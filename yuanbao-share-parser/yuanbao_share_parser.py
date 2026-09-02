#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yuanbao_share_parser.py — 元宝微信分享链接解析器

把微信里「转发给元宝」后生成的分享页（yb.tencent.com/wx/ct/...）抓取下来，
从页面内嵌的 __NEXT_DATA__ 中提取对话内容（用户提问 / 元宝回答 / 视频号等富媒体），
输出为 Markdown 或 JSON，方便归档、检索、二次创作。

设计目标
--------
- 零依赖：仅用 Python 3 标准库（urllib / json / re / html / argparse）。
- 模拟微信移动端请求：默认带 MicroMessenger User-Agent + wx.qq.com Referer，
  与手机微信内打开分享页的行为一致，拿到完整 SSR 内容。
- 鲁棒解析：兼容 conversation_info.data.extra 与 dataObj.mergedQuestion 两种嵌套，
  自动递归解码「字符串化的 JSON」，无需关心具体层级。

用法
----
    # 抓成 Markdown 打到终端
    python yuanbao_share_parser.py "https://yb.tencent.com/wx/ct/f/YFuacU3Vg4MNk3"

    # 输出 JSON 到文件
    python yuanbao_share_parser.py "<URL>" --format json --output out.json

    # 只打印消息角色概览
    python yuanbao_share_parser.py "<URL>" --list

    # 用普通浏览器 UA（部分场景不需要微信 UA）
    python yuanbao_share_parser.py "<URL>" --browser-ua
"""

import argparse
import html
import json
import re
import sys
import urllib.request
import urllib.error
from urllib.parse import urlparse

# 模拟 iPhone 微信内打开分享页的请求头
WECHAT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.38(0x1800262c) NetType/WIFI Language/zh_CN"
)
REFERER = "https://wx.qq.com/"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
# 1. 抓取
# --------------------------------------------------------------------------- #
def fetch_html(url: str, use_wechat_ua: bool = True) -> str:
    """模拟微信移动端请求，返回分享页 HTML 文本。"""
    ua = WECHAT_UA if use_wechat_ua else BROWSER_UA
    headers = {
        "User-Agent": ua,
        "Referer": REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, "replace")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[HTTP 错误] {e.code} {e.reason} — 链接可能已失效或需要登录")
    except urllib.error.URLError as e:
        raise SystemExit(f"[网络错误] 无法访问 {url}：{e.reason}")


# --------------------------------------------------------------------------- #
# 2. 提取 __NEXT_DATA__
# --------------------------------------------------------------------------- #
def extract_next_data(html_text: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    if not m:
        raise SystemExit("[解析失败] 页面未包含 __NEXT_DATA__，可能不是元宝分享页或结构已变更")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SystemExit(f"[解析失败] __NEXT_DATA__ 不是合法 JSON：{e}")


# --------------------------------------------------------------------------- #
# 3. 递归解码「字符串化的 JSON」
# --------------------------------------------------------------------------- #
def _coerce(obj):
    """如果 obj 是看起来像 JSON 的字符串，就解一层；递归处理。"""
    if isinstance(obj, str):
        s = obj.strip()
        if s and s[0] in "{[":
            try:
                return _coerce(json.loads(s))
            except Exception:
                return obj
    return obj


def extract_messages(next_data: dict):
    """从 __NEXT_DATA__ 中挖出消息列表与对话元信息。"""
    try:
        node = next_data["props"]["pageProps"]["data"]
    except (KeyError, TypeError):
        raise SystemExit("[解析失败] 页面结构不符：缺少 props.pageProps.data")

    ci = node.get("conversation_info") or {}
    meta = {
        "conversationId": ci.get("conversationId"),
        "status": ci.get("status"),
    }
    data = ci.get("data") or node
    data = _coerce(data)

    raw_msgs = None
    if isinstance(data, dict):
        if data.get("extra"):
            raw_msgs = data["extra"]
        elif "dataObj" in data:
            do = _coerce(data["dataObj"])
            if isinstance(do, dict):
                raw_msgs = do.get("mergedQuestion")
                meta.setdefault("hasThinking", do.get("hasThinking"))
    raw_msgs = _coerce(raw_msgs)
    if not isinstance(raw_msgs, list):
        raw_msgs = [raw_msgs] if raw_msgs else []

    # 对话级元信息补充
    if isinstance(data, dict):
        meta.setdefault("convId", data.get("convId"))
        meta.setdefault("platform", data.get("platform"))
        chat_info = data.get("chatInfo")
        if isinstance(chat_info, list) and chat_info:
            ci0 = chat_info[0]
            if isinstance(ci0, dict):
                meta.setdefault("agentId", ci0.get("agentId"))

    return raw_msgs, meta


# --------------------------------------------------------------------------- #
# 4. 解析单条消息
# --------------------------------------------------------------------------- #
_TEXT_FIELDS = ("content", "text", "answer", "thinkText", "reasoningContent")
_MEDIA_FIELDS = ("author", "title", "coverUrl", "type", "duration", "exportId", "source", "mediaId")
_SKIP_SPEECH = ("[视频号消息]", "[图片]", "[视频]", "[文件]", "[链接]", "[语音]")


def parse_message(msg) -> dict | None:
    if not isinstance(msg, dict):
        return None
    speaker = msg.get("speaker") or msg.get("role") or "unknown"
    parts, media = [], []

    # 首选 speechesV2 结构
    for s in (msg.get("speechesV2") or []):
        c = s.get("content") if isinstance(s, dict) else None
        if isinstance(c, list):
            for it in c:
                if isinstance(it, dict):
                    txt = " ".join(str(it.get(f, "")) for f in _TEXT_FIELDS if it.get(f))
                    if txt.strip():
                        parts.append(txt.strip())
                    if any(it.get(k) for k in ("coverUrl", "author", "title")):
                        media.append({k: it.get(k) for k in _MEDIA_FIELDS if it.get(k)})
                elif isinstance(it, str):
                    parts.append(it)
        elif isinstance(c, str):
            parts.append(c)

    # 兜底：兼容老结构
    if not parts:
        if isinstance(msg.get("content"), str):
            parts.append(msg["content"])
        sp = msg.get("speech")
        if isinstance(sp, str) and sp not in _SKIP_SPEECH:
            parts.append(sp)

    return {
        "speaker": speaker,
        "text": "\n".join(p for p in parts if p).strip(),
        "media": media,
    }


# --------------------------------------------------------------------------- #
# 5. 渲染
# --------------------------------------------------------------------------- #
def render_markdown(conversation: dict) -> str:
    meta = conversation["meta"]
    lines = []
    cid = (meta.get("conversationId") or meta.get("convId") or "unknown")[:8]
    lines.append(f"# 元宝分享解析 · {cid}\n")

    info = []
    if meta.get("agentId"):
        info.append(f"Agent: `{meta['agentId']}`")
    if meta.get("platform"):
        info.append(f"平台: {meta['platform']}")
    if meta.get("status") is not None:
        info.append(f"状态: {meta['status']}")
    if info:
        lines.append("> " + "  ·  ".join(info) + "\n")

    for idx, msg in enumerate(conversation["messages"], 1):
        if msg["speaker"] == "human":
            role = "🧑 用户"
        elif msg["speaker"] in ("ai", "assistant"):
            role = "🤖 元宝"
        else:
            role = msg["speaker"]
        lines.append(f"\n## {idx}. {role}\n")
        if msg["text"]:
            lines.append(msg["text"])
        for m in msg["media"]:
            if m.get("author"):
                lines.append(f"\n> 来源账号：{m['author']}")
            if m.get("coverUrl"):
                lines.append(f"\n![封面]({m['coverUrl']})")
            if m.get("duration"):
                lines.append(f"\n> 时长：{m['duration']}s")
    lines.append("\n---\n*由 yuanbao_share_parser 抓取解析*")
    return "\n".join(lines)


def render_json(conversation: dict) -> str:
    return json.dumps(conversation, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# 6. CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="元宝微信分享链接解析器（零依赖，标准库实现）",
    )
    ap.add_argument("url", help="元宝分享链接，形如 https://yb.tencent.com/wx/ct/f/xxxx")
    ap.add_argument("-f", "--format", choices=("md", "json"), default="md", help="输出格式（默认 md）")
    ap.add_argument("-o", "--output", help="输出到文件（默认打印到终端）")
    ap.add_argument("--list", action="store_true", help="只打印消息角色概览")
    ap.add_argument("--browser-ua", action="store_true", help="用普通浏览器 UA 代替微信 UA")
    args = ap.parse_args()

    if not urlparse(args.url).netloc.endswith("yb.tencent.com"):
        print("[提示] 该工具面向 yb.tencent.com 分享链接，其他域名可能解析失败", file=sys.stderr)

    html_text = fetch_html(args.url, use_wechat_ua=not args.browser_ua)
    next_data = extract_next_data(html_text)
    raw_msgs, meta = extract_messages(next_data)
    messages = [m for m in (parse_message(x) for x in raw_msgs) if m]

    if args.list:
        for i, m in enumerate(messages, 1):
            preview = (m["text"] or (m["media"][0].get("author", "") if m["media"] else ""))[:40]
            print(f"{i:>3}. [{m['speaker']}] {preview}")
        return

    conversation = {"meta": meta, "messages": messages}
    out = render_json(conversation) if args.format == "json" else render_markdown(conversation)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[完成] 已写入 {args.output}（{len(messages)} 条消息）", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
