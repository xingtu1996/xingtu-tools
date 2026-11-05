#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yuanbao_full_extract.py — 元宝会话完整提取器（含 zstd 解压）
====================================================================
从【已解密】的微信 4.x 消息库中，完整提取元宝会话的所有消息：
  ① 文本消息（用户转发说明 / 元宝 AI 回复）
  ② appmsg 分享卡片（视频号/公众号链接，zstd 解压后解析 XML）
  ③ 其他类型（图片/语音等）做占位标记

输出：
  - <out>/yuanbao_all_messages.json   全部消息（结构化）
  - <out>/yuanbao_cards.json          仅分享卡/AI分析卡（高价值）
  - <out>/yuanbao_chat_full.txt       人读版完整对话流
"""
import sqlite3, os, sys, json, re, glob, hashlib
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
try:
    import zstandard
except ImportError:
    zstandard = None

CST = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MSG_TYPES = {1:"text",3:"image",34:"voice",43:"video",47:"sticker",48:"location",
             49:"link",10000:"system",10002:"revoke"}

def _ts_to_dt(ts):
    try: ts=int(ts)
    except: return None
    if ts>1e12: ts=ts/1000
    try: return datetime.fromtimestamp(ts, tz=CST)
    except: return None

def _decompress(data):
    if not data: return ""
    if isinstance(data, str):
        data = data.encode("latin-1")
    if zstandard is None: return ""
    try:
        return zstandard.ZstdDecompressor().decompress(data)
    except Exception:
        return b""

def _parse_appmsg(content):
    """解析 appmsg XML → 卡片字段"""
    if not isinstance(content, bytes):
        content = content.encode("utf-8", errors="replace")
    text = content.decode("utf-8", errors="replace")
    if not text.strip().startswith("<"): return None
    try: root = ET.fromstring(text)
    except ET.ParseError: return None
    appmsg = root.find(".//appmsg")
    if appmsg is None: return None
    def g(tag):
        el = appmsg.find(tag)
        return (el.text or "").strip() if el is not None else ""
    title=g("title"); des=g("des"); url=g("url")
    src=g("sourceDisplayName") or g("sourcedisplayname")
    if not title and not des and not url: return None
    return {"card_type":"share","title":title,"description":des,"url":url,
            "source":src}

def extract(wxid, dbdir):
    tbl = "Msg_" + hashlib.md5(wxid.encode()).hexdigest()
    all_msgs=[]
    dbs = sorted(glob.glob(os.path.join(dbdir,"message_*.db")) + glob.glob(os.path.join(dbdir,"message","message_*.db")))
    dbs = list(dict.fromkeys(dbs))  # 去重（保留顺序）
    dbs = [d for d in dbs if "fts" not in d and "resource" not in d]
    for db in dbs:
        try: con=sqlite3.connect(db)
        except: continue
        tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if tbl not in tables: con.close(); continue
        cols=[r[1] for r in con.execute(f'PRAGMA table_info("{tbl}")')]
        try:
            cur=con.execute(f'SELECT local_id, local_type, create_time, sort_seq, real_sender_id, message_content, compress_content, WCDB_CT_message_content FROM "{tbl}"')
            for lid, ltype, ct, sortseq, sender_rid, msg, comp, ctflag in cur:
                dt=_ts_to_dt(ct)
                content=""
                if ctflag==4:
                    raw=_decompress(comp or msg)
                else:
                    raw=msg if isinstance(msg,bytes) else (msg.encode("utf-8",errors="replace") if msg else b"")
                content=raw.decode("utf-8",errors="replace") if raw else ""
                card=None
                if ltype==1:
                    card={"card_type":"text","title":"","description":content}
                elif ltype==49 or (isinstance(content,str) and content.strip().startswith("<msg>")):
                    card=_parse_appmsg(content.encode("utf-8",errors="replace"))
                elif ltype in MSG_TYPES and ltype in (3,34,43,47,48):
                    card={"card_type":MSG_TYPES[ltype],"title":"","description":"[非文本消息]"}
                rec={"id":lid,"type":ltype,"type_name":MSG_TYPES.get(ltype,f"type_{ltype}"),
                     "time":dt.strftime("%Y-%m-%d %H:%M:%S") if dt else str(ct),
                     "timestamp":ct,"sender_rid":sender_rid,"content":content}
                if card:
                    rec["card"]=card
                all_msgs.append(rec)
        except Exception as e:
            print("err",db,e,file=sys.stderr)
        con.close()
    all_msgs.sort(key=lambda x: x["timestamp"] or 0)
    # 去重（按时间+内容前80）
    seen=set(); out=[]
    for m in all_msgs:
        k=(m["timestamp"], m["content"][:80])
        if k in seen: continue
        seen.add(k); out.append(m)
    return out

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--dbdir", required=True)
    ap.add_argument("--wxid", required=True, help="目标微信账号 id（形如 wxid_xxxxxxxxxxxx）")
    ap.add_argument("--name", default="元宝")
    ap.add_argument("-o","--out", required=True)
    args=ap.parse_args()
    msgs=extract(args.wxid, args.dbdir)
    os.makedirs(args.out, exist_ok=True)
    # 全量
    allp=os.path.join(args.out,"yuanbao_all_messages.json")
    json.dump(msgs,open(allp,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    # 卡片
    cards=[m for m in msgs if m.get("card")]
    cp=os.path.join(args.out,"yuanbao_cards.json")
    json.dump(cards,open(cp,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    # 人读版 txt
    tp=os.path.join(args.out,"yuanbao_chat_full.txt")
    with open(tp,"w",encoding="utf-8") as f:
        f.write(f"# {args.name} 会话完整导出\n总消息 {len(msgs)} 条\n{'='*50}\n\n")
        for m in msgs:
            tag=f"[{m['type_name']}]" if m["type_name"]!="text" else ""
            f.write(f"[{m['time']}]{tag}\n{m['content']}\n\n")
    print(f"总消息: {len(msgs)} | 卡片: {len(cards)}")
    print(f"全量: {allp}\n卡片: {cp}\n文本: {tp}")

if __name__=="__main__":
    main()
