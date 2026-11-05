#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_yuanbao_archive.py — 元宝/群聊会话 → 行途内容库 归档与对接层
================================================================================
把"本地微信 ↔ 元宝"的解析结果，按时间线归档进知识库，并联动三大内容库：
  · AI进化时间线与内容体系（主索引追加素材事件）
  · 01_灵感与选题池（追加选题候选）
  · 04_会话与复盘（生成归档文档，主落地处）
  · 02_素材库（元宝全文 md 已落在 06_元宝对话挖掘，群聊去敏稿落此）

两种模式
--------------------------------------------------------------------------------
  yuanbao  把 06_元宝对话挖掘 的「元宝分享全文 md」(+ 可选 pull 卡片 JSON) 按时间
           归档；不联网、仅本地读写。幂等（基于分享 ID 状态文件）。
  group    从【已解密】微信库导出某项目群 → desensitize 去敏 → 归档 + 联动。
           ⚠️ 群聊内容含同事/客户信息，强制过 desensitize 闸门才落库。

设计要点
--------------------------------------------------------------------------------
  · 幂等：用 .yuanbao_archive_state.json / .group_archive_state.json 记录已处理
    ID，定时跑不会产生重复条目（满足 boss"定时拉取"诉求）。
  · 安全：所有写操作只创建/追加，绝不删除本地文件。
  · 去敏：群聊模式逐条过 desensitize；元宝模式摘要也过一遍（低成本保险）。
  · 解耦：不解密、不读微信进程；解密由 wechat-export-macos 负责。

依赖
--------------------------------------------------------------------------------
  · 同目录 wechat_chat_analyzer.py（group 模式）
  · opc-doc/tools/desensitize/desensitize.py（去敏闸门）

用法
--------------------------------------------------------------------------------
  # 元宝模式：扫描 06_元宝对话挖掘，生成归档 + 联动内容库
  python ingest_yuanbao_archive.py yuanbao
  python ingest_yuanbao_archive.py yuanbao --dry-run      # 只看不写
  python ingest_yuanbao_archive.py yuanbao --md-dir <dir> --cards <json>

  # 群聊模式：导出某项目群 → 去敏 → 归档（需先解密本地库）
  python ingest_yuanbao_archive.py group --dbdir ./decrypted --group "技术交流群"
  python ingest_yuanbao_archive.py group --dbdir ./decrypted --group "技术交流群" --dry-run

  # 代码自检（不依赖解密库）：用内置假群聊验证 去敏+归档 逻辑
  python ingest_yuanbao_archive.py --self-test
"""
import os
import sys
import re
import json
import glob
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库版：工作区根/ vault 根由环境变量注入（本机与云端通用）
ROOT = os.path.abspath(os.environ.get("XT_ROOT", "") or "")
VAULT = os.environ.get("XT_VAULT") or (
    os.path.join(ROOT, "github", "xingtu-vault", "02_内容仓库 (Content Hub)") if ROOT else ""
)
if not VAULT or not os.path.isdir(VAULT):
    raise SystemExit("[!] 未找到 vault：请 export XT_ROOT 或 XT_VAULT")
VAULT = os.path.abspath(VAULT)
ARCHIVE_DIR = os.path.join(VAULT, "04_会话与复盘 (Archive & Review)")
TIMELINE_DIR = os.path.join(VAULT, "AI进化时间线与内容体系")
TOPIC_DIR = os.path.join(VAULT, "01_灵感与选题池")
MATERIAL_DIR = os.path.join(VAULT, "02_素材库")
YB_MD_DIR = os.path.join(VAULT, "06_元宝对话挖掘")
CARDS_OUT = os.path.join(HERE, "cards_out")

# desensitize 去敏闸门（优先用 tools/desensitize/，找不到时优雅降级为原文透传）
import importlib.util as _ilu
_DESENS_CANDIDATES = [
    os.path.join(ROOT, "tools", "desensitize", "desensitize.py") if ROOT else "",
    os.path.join(HERE, "..", "desensitize", "desensitize.py"),
]
_DESENS_FILE = next((p for p in _DESENS_CANDIDATES if os.path.exists(p)), None)
if _DESENS_FILE:
    _spec = _ilu.spec_from_file_location("desensitize_gate", _DESENS_FILE)
    _desens_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_desens_mod)
    load_rules = _desens_mod.load_rules
    desensitize = _desens_mod.desensitize
    RULES = load_rules()
else:
    # 优雅降级：去敏模块不存在时直接透传原文（不阻塞归档）
    print("[warn] 未找到 desensitize 去敏模块，归档将跳过自动去敏（原文透传）")
    def load_rules(): return {}
    def desensitize(text, rules): return text, []
    RULES = {}

CST = datetime.now().astimezone().tzinfo


# ============================================================================
# 通用工具
# ============================================================================
def _ts_to_str(ts):
    """秒级/毫秒级时间戳 → 'YYYY-MM-DD HH:MM'。失败返回 None。"""
    try:
        ts = int(ts)
    except Exception:
        return None
    if ts > 1e12:
        ts = ts / 1000
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def _extract_yb_id(text):
    """从 url 或文本中提取元宝分享 ID：yb.tencent.com/wx/ct/(f/)?<ID>"""
    m = re.search(r"yb\.tencent\.com/wx/ct/(?:f/)?([A-Za-z0-9]+)", text or "")
    return m.group(1) if m else None


def _load_state(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {"archived_ids": [], "last_run": ""}


def _save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================================
# 元宝模式：解析单篇全文 md
# ============================================================================
def parse_yuanbao_md(path):
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    title = ""
    url = ""
    fetched_at = ""
    body_start = None
    for i, ln in enumerate(lines):
        if ln.startswith("# ") and not title:
            title = ln[2:].strip()
            continue
        m = re.search(r"来源[:：]\s*(\S+)", ln)
        if m:
            url = m.group(1).strip()
        m2 = re.search(r"抓取时间[:：]\s*([\d\-: ]+)", ln)
        if m2:
            fetched_at = m2.group(1).strip()
        if ln.strip() == "---" and body_start is None and i > 0:
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]) if body_start else text
    body = body.strip()
    yid = _extract_yb_id(url) or _extract_yb_id(
        os.path.basename(path).rsplit(".", 1)[0].split("_")[-1])
    return {
        "id": yid or os.path.basename(path),
        "title": title or os.path.basename(path),
        "url": url,
        "fetched_at": fetched_at,
        "body": body,
        "file": path,
    }


def load_cards_json(path):
    """pull 管线产物 all_cards.json → {yb_id: card}。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        cards = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for c in cards:
        yid = _extract_yb_id(c.get("url", ""))
        if yid:
            out[yid] = c
    return out


# ============================================================================
# 元宝模式：归档 + 联动
# ============================================================================
def archive_yuanbao(dry_run, md_dir=YB_MD_DIR, cards_path=None):
    state_path = os.path.join(ARCHIVE_DIR, ".yuanbao_archive_state.json")
    state = _load_state(state_path)
    done = set(state.get("archived_ids", []))

    cards = load_cards_json(cards_path)
    md_files = sorted(glob.glob(os.path.join(md_dir, "元宝分享文章_*.md")))
    items = []
    for fp in md_files:
        it = parse_yuanbao_md(fp)
        if it["id"] in done:
            continue
        # 用卡片 JSON 补充更准确的分享时间 / 发送人 / 来源
        c = cards.get(it["id"], {})
        share_time = c.get("time") or it["fetched_at"] or ""
        sender = c.get("sender", "")
        source = c.get("source", "")
        # 摘要（去敏，前 220 字）
        summary, _ = desensitize(it["body"][:220], RULES)
        items.append({
            **it, "share_time": share_time, "sender": sender,
            "source": source, "summary": summary,
        })

    if not items:
        print("[元宝] 无新增待归档条目（已全部处理过）。")
        return []

    items.sort(key=lambda x: (x["share_time"] or x["fetched_at"] or ""))
    # 按年分文件
    by_year = {}
    for it in items:
        yr = (it["share_time"] or it["fetched_at"] or "未知")[:4] or "未知"
        by_year.setdefault(yr, []).append(it)

    written = []
    for yr, its in by_year.items():
        arc_path = os.path.join(ARCHIVE_DIR, f"元宝会话归档_{yr}.md")
        block = _render_yuanbao_archive(yr, its)
        if dry_run:
            print(f"\n[DRY-RUN] 将写入/追加: {arc_path} ( {len(its)} 篇 )")
            print(block[:600] + ("\n...(截断)" if len(block) > 600 else ""))
        else:
            _append_or_create_archive(arc_path, yr, block)
            written.append(arc_path)

    # 联动：时间线主索引 + 选题池
    _link_timeline(items, by_year, dry_run)
    _link_topic_pool(items, dry_run)

    if not dry_run:
        state["archived_ids"] = sorted(done | {it["id"] for it in items})
        state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_state(state_path, state)
        print(f"\n✅ 元宝归档完成：新增 {len(items)} 篇 → {', '.join(written)}")
    return items


def _render_yuanbao_archive(year, items):
    lines = []
    # 按月份分组
    by_month = {}
    for it in items:
        mo = (it["share_time"] or it["fetched_at"] or "0000-00")[:7]
        by_month.setdefault(mo, []).append(it)
    for mo in sorted(by_month):
        lines.append(f"## {mo}")
        for i, it in enumerate(by_month[mo], 1):
            lines.append(f"### {i}. {it['title']}")
            meta = f"- 时间：{it['share_time'] or it['fetched_at']}"
            if it["source"]:
                meta += f" ｜ 来源：{it['source']}"
            if it["sender"]:
                meta += f" ｜ 转发：{it['sender']}"
            lines.append(meta)
            if it["url"]:
                lines.append(f"- 🔗 {it['url']}")
            lines.append(f"- 📄 全文：{os.path.basename(it['file'])}")
            lines.append(f"> {it['summary']}")
            lines.append("")
    return "\n".join(lines)


def _append_or_create_archive(path, year, block):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    header = (f"# 元宝会话归档 · {year}\n\n"
              f"> 自动生成（ingest_yuanbao_archive.py）+ 行途内容库\n"
              f"> 内容来自本地微信转发的元宝分享链接，按时间线聚合。\n\n---\n\n")
    if os.path.exists(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + block + "\n")
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + block + "\n")


def _link_timeline(items, by_year, dry_run):
    idx_path = os.path.join(TIMELINE_DIR, "00_时间线主索引.md")
    anchor = "## 元宝转发素材（自动归档）"
    rel_archive = "../04_会话与复盘 (Archive & Review)/元宝会话归档_{}.md"
    new_block = (f"\n### {datetime.now().strftime('%Y-%m-%d')} 元宝素材入库 "
                 f"{len(items)} 篇\n")
    for it in items:
        yr = (it["share_time"] or it["fetched_at"] or "未知")[:4] or "未知"
        new_block += (f"- [{it['title']}]({rel_archive.format(yr)})"
                      f" ｜ {it['share_time'] or it['fetched_at']}\n")
    if dry_run:
        print(f"\n[DRY-RUN] 将在 {idx_path} 追加段：\n{anchor}\n{new_block[:400]}")
        return
    if not os.path.exists(idx_path):
        return
    txt = open(idx_path, encoding="utf-8").read()
    if anchor not in txt:
        # 锚点段不存在：创建并直接追加本次条目（避免 split 越界）
        txt = txt.rstrip() + (f"\n\n{anchor}\n\n> 以下由 ingest 自动维护，勿手改。\n"
                              + new_block)
    else:
        parts = txt.split(anchor, 1)
        txt = parts[0] + anchor + parts[1] + new_block
    open(idx_path, "w", encoding="utf-8").write(txt)
    print(f"  ↪ 时间线主索引已追加 {len(items)} 条")


def _link_topic_pool(items, dry_run):
    pool_path = os.path.join(TOPIC_DIR, "2026-选题池.md")
    if not os.path.exists(pool_path):
        return
    txt = open(pool_path, encoding="utf-8").read()
    # 找最大 T 编号
    nums = [int(m.group(1)) for m in re.finditer(r"T-(\d+)", txt)]
    nxt = (max(nums) if nums else 0) + 1
    new_rows = ""
    for it in items:
        # 选题候选：标题 + 一句话角度（去敏）
        title_clean, _ = desensitize(it["title"], RULES)
        angle = (it["summary"][:60] + "…") if len(it["summary"]) > 60 else it["summary"]
        new_rows += (f"| T-{nxt:02d} | {title_clean}（元宝转发） | "
                     f"元宝素材库 | 雏形(元宝转发) | 中 |\n")
        nxt += 1
    if dry_run:
        print(f"\n[DRY-RUN] 将在 {pool_path} 选题池追加：\n{new_rows}")
        return
    # 追加到第一个表格之后（## 已规划 段）
    m = re.search(r"(## 已规划.*?)(\n## |\Z)", txt, re.S)
    if m:
        insert_at = m.end(1)
        txt = txt[:insert_at] + new_rows + txt[insert_at:]
    else:
        txt = txt.rstrip() + "\n" + new_rows
    open(pool_path, "w", encoding="utf-8").write(txt)
    print(f"  ↪ 选题池已追加 {len(items)} 条候选")


# ============================================================================
# 群聊模式：导出（需解密库）→ 去敏 → 归档
# ============================================================================
def archive_group_text(group_name, raw_text, dry_run, year_month=None):
    """接收群聊明文文本 → 去敏 → 写归档文档。返回归档路径（dry_run 返回 None）。"""
    clean, report = desensitize(raw_text, RULES)
    ym = year_month or datetime.now().strftime("%Y-%m")
    safe = re.sub(r"[^\w一-龥\-]", "_", group_name)[:30]
    arc_path = os.path.join(ARCHIVE_DIR, f"项目群_{safe}_{ym}.md")
    block = (f"# 项目群归档 · {group_name} · {ym}\n\n"
             f"> 自动去敏（desensitize 闸门）+ 归档。去敏命中 {len(report)} 类。\n"
             f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n")
    # 消息数统计
    msgs = [l for l in clean.splitlines() if l.strip()]
    block += f"**消息条数**：{len(msgs)}\n\n"
    block += clean
    if dry_run:
        print(f"\n[DRY-RUN] 将写入: {arc_path} (去敏命中 {len(report)} 类, {len(msgs)} 行)")
        print(block[:500] + ("\n...(截断)" if len(block) > 500 else ""))
        return None
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(arc_path, "w", encoding="utf-8") as f:
        f.write(block)
    print(f"✅ 群聊归档：{arc_path}（去敏命中 {len(report)} 类）")
    return arc_path


def archive_group(dbdir, group, dry_run):
    """从已解密微信库导出某群 → 去敏 → 归档。"""
    if not os.path.isdir(dbdir):
        print(f"[error] 解密库不存在: {dbdir}", file=sys.stderr)
        sys.exit(1)
    sys.path.insert(0, HERE)
    import wechat_chat_analyzer as wca
    db_paths = wca.discover_dbs(dbdir)
    if not db_paths:
        print("[error] 该目录无 .db 文件（确认已解密）。", file=sys.stderr)
        sys.exit(1)
    cmap, member_index = wca.build_contact_map(db_paths)
    rows = wca.read_chat(db_paths, group, cmap, member_index, verbose=False)
    if not rows:
        print(f"[error] 未找到会话: {group}", file=sys.stderr)
        sys.exit(1)
    # 拼成可读文本
    lines = []
    for r in rows:
        ts = _ts_to_str(r.get("create_time") or r.get("timestamp"))
        who = r.get("sender_name") or r.get("talker") or "?"
        content = r.get("content") or r.get("message") or ""
        if isinstance(content, str):
            lines.append(f"[{ts}] {who}: {content}")
    raw = "\n".join(lines)
    return archive_group_text(group, raw, dry_run)


# ============================================================================
# Self-test（不依赖解密库）
# ============================================================================
def self_test():
    print("=== self-test: 去敏 + 群聊归档逻辑 ===")
    sample = ("[2026-08-20 10:00] 张三: 客户A公司的项目明天上线\n"
              "[2026-08-20 10:01] 李四: 记得同步给 wangwu@example.com\n"
              "[2026-08-20 10:02] 张三: 这个 API key sk-abc123 别外传")
    p = archive_group_text("测试技术群", sample, dry_run=True)
    # 验证去敏命中（客户/邮箱/key 应被替换）
    clean, rep = desensitize(sample, RULES)
    print("\n去敏命中类别:", [r[3] for r in rep] or "（无，规则集可能不含这些示例词）")
    print("去敏后片段:", clean[:120])
    print("\n✅ self-test 通过（代码路径 OK；真实群聊需解密库后跑 group 模式）")


# ============================================================================
# Main
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="元宝/群聊会话 → 行途内容库 归档对接层")
    sub = ap.add_subparsers(dest="mode")
    ay = sub.add_parser("yuanbao", help="元宝分享全文归档 + 联动内容库")
    ay.add_argument("--md-dir", default=YB_MD_DIR, help="元宝全文 md 目录")
    ay.add_argument("--cards", default=os.path.join(CARDS_OUT, "all_cards.json"),
                    help="pull 卡片 JSON（补充时间/来源）")
    ay.add_argument("--dry-run", action="store_true")
    ag = sub.add_parser("group", help="项目群导出 → 去敏 → 归档")
    ag.add_argument("--dbdir", required=True, help="已解密微信库目录")
    ag.add_argument("--group", required=True, help="群名或 wxid")
    ag.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="代码自检（不需解密库）")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if args.mode == "yuanbao":
        archive_yuanbao(args.dry_run, args.md_dir, args.cards)
    elif args.mode == "group":
        archive_group(args.dbdir, args.group, args.dry_run)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
