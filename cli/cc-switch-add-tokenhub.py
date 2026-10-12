#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 TokenHub 供应商一键写入 cc-switch 数据库（Lingrui98/cc-switch 桌面版）。

原理：cc-switch 把所有供应商存在 ~/.cc-switch/cc-switch.db 的 providers 表，
切换时把选中供应商的 settings_config 覆盖写进 ~/.claude/settings.json。
本脚本按现有中转供应商（如 内部 AI 平台）的真实字段格式，把 TokenHub 各档位插入，
从而让 cc-switch 里出现「TokenHub·网关全25款 / Hy3 / Kimi / ...」等一键档。

安全：
  - 执行前自动备份 cc-switch.db（带时间戳），可回滚。
  - 真 TokenHub Key 不进数据库（网关 auth_token 用占位 local-gateway；真 Key 只在起网关时当环境变量）。
  - 幂等：id 已存在则跳过，不重复插入。
  - 默认 dry-run（只打印不写），加 --really 才真正写入。

用法：
  python3 cc-switch-add-tokenhub.py            # 预览将要写入的内容
  python3 cc-switch-add-tokenhub.py --really   # 真正写入数据库

前置：
  1) 先起本地网关（否则切过去 Claude Code 连不上）：
     TOKENHUB_API_KEY=你的Key GATEWAY_PORT=4000 python3 tools/tokenhub_minigate.py &
  2) 写入后重启 cc-switch 桌面应用，让它重新读取数据库，GUI 里即出现 TokenHub 档位。
"""
import argparse
import json
import os
import shutil
import sqlite3
import time

HOME = os.path.expanduser("~")
DB_PATH = os.path.join(HOME, ".cc-switch", "cc-switch.db")
SETTINGS_PATH = os.path.join(HOME, ".claude", "settings.json")
PROFILES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc-switch-tokenhub-profiles.json")


def build_env(profile, gateway):
    slots = profile["slots"]
    env = {
        "ANTHROPIC_BASE_URL": gateway["base_url"],
        "ANTHROPIC_AUTH_TOKEN": gateway["auth_token_placeholder"],
        "ANTHROPIC_API_KEY": "",  # 必须清空，防止 Claude Code 回退到 Anthropic 官方
        "ANTHROPIC_MODEL": profile["default_model"],
        "ANTHROPIC_DEFAULT_SONNET_MODEL": slots["sonnet"],
        "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": slots["sonnet"],
        "ANTHROPIC_DEFAULT_OPUS_MODEL": slots["opus"],
        "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME": slots["opus"],
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": slots["haiku"],
        "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME": slots["haiku"],
        "ANTHROPIC_DEFAULT_FABLE_MODEL": slots["fable"],
        "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME": slots["fable"],
        "ANTHROPIC_REASONING_MODEL": profile["default_model"],
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_SUBAGENT_MODEL": slots["haiku"],
    }
    if profile.get("gateway_discovery"):
        env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    return env


def main():
    parser = argparse.ArgumentParser(description="把 TokenHub 供应商写入 cc-switch 数据库")
    parser.add_argument("--really", action="store_true", help="真正写入数据库（默认仅预览）")
    args = parser.parse_args()

    for p in (DB_PATH, SETTINGS_PATH, PROFILES_PATH):
        if not os.path.exists(p):
            print(f"❌ 找不到必要文件: {p}")
            return

    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles_doc = json.load(f)
    gateway = profiles_doc["gateway"]
    profiles = profiles_doc["profiles"]

    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        settings = json.load(f)
    # 复制当前 settings 的非 env 顶层配置（hooks/statusLine/permissions 等），切过去不丢
    base_config = {k: v for k, v in settings.items() if k != "env"}

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # 当前最大 sort_index，新插入往后排
    max_sort = cur.execute("SELECT MAX(sort_index) FROM providers").fetchone()[0]
    max_sort = max_sort or 0

    rows = []
    for pf in profiles:
        pid = "tokenhub-" + pf["id_suffix"]
        settings_config = {**base_config, "env": build_env(pf, gateway)}
        meta = json.dumps({"commonConfigEnabled": True, "endpointAutoSelect": True, "apiFormat": "anthropic"}, ensure_ascii=False)
        rows.append((pid, "claude", pf["name"], json.dumps(settings_config, ensure_ascii=False),
                     "https://console.cloud.tencent.com/tokenhub", "custom",
                     int(time.time() * 1000), max_sort + 1, meta))
        max_sort += 1

    if not args.really:
        print("【DRY-RUN 预览】以下供应商将被插入 providers 表（加 --really 才真正写入）：\n")
        for r in rows:
            print(f"  id={r[0]}  name={r[2]}  app_type={r[1]}")
            cfg = json.loads(r[3])
            print("    env.ANTHROPIC_BASE_URL =", cfg["env"]["ANTHROPIC_BASE_URL"])
            print("    env.ANTHROPIC_MODEL    =", cfg["env"]["ANTHROPIC_MODEL"])
            print("    env.ANTHROPIC_API_KEY  =", repr(cfg["env"]["ANTHROPIC_API_KEY"]))
            if "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY" in cfg["env"]:
                print("    + GATEWAY_MODEL_DISCOVERY 已开启（/model 列出 25 款）")
            print()
        print("未做任何修改。")
        con.close()
        return

    # 真正写入：先备份
    backup_dir = os.path.join(HOME, ".cc-switch", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"cc-switch.db.bak-{int(time.time())}")
    shutil.copy2(DB_PATH, backup_path)
    print(f"✅ 已备份数据库到: {backup_path}")

    inserted, skipped = 0, 0
    for r in rows:
        pid = r[0]
        exists = cur.execute("SELECT 1 FROM providers WHERE id=?", (pid,)).fetchone()
        if exists:
            print(f"  ↺ 跳过已存在: {pid}")
            skipped += 1
            continue
        cur.execute(
            "INSERT INTO providers (id, app_type, name, settings_config, website_url, category, "
            "created_at, sort_index, meta, is_current, in_failover_queue, cost_multiplier) "
            "VALUES (?,?,?,?,?,?,?,?,?,0,0,'1.0')",
            r,
        )
        print(f"  ➕ 已插入: {pid}  ({r[2]})")
        inserted += 1
    con.commit()
    con.close()
    print(f"\n完成：新增 {inserted} 个，跳过 {skipped} 个（已存在）。")
    print("下一步：重启 cc-switch 桌面应用 → GUI 里出现 TokenHub 档位 → 点选一键切换。")
    print("注意：切换前请确保本地网关已在运行（见脚本顶部前置说明）。")


if __name__ == "__main__":
    main()
