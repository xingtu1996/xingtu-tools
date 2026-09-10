#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽样确认各 AI 工具会话数据的真实格式。"""
import os, json, sqlite3, glob

HOME = os.path.expanduser("~")
SEP = "=" * 60


def head_text(p, n=1400):
    try:
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(n)
    except Exception as e:
        return f"<read err {e}>"


def sqlite_keys(p):
    try:
        con = sqlite3.connect(p)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        info = {}
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM '{t}'")
                cnt = cur.fetchone()[0]
                info[t] = cnt
            except Exception:
                pass
        # ItemTable key 前缀分布
        keys = []
        if 'ItemTable' in tables:
            try:
                cur.execute("SELECT key FROM ItemTable")
                keys = [r[0] for r in cur.fetchall()]
            except Exception:
                pass
        con.close()
        return tables, info, keys
    except Exception as e:
        return None, None, [f"<err {e}>"]


print(SEP); print("1) KIRO (Application Support/Kiro/User)")
kiro = os.path.join(HOME, "Library/Application Support", "Kiro", "User")
if os.path.isdir(kiro):
    for top in sorted(os.listdir(kiro))[:12]:
        print("   ", top)
    ws = os.path.join(kiro, "workspaceStorage")
    if os.path.isdir(ws):
        dbs = glob.glob(os.path.join(ws, "*", "state.vscdb"))
        print(f"   workspaceStorage state.vscdb 数量: {len(dbs)}")
        if dbs:
            tables, info, keys = sqlite_keys(dbs[0])
            print("   首个 vscdb 表:", info)
            from collections import Counter
            pref = Counter(k.split('.')[0] for k in keys)
            print("   键前缀分布(前12):", dict(pref.most_common(12)))
    gs = os.path.join(kiro, "globalStorage")
    if os.path.isdir(gs):
        for root, d, f in os.walk(gs):
            if len(f) > 0:
                rel = os.path.relpath(root, gs)
                print(f"   globalStorage/{rel}: {f[:6]}")
            if root.count(os.sep) - gs.count(os.sep) > 2:
                d[:] = []
else:
    print("   不存在")

print(SEP); print("2) Claude-3p local-agent-mode-sessions / claude-code-sessions")
c3 = os.path.join(HOME, "Library/Application Support", "Claude-3p")
for sub in ["local-agent-mode-sessions", "claude-code-sessions"]:
    d = os.path.join(c3, sub)
    if os.path.isdir(d):
        fs = sorted(os.listdir(d))[:5]
        print(f"   {sub}: {fs}")
        for fn in fs[:1]:
            fp = os.path.join(d, fn)
            print("   样本:", fn, "->", head_text(fp, 800).replace("\n", " ")[:400])

print(SEP); print("3) .codex/sessions")
codex = os.path.join(HOME, ".codex", "sessions")
if os.path.isdir(codex):
    fs = sorted(os.listdir(codex))[:3]
    for fn in fs[:1]:
        fp = os.path.join(codex, fn)
        print("   样本:", fn)
        print(head_text(fp, 1000))

print(SEP); print("4) .kimi/sessions")
kimi = os.path.join(HOME, ".kimi", "sessions")
if os.path.isdir(kimi):
    fs = sorted(os.listdir(kimi))[:3]
    for fn in fs[:1]:
        fp = os.path.join(kimi, fn)
        print("   样本:", fn)
        print(head_text(fp, 1000))

print(SEP); print("5) .copilot/session-state (sqlite)")
cop = os.path.join(HOME, ".copilot", "session-state")
if os.path.isdir(cop):
    dbs = glob.glob(os.path.join(cop, "*.sqlite")) + glob.glob(os.path.join(cop, "*.db"))
    print("   sqlite 文件:", [os.path.basename(x) for x in dbs][:5])
    if dbs:
        tables, info, keys = sqlite_keys(dbs[0])
        print("   表:", info)
        if isinstance(keys, list) and keys and not str(keys[0]).startswith("<"):
            print("   样本 keys:", keys[:10])

print(SEP); print("6) opencode / mimocode prompt-history.jsonl")
for name, p in [("opencode", os.path.join(HOME, ".local", "state", "opencode", "prompt-history.jsonl")),
                ("mimocode", os.path.join(HOME, ".local", "state", "mimocode", "prompt-history.jsonl"))]:
    print(f"   --- {name} ---")
    if os.path.exists(p):
        print(head_text(p, 1200))
    else:
        print("   不存在")
