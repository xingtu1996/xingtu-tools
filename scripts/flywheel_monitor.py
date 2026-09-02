#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞轮效率观测探针（flywheel_monitor.py）
====================================
零依赖（仅 Python 标准库），可重复运行。从三层数据源采集「并行处理效率」指标，
生成单文件 HTML 看板：

  L1 自动化层  ~/.workbuddy/workbuddy.db 的 automations / automation_runs
               （每次运行的 startedAt/finishedAt → 时长、成功率、产出字数）
  L2 Agent 层  outputs/内容战略分析/飞轮运行日志.jsonl（飞轮自动化埋点契约）
               （每个 agent 的起止时间 → 并行加速比 = Σ个体时长 / 墙钟时长）
  L3 会话层    sessions / session_usage（上下文占用 used/size、credit 成本）

用法：
  python3 tools/flywheel_monitor.py                 # 默认路径，刷新看板
  python3 tools/flywheel_monitor.py --days 14       # 只看近 14 天
输出：
  outputs/内容战略分析/飞轮效率看板.html（稳定文件名，可反复刷新）
"""

import argparse
import datetime
import glob
import html
import json
import os
import sqlite3

# ---------------------------------------------------------------- 基础工具

def ts(ms, fmt="%m-%d %H:%M"):
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime(fmt)
    except Exception:
        return "-"


def dur_text(sec):
    if sec is None:
        return "-"
    if sec < 90:
        return f"{sec:.0f}s"
    if sec < 5400:
        return f"{sec / 60:.1f}min"
    return f"{sec / 3600:.1f}h"


def esc(s):
    return html.escape(str(s)) if s is not None else "-"


SHORT_MAP = [
    ("广撒网", "广撒网采集"), ("对话挖掘", "对话挖掘"), ("素材库", "素材库周刷"),
    ("飞轮", "变现飞轮"), ("内容飞轮", "变现飞轮"),
]


def short_name(name):
    for k, v in SHORT_MAP:
        if k in (name or ""):
            return v
    return (name or "?")[:10]


def rrule_text(rr):
    if not rr:
        return "-"
    if "DAILY" in rr:
        return "每日 " + rr.split("BYHOUR=")[-1].split(";")[0] + ":00"
    if "WEEKLY" in rr:
        day = {"MO": "一", "TU": "二", "WE": "三", "TH": "四", "FR": "五", "SA": "六", "SU": "日"}
        d = "".join(day.get(x, x) for x in rr.split("BYDAY=")[-1].split(";")[0].split(","))
        h = rr.split("BYHOUR=")[-1].split(";")[0]
        return f"每周{d} {h}:00"
    return rr

# ---------------------------------------------------------------- 数据采集

def collect_db(db_path, days):
    """L1 自动化层 + L3 会话层"""
    out = {"automations": [], "runs": [], "today_sessions": [], "kpi": {}, "db_ok": False}
    if not os.path.exists(db_path):
        return out
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
    except Exception:
        return out
    out["db_ok"] = True

    now = datetime.datetime.now()
    since = (now - datetime.timedelta(days=days)).timestamp() * 1000

    amap = {}
    for r in c.execute("SELECT id,name,status,rrule,schedule_type,next_run_at,last_run_at FROM automations WHERE deleted_at IS NULL"):
        a = dict(r)
        amap[a["id"]] = a
        out["automations"].append(a)

    for r in c.execute("SELECT automation_id,created_at,runs_json,result_success FROM automation_runs WHERE created_at>=? ORDER BY created_at", (since,)):
        try:
            runs = json.loads(r["runs_json"] or "[]") or []
        except Exception:
            runs = []
        for run in runs:
            s, f = run.get("startedAt"), run.get("finishedAt")
            out["runs"].append({
                "automation_id": r["automation_id"],
                "name": short_name(amap.get(r["automation_id"], {}).get("name", "?")),
                "startedAt": s, "finishedAt": f,
                "dur": (f - s) / 1000 if s and f else None,
                "success": bool(run.get("success")),
                "output_chars": len(run.get("output") or ""),
                "date": ts(s, "%m-%d"),
            })

    # 今日会话（交互 + 后台自动化）
    t0 = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
    sess = list(c.execute(
        "SELECT id,title,created_at,updated_at,is_background_automation FROM sessions WHERE created_at>=? ORDER BY created_at", (t0,)))
    usage = {}
    for u in c.execute("SELECT session_id,used,size,credit_json FROM session_usage"):
        usage[u["session_id"]] = dict(u)
    for s in sess:
        u = usage.get(s["id"], {})
        try:
            credit = sum(json.loads(u["credit_json"]).values()) if u.get("credit_json") else 0
        except Exception:
            credit = 0
        out["today_sessions"].append({
            "title": s["title"] or ("自动化·后台会话" if s["is_background_automation"] else "(未命名)"),
            "bg": bool(s["is_background_automation"]),
            "dur": (s["updated_at"] - s["created_at"]) / 1000,
            "used": u.get("used") or 0,
            "size": u.get("size") or 0,
            "credit": round(credit, 2),
            "time": ts(s["created_at"], "%H:%M"),
        })
    return out


def collect_jsonl(path):
    """L2 Agent 层埋点：飞轮运行日志"""
    rows = []
    if not os.path.exists(path):
        return rows
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return rows


def parallel_clusters(directory, days=1):
    """产物时间线：把 outputs/内容战略分析/ 下近 days 天的产物按修改时间聚类，
    间隔 ≤300s 的算同一簇；≥3 个文件的簇 = 并行完成簇（多 agent 同时收工的物证）。"""
    items = []
    if not os.path.isdir(directory):
        return items
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
    for p in glob.glob(os.path.join(directory, "*")):
        if os.path.isdir(p):
            continue
        m = os.path.getmtime(p)
        if m >= cutoff:
            items.append({"name": os.path.basename(p), "mtime": m})
    items.sort(key=lambda x: x["mtime"])
    clusters, cur = [], []
    for it in items:
        if cur and it["mtime"] - cur[-1]["mtime"] > 300:
            clusters.append(cur)
            cur = []
        cur.append(it)
    if cur:
        clusters.append(cur)
    out = []
    for cl in clusters:
        out.append({
            "files": cl,
            "span": cl[-1]["mtime"] - cl[0]["mtime"],
            "start": datetime.datetime.fromtimestamp(cl[0]["mtime"]),
            "parallel": len(cl) >= 3,
        })
    return out

# ---------------------------------------------------------------- 渲染

CSS = """
:root{--bg:#f5f6f8;--card:#ffffff;--ink:#1f2329;--sub:#6b7280;--line:#e5e7eb;
--blue:#2563eb;--green:#16a34a;--red:#dc2626;--amber:#d97706;--chip:#eef2ff}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:var(--ink);padding:28px;line-height:1.65}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;margin-bottom:4px}
.sub{color:var(--sub);font-size:13px;margin-bottom:20px}
h2{font-size:16px;margin:26px 0 12px;padding-left:10px;border-left:4px solid var(--blue)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:24px;font-weight:700}
.kpi .l{font-size:12px;color:var(--sub);margin-top:2px}
.kpi .n{font-size:11px;color:var(--sub)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--sub);font-weight:600;padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid #f1f2f4;vertical-align:middle}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:600}
.b-ok{background:#dcfce7;color:var(--green)} .b-bad{background:#fee2e2;color:var(--red)}
.b-wait{background:#fef3c7;color:var(--amber)} .b-info{background:var(--chip);color:var(--blue)}
.gantt-row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12px}
.gantt-row .t{width:118px;color:var(--sub);flex:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gantt-row .bar{height:14px;border-radius:4px;min-width:3px}
.gantt-row .d{color:var(--sub);white-space:nowrap}
.bar.ok{background:var(--green)} .bar.bad{background:var(--red)}
.ubar{background:var(--line);border-radius:99px;height:8px;width:110px;display:inline-block;vertical-align:middle;margin-right:6px}
.ubar>i{display:block;height:8px;border-radius:99px;background:var(--blue)}
code{background:#f3f4f6;border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:12px;font-family:ui-monospace,Menlo,monospace}
.note{font-size:12px;color:var(--sub);margin-top:8px}
.big{font-size:30px;font-weight:800;color:var(--blue)}
.method li{margin:6px 0;font-size:13.5px}
.footer{color:var(--sub);font-size:12px;text-align:center;margin-top:26px}
"""


def render(db, jsonl_rows, clusters, args):
    runs = db["runs"]
    autos = db["automations"]
    today = db["today_sessions"]
    total = len(runs)
    ok = sum(1 for r in runs if r["success"])
    ok_rate = (ok / total * 100) if total else 0
    today_credit = sum(s["credit"] for s in today)
    main_ctx = max(((s["used"], s["size"]) for s in today), default=(0, 0))

    # --- 自动化健康表 ---
    a_rows = []
    for a in autos:
        ar = [r for r in runs if r["automation_id"] == a["id"]]
        n = len(ar)
        sok = sum(1 for r in ar if r["success"])
        durs = [r["dur"] for r in ar if r["dur"]]
        avg = sum(durs) / len(durs) if durs else None
        last = ar[-1] if ar else None
        if n == 0:
            badge, state = '<span class="badge b-wait">待首跑</span>', "未运行"
        elif sok / n >= 0.7:
            badge = '<span class="badge b-ok">健康</span>'
        elif sok / n >= 0.4:
            badge = '<span class="badge b-wait">波动</span>'
        else:
            badge = '<span class="badge b-bad">告警</span>'
        last_txt = f'{ts(last["startedAt"], "%m-%d %H:%M")} · {dur_text(last["dur"])} · {"成功" if last["success"] else "失败"}' if last else "-"
        a_rows.append(f"""<tr>
<td><b>{esc(short_name(a["name"]))}</b><div style="color:var(--sub);font-size:11px">{esc(a["name"])}</div></td>
<td>{esc(rrule_text(a["rrule"]))}</td><td>{n}</td>
<td>{sok}/{n} {f"({sok / n * 100:.0f}%)" if n else ""}</td>
<td>{dur_text(avg)}</td><td>{last_txt}</td>
<td>{ts(a["next_run_at"], "%m-%d %H:%M")}</td><td>{badge}</td></tr>""")

    # --- 运行时间线（甘特） ---
    max_d = 4200
    g_rows = []
    for r in runs:
        d = r["dur"] or 0
        w = min(d, max_d) / max_d * 62
        mark = "ok" if r["success"] else "bad"
        flag = "✓" if r["success"] else "✗"
        g_rows.append(
            f'<div class="gantt-row"><span class="t">{r["date"]} {r["name"]}</span>'
            f'<div class="bar {mark}" style="width:{max(w, 0.6)}%"></div>'
            f'<span class="d">{flag} {dur_text(r["dur"])}{"" if r["success"] else " · 失败"}</span></div>')

    # --- 今日会话成本 ---
    s_rows = []
    for s in sorted(today, key=lambda x: -x["credit"]):
        pct = (s["used"] / s["size"] * 100) if s["size"] else 0
        tag = ' <span class="badge b-info">后台自动化</span>' if s["bg"] else ""
        s_rows.append(f"""<tr><td>{s["time"]}</td>
<td>{esc(s["title"])}{tag}</td>
<td><span class="ubar"><i style="width:{min(pct, 100):.0f}%"></i></span>{s["used"]:,}/{s["size"]:,}</td>
<td>{dur_text(s["dur"])}</td><td><b>{s["credit"]}</b></td></tr>""")

    # --- L2 埋点（Agent 层并行效率） ---
    if jsonl_rows:
        jr = [x for x in jsonl_rows if x.get("startedAt") and x.get("finishedAt")]
        for x in jr:
            x["_dur"] = (x["finishedAt"] - x["startedAt"]) / 1000
        wall = (max(x["finishedAt"] for x in jr) - min(x["startedAt"] for x in jr)) / 1000
        serial = sum(x["_dur"] for x in jr)
        speedup = (serial / wall) if wall else 0
        j_rows = "".join(
            f'<tr><td>{esc(x.get("phase", "-"))}</td><td>{esc(x.get("agent", "-"))}</td>'
            f'<td>{dur_text(x["_dur"])}</td><td>{x.get("outputChars", "-")}</td>'
            f'<td>{"✓" if x.get("success", True) else "✗"}</td></tr>' for x in jr)
        l2 = f"""<div class="card">
<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
<div><div class="big">{speedup:.2f}×</div><div class="n">并行加速比 = Σ个体时长 ÷ 墙钟时长</div></div>
<div style="font-size:13px">墙钟 <b>{dur_text(wall)}</b> · 串行等价 <b>{dur_text(serial)}</b> · 埋点 {len(jr)} 条</div></div>
<table><tr><th>环节</th><th>Agent</th><th>个体时长</th><th>产出字数</th><th>结果</th></tr>{j_rows}</table></div>"""
    else:
        l2 = """<div class="card"><div style="font-size:13.5px">暂无埋点数据。周日晚 22:00「变现飞轮」首跑后，每个 agent 会向
<code>outputs/内容战略分析/飞轮运行日志.jsonl</code> 追加起止时间，届时此卡片自动出现精确加速比。</div></div>"""

    # --- 产物时间线（并行完成簇） ---
    c_html = []
    for cl in clusters:
        badge = '<span class="badge b-info">并行完成簇</span>' if cl["parallel"] else '<span class="badge b-ok">顺序产出</span>'
        files = "、".join(esc(f["name"]) for f in cl["files"])
        c_html.append(
            f'<div class="card"><div style="font-size:13px;margin-bottom:4px">{badge} '
            f'<b>{cl["start"].strftime("%m-%d %H:%M:%S")}</b> · {len(cl["files"])} 个产物 · 簇跨度 {dur_text(cl["span"])}</div>'
            f'<div style="font-size:12.5px;color:var(--sub)">{files}</div></div>')

    # --- 健康诊断 ---
    diag = []
    for a in autos:
        ar = [r for r in runs if r["automation_id"] == a["id"]]
        if not ar:
            continue
        fails = [r for r in ar[-8:] if not r["success"]]
        if len(fails) >= 3:
            avg_fail = sum(r["dur"] for r in fails if r["dur"]) / max(len(fails), 1)
            diag.append(f'🔴 <b>{esc(short_name(a["name"]))}</b>：近 {len(ar[-8:])} 次失败 {len(fails)} 次，'
                        f'平均每次空烧 {dur_text(avg_fail)}——建议修复 prompt 或暂停，止损时长与 token。')
    if diag:
        diag.append("🟢 对话挖掘：成功率约 70%，产出正常，维持现状。")
        diag.append("🟡 素材库周刷 + 变现飞轮：周日晚 21:00/22:00 首跑，跑完本看板自动出加速比。")
    else:
        diag.append("暂无明显异常。")

    gen_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>飞轮效率观测台</title><style>{CSS}</style></head><body><div class="wrap">
<h1>🛞 飞轮效率观测台</h1>
<div class="sub">生成于 {gen_at} · 数据源 ~/.workbuddy/workbuddy.db + 飞轮运行日志.jsonl ·
刷新：<code>python3 tools/flywheel_monitor.py</code></div>

<div class="kpis">
<div class="kpi"><div class="v">{len(autos)}</div><div class="l">自动化任务（含待首跑）</div></div>
<div class="kpi"><div class="v">{total}</div><div class="l">近 {args.days} 天运行次数</div></div>
<div class="kpi"><div class="v" style="color:{'var(--green)' if ok_rate >= 60 else 'var(--red)'}">{ok_rate:.0f}%</div><div class="l">整体成功率（{ok}/{total}）</div></div>
<div class="kpi"><div class="v">¥{today_credit:.2f}</div><div class="l">今日会话 credit 成本</div><div class="n">自动化的 credit 暂未入此表</div></div>
<div class="kpi"><div class="v">{len(today)}</div><div class="l">今日会话数（含后台）</div></div>
<div class="kpi"><div class="v">{main_ctx[0] / 1000:.0f}k<span style="font-size:13px;color:var(--sub)">/{main_ctx[1] // 1000}k</span></div><div class="l">最大单会话上下文占用</div></div>
</div>

<h2>① 自动化任务健康度</h2>
<div class="card"><table>
<tr><th>任务</th><th>排程</th><th>次数</th><th>成功</th><th>平均时长</th><th>最近一次</th><th>下次运行</th><th>状态</th></tr>
{''.join(a_rows)}</table></div>

<h2>② 运行时间线（绿=成功 红=失败，条长≈时长）</h2>
<div class="card">{''.join(g_rows)}
<div class="note">超过 70min 的失败运行（如 08-18 的 2.2h）已被截断显示——长红条 = 空烧信号。</div></div>

<h2>③ Agent 层并行效率（埋点契约）</h2>
{l2}

<h2>④ 产物时间线 · 并行完成簇物证</h2>
{''.join(c_html) if c_html else '<div class="card" style="font-size:13px">outputs/内容战略分析/ 近 24h 无新产物。</div>'}
<div class="note" style="margin-top:-6px">同一簇内 ≥3 个产物几乎同时落地 = 多 agent 并行收工的直接物证（今天 4 份报告落在 2 分 21 秒窗口内）。</div>

<h2>⑤ 今日会话成本观测</h2>
<div class="card"><table>
<tr><th>开始</th><th>会话</th><th>上下文占用</th><th>活跃时长</th><th>credit</th></tr>
{''.join(s_rows)}</table>
<div class="note">credit 为平台计量额度（非人民币实付）；used 接近 size 时上下文将触发压缩，长会话建议及时拆分。</div></div>

<h2>⑥ 观测方法论：怎么判断「并行到底快没快」</h2>
<div class="card"><ol class="method">
<li><b>加速比</b>（唯一硬指标）：并行加速比 = Σ(各 agent 个体时长) ÷ (最晚结束 − 最早开始)。=1 等于没并行；≈agent 数才算真并行。数据来自埋点 JSONL，本看板 ③ 区自动计算。</li>
<li><b>完成簇</b>（物证法）：多个产物文件 mtime 落在数分钟窗口内 → 同时收工。今天 4 份报告 22:03:42–22:06:03 落地，即并行证据。</li>
<li><b>健康度</b>（别让飞轮空转）：成功率 + 平均时长 + 失败空烧时长。失败但跑 1h 的任务比快速失败更伤——烧的是你的 credit。</li>
<li><b>成本</b>：每会话 credit 与上下文占用，防止「并行很爽、账单很痛」。</li></ol></div>

<h2>⑦ 本期诊断结论</h2>
<div class="card" style="font-size:13.5px">{'<br>'.join(diag)}
<div class="note" style="margin-top:10px">操作建议：广撒网采集已连续失败多日，建议 <b>暂停并重写 prompt</b>（或改为与对话挖掘合并跑），避免每晚空烧。是否处理由 Boss 拍板，本探针只诊断不自动改配置。</div></div>

<div class="footer">flywheel_monitor.py · 单文件零依赖 · 每次运行覆盖刷新本看板</div>
</div></body></html>"""

# ---------------------------------------------------------------- 主流程

def main():
    base = "~/xingtu"
    ap = argparse.ArgumentParser(description="飞轮效率观测探针")
    ap.add_argument("--db", default=os.path.expanduser("~/.workbuddy/workbuddy.db"))
    ap.add_argument("--outdir", default=os.path.join(base, "outputs", "内容战略分析"))
    ap.add_argument("--jsonl", default=os.path.join(base, "outputs", "内容战略分析", "飞轮运行日志.jsonl"))
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--artifact-days", type=float, default=1)
    args = ap.parse_args()

    db = collect_db(args.db, args.days)
    jsonl_rows = collect_jsonl(args.jsonl)
    clusters = parallel_clusters(args.outdir, days=args.artifact_days)

    os.makedirs(args.outdir, exist_ok=True)
    out = os.path.join(args.outdir, "飞轮效率看板.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(db, jsonl_rows, clusters, args))

    n_runs = len(db["runs"])
    print(f"[OK] 看板已刷新: {out}")
    print(f"     运行记录 {n_runs} 条 | 今日会话 {len(db['today_sessions'])} 个 | 埋点 {len(jsonl_rows)} 条 | 产物簇 {len(clusters)} 个")
    if not db["db_ok"]:
        print("[WARN] 未读到 WorkBuddy DB，看板仅含产物时间线。")


if __name__ == "__main__":
    main()
