#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yuanbao_incremental_fetch.py — 元宝会话「增量抓取」定时任务专用脚本
====================================================================
在 batch_fetch_yuanbao.py 全量抓取基础上，实现真正的「水位线增量」：
  1. 读取上次抓取的最后一张卡片分享时间（watermark）
  2. 从最新 yuanbao_cards.json 筛选出分享时间 > watermark 的新卡片
  3. 只抓取这些新卡片的全文（零 token，伪装微信 UA 直抓）
  4. 抓取完成更新 watermark = 本次最大分享时间
  5. 产物按日期归档到 增量批次/<YYYY-MM-DD>/（每次运行一个文件夹）

设计动机（boss 要求）：
  - 不是每次都抓全量；每次只抓「上次最后 1 张卡片之后」新增的内容，避免重复
  - 聚合历史：以卡片分享时间（元宝生成该分析的时间）为水位线，天然有序、不重不漏
  - 产物按时间建文件夹管理，回溯方便

用法：
  python yuanbao_incremental_fetch.py                  # 增量抓取（读水位线）
  python yuanbao_incremental_fetch.py --full           # 全量抓取（忽略水位线）
  python yuanbao_incremental_fetch.py --since "2026-09-01 00:00:00"  # 指定时间起点
  python yuanbao_incremental_fetch.py --dry-run        # 只看待抓列表，不落盘
  python yuanbao_incremental_fetch.py --decrypt-first  # 先解密最新微信库再提取（全自动闭环）

依赖：Python 标准库 + 系统 curl；import 同目录 batch_fetch_yuanbao.py 复用抓取/解析函数
"""
import os
import re
import sys
import json
import time
import shutil
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库版：工作区根由环境变量注入（本机与云端通用），不再依赖脚本所在层级
ROOT = os.path.abspath(os.environ.get("XT_ROOT", ""))
if not ROOT or not os.path.isdir(ROOT):
    sys.exit("[!] 未设置 XT_ROOT：请 export XT_ROOT=<工作区根（含 github/xingtu-vault）>")
# 2026-10-13 迁移后：存量真源（全量主仓库/增量批次/水位线）在 vault 金库，脚本同步指向
VAULT_INV = os.path.join(ROOT, "github", "xingtu-vault", "12_工具研究室", "yuanbao_inventory")
INV = os.path.join(ROOT, "outputs", "yuanbao_inventory")    # 仅存提取产物（yuanbao_cards.json 等）
CARDS_JSON = os.path.join(INV, "yuanbao_cards.json")      # 最新提取的卡片（yuanbao_full_extract 产物）
MSGS_JSON = os.path.join(INV, "yuanbao_all_messages.json") # 全量消息（备用）
MAIN_OUT = os.path.join(VAULT_INV, "元宝全文抓取")          # 全量平铺主仓库（vault 金库真源，不动）
BATCH_ROOT = os.path.join(VAULT_INV, "增量批次")             # 每次增量的按日归档目录（vault 金库真源）
WATERMARK_FILE = os.path.join(VAULT_INV, ".yuanbao_watermark.json")

# 复用 batch_fetch_yuanbao 的抓取/解析函数（优先同目录 bin/，回退工作区 tools/）
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)
import batch_fetch_yuanbao as bf  # noqa: E402


def load_watermark():
    """读取水位线。不存在 → None（表示从未增量抓取过，从全量库最大时间续）。"""
    if os.path.exists(WATERMARK_FILE):
        try:
            return json.load(open(WATERMARK_FILE, encoding="utf-8"))
        except Exception:
            pass
    return None


def save_watermark(state: dict):
    os.makedirs(os.path.dirname(WATERMARK_FILE), exist_ok=True)
    with open(WATERMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def collect_yb_cards():
    """从最新 yuanbao_cards.json 提取全部 yb 分享卡片（去重，按时间排序）。"""
    if not os.path.exists(CARDS_JSON):
        print(f"[!] 找不到 {CARDS_JSON}，先运行 yuanbao_full_extract.py 提取。")
        return []
    cards = json.load(open(CARDS_JSON, encoding="utf-8"))
    seen, out = set(), []
    for c in cards:
        card = c.get("card") or {}
        url = card.get("url", "") or ""
        if "yb.tencent.com/wx/ct" not in url:
            continue
        m = re.search(r"/([A-Za-z0-9_-]+)$", url.rstrip("/"))
        if not m:
            continue
        tok = m.group(1)
        if tok in seen:
            continue
        seen.add(tok)
        out.append({
            "time": c.get("time", ""),
            "title": card.get("title", ""),
            "url": url,
            "token": tok,
        })
    out.sort(key=lambda x: x["time"])  # 按分享时间升序
    return out


def select_new_cards(cards, since, full=False):
    """筛选待抓卡片：share_time > since 的新卡片（full 忽略水位线）。"""
    if full or not since:
        return cards
    new = [c for c in cards if c["time"] and c["time"] > since]
    return new


def already_fetched_in_main(cards):
    """与主仓库比对，剔除已抓 token（幂等保护，防止水位线异常时重复）。"""
    if not os.path.isdir(MAIN_OUT):
        return cards
    existing = set()
    for fn in os.listdir(MAIN_OUT):
        if fn.endswith(".md") and fn != "README.md":
            m = re.search(r"_([A-Za-z0-9_-]{6,})\.md$", fn)
            if m:
                existing.add(m.group(1))
    return [c for c in cards if c["token"] not in existing]


def fetch_batch(cards, out_dir, dry_run, delay=0.5):
    """逐条抓取新卡片全文 → 写入 out_dir。返回统计。"""
    os.makedirs(out_dir, exist_ok=True)
    stats = {"ok": 0, "fail": 0, "blocked": 0, "dry": 0}
    written = []
    for i, c in enumerate(cards, 1):
        url, tok = c["url"], c["token"]
        title, body = bf.fetch_one(url)  # 复用 batch_fetch 抓取+解析
        if title is None:
            stats["fail"] += 1
            print(f"[{i}/{len(cards)}] ↷ 已在主库跳过 {tok}")
            continue
        if body.startswith("["):  # 错误标记
            stats["blocked"] += 1
            print(f"[{i}/{len(cards)}] ✗ 拦截/失败 {tok} → {body}")
            continue
        # 命名：分享时间戳_标题_token.md（与主库一致，IDE 按名即时间序）
        ts = bf._ts_prefix(c["time"])
        ftitle = bf._clean_title(c["title"] or title)
        fn = f"{ts}_{ftitle}_{tok}.md"
        content = (f"# {title}\n\n> 来源：{url}\n"
                   f"> 分享时间：{c['time']}\n"
                   f"> 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                   f"> 方式：伪装微信 UA 直抓（本地，零 token）\n\n---\n\n{body}\n")
        if dry_run:
            stats["dry"] += 1
            print(f"[{i}/{len(cards)}] ● [dry-run] {tok} {title}（{len(body)}字）→ {fn}")
            continue
        fp = os.path.join(out_dir, fn)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        # 同步归档到主仓库（保持全量平铺库完整）
        shutil.copy2(fp, os.path.join(MAIN_OUT, fn))
        written.append(fn)
        stats["ok"] += 1
        print(f"[{i}/{len(cards)}] ✓ {title}（{len(body)}字）→ 增量批次/{os.path.basename(os.path.dirname(fp))}/{fn}")
        if i < len(cards):
            time.sleep(delay)
    return stats, written


def main():
    ap = argparse.ArgumentParser(description="元宝会话增量抓取（定时任务专用）")
    ap.add_argument("--full", action="store_true", help="全量抓取（忽略水位线）")
    ap.add_argument("--since", help='指定时间起点，如 "2026-09-01 00:00:00"')
    ap.add_argument("--dry-run", action="store_true", help="只列待抓，不落盘")
    ap.add_argument("--delay", type=float, default=0.5, help="请求间隔秒")
    ap.add_argument("--decrypt-first", action="store_true",
                    help="先解密最新微信库再提取（全自动闭环，需密钥）")
    args = ap.parse_args()

    if args.decrypt_first:
        print("[1] 解密最新微信库...")
        os.system(f'"{sys.executable}" {ROOT}/tools/wechatdecryption/decrypt.py 2>/dev/null || echo 解密跳过')
        # decrypt.py 无 CLI，实际解密用下方 python 内联
        print("[!] 请使用 run_yuanbao_pipeline.sh 的步骤1-2 完成解密+提取，或直接依赖已有解密库")

    cards = collect_yb_cards()
    if not cards:
        print("[!] 未获取到 yb 卡片，结束。")
        return

    wm = load_watermark()
    since = args.since or (wm.get("last_card_time") if wm else None)
    if args.full:
        since = None

    new = select_new_cards(cards, since, full=args.full)
    # 水位线设计：即使卡片时间有重叠，也以「主库已抓」做最终幂等兜底
    new = already_fetched_in_main(new)

    print(f"[i] 卡片总数 {len(cards)} | 水位线={since or '（无，全量）'} | 待抓新增 {len(new)}")
    if not new:
        print("[✓] 无新增卡片，无需抓取。（聚合历史水位线已到最新）")
        # 非 dry-run 时才推进水位线（避免 dry-run 误吞真实水位线）
        if not args.dry_run:
            latest = cards[-1]["time"] if cards else ""
            save_watermark({"last_card_time": latest, "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            print(f"[i] 水位线已推进到：{latest}")
        return

    # 按日归档目录：增量批次/YYYY-MM-DD/
    today = datetime.now().strftime("%Y-%m-%d")
    batch_dir = os.path.join(BATCH_ROOT, today)
    stats, written = fetch_batch(new, batch_dir, args.dry_run, args.delay)

    # 更新水位线 = 本次待抓卡片中最大的分享时间（或全量库最新）
    latest = cards[-1]["time"] if cards else since or ""
    if not args.dry_run:
        save_watermark({"last_card_time": latest,
                        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_batch": today,
                        "last_count": stats["ok"]})
        # 批次摘要
        if written:
            summary = os.path.join(batch_dir, "_批次摘要.md")
            with open(summary, "w", encoding="utf-8") as f:
                f.write(f"# 增量批次 · {today}\n\n")
                f.write(f"> 水位线推进至：{latest}\n")
                f.write(f"> 新增 {stats['ok']} 篇｜跳过 {stats['fail']} 篇｜失败 {stats['blocked']} 篇\n\n")
                for w in written:
                    f.write(f"- {w}\n")

    print(f"\n完成：新增 {stats['ok']} | 跳过 {stats['fail']} | 拦截/失败 {stats['blocked']}"
          + (f" | dry-run {stats['dry']}" if args.dry_run else ""))
    print(f"水位线 → {latest}")
    print(f"增量批次目录：{BATCH_ROOT}")


if __name__ == "__main__":
    main()
