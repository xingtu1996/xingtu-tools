#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_fetch_yuanbao.py — 元宝分享链接批量抓取器（纯本地，零 token）
=====================================================================
从元宝会话消息中提取全部 yb 分享链接，伪装微信 UA 批量抓取全文，
输出到 github/xingtu-vault/12_工具研究室/yuanbao_inventory/元宝全文抓取/ 目录。
纯标准库 + 系统 curl，不调用任何 AI 接口，不消耗 token。

用法：
  python batch_fetch_yuanbao.py                 # 全量抓取
  python batch_fetch_yuanbao.py --url URL       # 只抓指定链接
  python batch_fetch_yuanbao.py --urls urls.txt # 从文件读取链接
  python batch_fetch_yuanbao.py --fresh         # 忽略已存在，强制重抓
  python batch_fetch_yuanbao.py --limit 50      # 只抓前50条（测试用）
"""
import os, sys, re, json, html, time, argparse, subprocess, hashlib
from datetime import datetime

# 微信 iOS UA（绕过元宝分享页的微信环境校验）
WECHAT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
             "MicroMessenger/8.0.38(0x18002623) NetType/WIFI Language/zh_CN")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../xingtu
OUT_DIR = os.path.join(ROOT, "github", "xingtu-vault", "12_工具研究室", "yuanbao_inventory", "元宝全文抓取")
ALL_MSGS = os.path.join(ROOT, "github", "xingtu-vault", "12_工具研究室", "yuanbao_inventory", "yuanbao_all_messages.json")
ALL_CARDS = os.path.join(ROOT, "github", "xingtu-vault", "12_工具研究室", "yuanbao_inventory", "yuanbao_cards.json")


def collect_urls():
    """从元宝会话消息中提取全部 yb 分享链接"""
    if not os.path.exists(ALL_MSGS):
        print(f"[!] 找不到 {ALL_MSGS}，先运行提取脚本生成它。")
        return []
    msgs = json.load(open(ALL_MSGS, encoding="utf-8"))
    urls, seen = [], set()
    for m in msgs:
        c = m.get("card") or {}
        u = c.get("url", "")
        if "yb.tencent.com/wx/ct" in u and u not in seen:
            seen.add(u)
            urls.append((m.get("time", ""), c.get("title", ""), u))
    print(f"[i] 从会话中提取到 {len(urls)} 个 yb 分享链接")
    return urls


def html_to_markdown(raw):
    """HTML → Markdown：保留表格/标题/列表/强调，清除零宽字符。"""
    s = raw
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    # 表格 → Markdown
    def _conv_table(m):
        inner = m.group(1)
        rows = []
        for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", inner, re.I):
            cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr, re.I)
            cleaned = [re.sub(r"<[^>]+>", "", html.unescape(c)).strip() for c in cells]
            if not cleaned: continue
            if not rows:
                rows.append("| " + " | ".join(cleaned) + " |")
                rows.append("|" + "|".join(" --- " for _ in cleaned) + "|")
            else:
                rows.append("| " + " | ".join(cleaned) + " |")
        return "\n".join(rows)
    s = re.sub(r"<table[^>]*>([\s\S]*?)</table>", _conv_table, s, flags=re.I)
    # 标题
    for i in range(6, 0, -1):
        tag = f"h{i}"
        s = re.sub(rf"<{tag}[^>]*>(.*?)</{tag}>",
                   lambda m, n=i: "#"*n + " " + re.sub(r"<[^>]+>", "", html.unescape(m.group(1))).strip(),
                   s, flags=re.I | re.S)
    # 列表
    def _li(m):
        c = m.group(1).strip()
        plain = re.sub(r"<[^>]+>", "", c).strip()
        if re.match(r"^([\u2022\u00b7\-*\u2726\u2713\u25e6\u25b8]\s?|\d+[.)]\s?)", plain):
            return c
        return "- " + c
    s = re.sub(r"<li[^>]*>(.*?)</li>", _li, s, flags=re.I | re.S)
    s = re.sub(r"</?[uo]l[^>]*>", "\n", s, flags=re.I)
    # 段落/换行
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s, flags=re.I)
    s = re.sub(r"<p[^>]*>|<div[^>]*>", "\n", s, flags=re.I)
    # 强调
    s = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", s, flags=re.I | re.S)
    s = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", s, flags=re.I | re.S)
    s = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", s, flags=re.I | re.S)
    # 剩余标签
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    # 零宽/特殊空格
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        s = s.replace(ch, "")
    s = s.replace("\u00a0", " ")
    # 空白整理
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"([\u2022\u00b7\-*\u2726\u2713\u25e6\u25b8]|\d+[.)])\s*\n[ \t]*(?=\S)", r"\1 ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def extract_title_and_body(raw, token):
    """从 HTML 提取 (标题, 正文)。正文从"听全文"锚点后开始（关键）。"""
    title = ""
    # 1) __NEXT_DATA__ JSON 里的 shareCardInfo.title
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw, re.S)
    if m:
        try:
            pp = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
            ci = pp.get("data", {}).get("conversation_info", {})
            if ci.get("shareCardInfo", {}).get("title"):
                title = ci["shareCardInfo"]["title"]
        except Exception:
            pass
    # 2) 结构化 Markdown
    md = html_to_markdown(raw)
    # 3) 标题回退：取"听全文"之前、UI 用户名之后的第一行
    if not title:
        # SAF-010：作者显示名不得硬编码进公开仓，改由环境变量注入
        _author = os.environ.get("YUANBAO_AUTHOR_NAME", "")
        i_user = md.find(_author) if _author else -1
        i_full = md.find("听全文")
        if i_user != -1 and i_full != -1 and i_user < i_full:
            cand = md[i_user + 9:i_full].strip()
            cand = re.split(r"元宝", cand)[0].strip()
            if cand:
                title = cand
    # 4) 正文：取"听全文"之后
    if "听全文" in md:
        body = md[md.find("听全文") + 3:].strip()
    else:
        body = md.strip()
    body = re.sub(r"^元宝\s*", "", body)
    title = title or token
    return title.strip(), body.strip()


def fetch_one(url, force=False):
    """抓取单个链接 → 返回 (标题, 正文) 或 (None, None)"""
    token = url.rstrip("/").split("/")[-1]
    safe_id = re.sub(r"[^\w\-]", "_", token)[:24]
    out_md = os.path.join(OUT_DIR, f"元宝文章_{safe_id}.md")
    if os.path.exists(out_md) and not force:
        return None, None  # 已存在，跳过

    # 用 curl 伪装微信 UA 抓取（macOS/Linux 自带）
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "30", "-A", WECHAT_UA, url],
            capture_output=True, timeout=40)
    except subprocess.TimeoutExpired:
        return ("", "[抓取超时]")
    if r.returncode != 0:
        return ("", "[curl失败]")
    htm = r.stdout.decode("utf-8", errors="replace")
    if not htm:
        return ("", "[空响应]")

    title, body = extract_title_and_body(htm, token)
    title = re.sub(r"[\\/:*?\"<>|\n]", "", title)[:60]

    if len(body) < 30:
        return (title, "[正文过短，可能被拦截：%d字]" % len(body))
    return (title, body)


def _clean_title(t):
    t = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', t or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t[:60]


def _ts_prefix(time_str):
    """从卡片时间 "2026-09-02 12:52:45" 提取文件名前缀 "20260902_1252"。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", time_str or "")
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}_{m.group(4)}{m.group(5)}"
    return "unknown"


def _load_token_meta():
    """从 yuanbao_cards.json 建立 token → {time, title} 映射（供文件名命名）。"""
    meta = {}
    try:
        cards = json.load(open(ALL_CARDS, encoding="utf-8"))
    except Exception:
        return meta
    for c in cards:
        card = c.get("card") or {}
        url = card.get("url", "") or ""
        m = re.search(r"/([A-Za-z0-9]{6,})$", url.rstrip("/"))
        if not m:
            continue
        token = m.group(1)
        if token not in meta:
            meta[token] = {"time": c.get("time", ""), "title": card.get("title", "")}
    return meta


def write_md(url, title, body):
    token = url.rstrip("/").split("/")[-1]
    # 用卡片元数据生成「时间戳_标题_token.md」文件名（IDE 里按名即按时间排序）
    meta = _load_token_meta().get(token, {})
    ts = _ts_prefix(meta.get("time"))
    ftitle = _clean_title(meta.get("title") or title)
    out_md = os.path.join(OUT_DIR, f"{ts}_{ftitle}_{token}.md")
    content = (f"# {title}\n\n> 来源：{url}\n"
               f"> 分享时间：{meta.get('time','')}\n"
               f"> 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
               f"> 方式：伪装微信 UA 直抓（本地，零 token）\n\n---\n\n{body}\n")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(content)
    return out_md


def main():
    ap = argparse.ArgumentParser(description="元宝分享链接批量抓取器（本地零token）")
    ap.add_argument("--url", help="只抓单个链接")
    ap.add_argument("--urls", help="从文件读取链接（每行一个）")
    ap.add_argument("--limit", type=int, default=0, help="最多抓 N 条（0=全部）")
    ap.add_argument("--fresh", action="store_true", help="忽略已存在，强制重抓")
    ap.add_argument("--delay", type=float, default=0.5, help="每次请求间隔秒数")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"输出目录：{OUT_DIR}")

    # 组装任务
    tasks = []
    if args.url:
        tasks.append(("", "", args.url))
    elif args.urls and os.path.exists(args.urls):
        for line in open(args.urls, encoding="utf-8"):
            line = line.strip()
            if line and "yb.tencent.com" in line:
                tasks.append(("", "", line))
    else:
        tasks = collect_urls()

    if args.limit > 0:
        tasks = tasks[:args.limit]
    if not tasks:
        print("[!] 没有可抓取的链接。")
        return

    print(f"[i] 待处理 {len(tasks)} 个链接（fresh={'是' if args.fresh else '否'}）")
    ok, skip, fail = 0, 0, 0
    for i, (stime, stitle, url) in enumerate(tasks, 1):
        title, body = fetch_one(url, force=args.fresh)
        if title is None:
            skip += 1
            print(f"[{i}/{len(tasks)}] ↷ 跳过（已存在） {url.split('/')[-1]}")
            continue
        if body.startswith("["):  # 错误标记
            fail += 1
            print(f"[{i}/{len(tasks)}] ✗ 失败 {url.split('/')[-1]} → {body}")
            continue
        out_md = write_md(url, title, body)
        ok += 1
        print(f"[{i}/{len(tasks)}] ✓ {title}（{len(body)}字）→ {os.path.basename(out_md)}")
        if i < len(tasks):
            time.sleep(args.delay)

    print(f"\n完成：新增 {ok} | 跳过 {skip} | 失败 {fail}")
    print(f"全部正文已存至：{OUT_DIR}")


if __name__ == "__main__":
    main()
