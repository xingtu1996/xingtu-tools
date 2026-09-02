#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
model_suggester.py —— 行途模型智能提示器
==========================================
读 tools/model_assignment.json 的信号词规则，把「任务描述」自动识别成
「推荐模型 + 倍率 + 理由 + 切换动作」。命中多条按打分 + 硬规则消解。

用法：
    python3 model_suggester.py "帮我写一篇公众号深度文"
    python3 model_suggester.py --time 23:00 "周末批量生产 3 篇"
    python3 model_suggester.py --json "看一下这张截图里的封面"
    echo "查一下 XX 的资料" | python3 model_suggester.py      # 交互/管道

硬规则（按优先级）：
    1. 黑名单拦截：任务里点名 kimi-k3 等 → 直接警告并给替代
    2. 图片强制：命中 glm-5v 信号 → 锁 5v（唯一带视觉，其他模型看不了图）
    3. hy3 夜间信号（夜间/批量生产/周末备稿…）→ 直接锁 hy3 夜间版 0.00x
    4. 夜间时段(22:00-07:59) + 推荐是 Pro/Flash → 追加「可切 hy3 白嫖」提示
    5. Auto 判定：命中 auto 信号 ≥ 任一创作场景 → 丢 Auto（错配代价低）
"""
import json
import sys
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "model_assignment.json")

NIGHT_START, NIGHT_END = 22, 8  # 22:00 - 07:59 为夜间


def load_conf():
    with open(CONF, encoding="utf-8") as f:
        return json.load(f)


def hit_score(text, signals):
    return sum(1 for s in signals if s in text)


def is_night(now=None):
    now = now or datetime.now()
    h = now.hour
    return h >= NIGHT_START or h < NIGHT_END


def suggest(text, now=None):
    conf = load_conf()
    warns = []

    # 0) 黑名单拦截
    for bl in conf.get("blacklist", []):
        if bl["模型"].lower() in text.lower():
            warns.append(f"⚠️ 点名了黑名单模型 {bl['模型']}（{bl['倍率']}）：{bl['原因']}。")

    # 1) 图片强制
    visual = next(a for a in conf["assignment"] if "5v" in a["模型"])
    if hit_score(text, visual.get("signals", [])) > 0:
        return build(text, visual, conf, warns, reason="命中读图/截图/封面信号，glm-5v 是唯一带视觉的模型", now=now)

    # 2) hy3 夜间信号
    night_hy3 = next(a for a in conf["assignment"] if "夜间版" in a["模型"])
    if hit_score(text, night_hy3.get("signals", [])) > 0:
        return build(text, night_hy3, conf, warns, reason="命中夜间/批量生产信号，0.00x 白嫖优先", now=now)

    # 3) 普通打分
    scored = [(a, hit_score(text, a.get("signals", []))) for a in conf["assignment"]]
    scored.sort(key=lambda x: -x[1])
    top, top_score = scored[0][0], scored[0][1]

    # 4) Auto 判定：命中 auto 信号且不低于任一创作场景
    auto = conf["auto_mode"]
    auto_score = hit_score(text, auto.get("signals", []))
    if auto_score > 0 and auto_score >= top_score:
        reason = "命中杂活信号（查/读/整理/汇总），错配代价低，丢 Auto 省心"
        return build(text, {"场景": "日常杂活", "模型": "Auto", "倍率": "—", "优先级": "杂活默认", "signals": auto["signals"]},
                     conf, warns, reason=reason, now=now)

    if top_score == 0:
        reason = "没有命中明确信号，按默认锁 V4-Pro（写稿主力，防懒切换）"
        return build(text, conf["default_model"] and next(a for a in conf["assignment"] if a["模型"] == conf["default_model"]),
                     conf, warns, reason=reason, now=now)

    reason = f"命中信号词 {top_score} 个：{' / '.join(s for s in top['signals'] if s in text)}"
    return build(text, top, conf, warns, reason=reason, now=now)


def build(text, chosen, conf, warns, reason, now=None):
    night = is_night(now)
    out = {
        "任务": text.strip(),
        "推荐模型": chosen["模型"],
        "倍率": chosen.get("倍率", "—"),
        "优先级": chosen.get("优先级", "—"),
        "理由": reason,
        "夜间": night,
        "警告": warns,
        "备选": [],
    }
    # 备选：不同模型的次高分配
    for a in conf["assignment"]:
        if a["模型"] != chosen["模型"] and hit_score(text, a.get("signals", [])) > 0:
            out["备选"].append({"模型": a["模型"], "倍率": a["倍率"], "命中": hit_score(text, a.get("signals", []))})
    out["备选"] = sorted(out["备选"], key=lambda x: -x["命中"])[:2]

    # 夜间白嫖提示：推荐是 Pro/Flash 且非夜间场景本身
    if night and chosen["模型"] in ("deepseek-v4-pro", "deepseek-v4-flash"):
        out["夜间提示"] = "🌙 现在是夜间时段，同任务可切 hy3 夜间版（0.00x）白嫖；非批量急稿建议直接切。"
    return out


def render(o, json_mode=False):
    if json_mode:
        print(json.dumps(o, ensure_ascii=False, indent=2))
        return
    L = 56
    print("=" * L)
    print("  🤖 行途模型智能提示")
    print("=" * L)
    print(f"  任务 : {o['任务']}")
    print(f"  推荐 : {o['推荐模型']}  ({o['倍率']})  [{o['优先级']}]")
    print(f"  理由 : {o['理由']}")
    for w in o.get("警告", []):
        print(f"  {w}")
    if o.get("备选"):
        print(f"  备选 : " + " | ".join(f"{b['模型']}({b['倍率']})" for b in o["备选"]))
    if o.get("夜间提示"):
        print(f"  {o['夜间提示']}")
    print("-" * L)
    print("  切换动作: WorkBuddy 模型选择器手动切 | CC 类: /model <名字>")
    print("=" * L)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    json_mode = "--json" in flags
    now = None
    for i, a in enumerate(sys.argv):
        if a == "--time" and i + 1 < len(sys.argv):
            hh, mm = sys.argv[i + 1].split(":")
            now = datetime.now().replace(hour=int(hh), minute=int(mm))

    if args:
        text = " ".join(args)
        render(suggest(text, now), json_mode)
        return
    # 管道或交互
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            render(suggest(text, now), json_mode)
            return
    print("model_suggester —— 丢一句任务描述，我给你模型切换建议")
    print("（Ctrl+D 退出）")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text:
            render(suggest(text, now))


if __name__ == "__main__":
    main()
