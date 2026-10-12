#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cc-switch-sync-profiles.py  v2
基于当前真实 ~/.claude/settings.json（保留全部 hooks / statusLine / theme），
生成 25 个「单模型档」+ 1 个「网关默认档」+ 1 个「网关全25款」聚合档，幂等写入 cc-switch 数据库。

关键发现（2026-08-13 实测）：
  - Claude Code v2.1.220 对非 Anthropic 模型名有内置校验，报错 "may not exist"。
  - modelOverrides / CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT 在当前版本均无效。
  - 正解：ANTHROPIC_CUSTOM_MODEL_OPTION（Ollama 本地模型也靠它接进 CC）。
  - 模型名需带 [1M] 窗口标记后缀，否则 CC 仍拒绝。
  - CC 登录检查只看 auth 凭证格式/长度（sk- 前缀 + 约 49 字符），不验证有效性；
    所以 auth 用固定长占位串（网关不校验 auth，真鉴权走 TOKENHUB_API_KEY 环境变量）。

不变量（安全）：
  - TokenHub 的 Key 只在 OpenAI 端点通（Anthropic 端点 401），所以 Claude Code 必须走
    本地网关 tokenhub_minigate.py（暴露 Anthropic 协议于 localhost:4000）。
  - db / cc-switch 里绝不落盘真实 TokenHub Key：auth 是固定占位串，真 Key 仅在起网关时
    以环境变量 TOKENHUB_API_KEY 传入。

用法：
  python3 cc-switch-sync-profiles.py            # dry-run 预览
  python3 cc-switch-sync-profiles.py --really   # 写入（先自动备份 db）
"""
import os, sys, json, sqlite3, shutil, time, argparse

DB = os.path.expanduser("~/.cc-switch/cc-switch.db")
SETTINGS = os.path.expanduser("~/.claude/settings.json")
BACKUP_DIR = os.path.expanduser("~/.cc-switch/backups")
GATEWAY = "http://localhost:4000"
# 固定长占位 auth：sk- 前缀 + 46 hex，约 49 字符，过 CC 登录格式检查；网关不校验它。
AUTH_PLACEHOLDER = "sk-REPLACE_WITH_REAL_KEY_via_env_0000000000000000000000"

# 25 款模型（与 tokenhub_minigate.py 对齐）
MODELS = [
    "hy3", "kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "minimax-m3", "minimax-m2.7",
    "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-pro-202606", "deepseek-v4-flash-202605",
    "hy-mt2-pro", "hy-mt2-lite", "hy-mt2-plus", "hy-role", "hy-role-latest",
    "glm-5", "glm-5.1", "glm-5.2", "glm-5-turbo", "glm-5v-turbo",
    "kimi-k2.6", "kimi-k2.5", "mimo-v2.5-pro",
    "qwen3.5-flash", "qwen3.5-plus",
]

DISPLAY = {
    "hy3": "混元3", "kimi-k3": "Kimi K3", "kimi-k2.7-code": "Kimi K2.7 Code",
    "kimi-k2.7-code-highspeed": "Kimi K2.7 Code 高速", "minimax-m3": "MiniMax M3",
    "minimax-m2.7": "MiniMax M2.7", "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek-v4-flash": "DeepSeek V4 Flash", "deepseek-v4-pro-202606": "DeepSeek V4 Pro(原厂)",
    "deepseek-v4-flash-202605": "DeepSeek V4 Flash(原厂)", "hy-mt2-pro": "混元翻译 Pro",
    "hy-mt2-lite": "混元翻译 Lite", "hy-mt2-plus": "混元翻译 Plus", "hy-role": "混元角色",
    "hy-role-latest": "混元角色最新", "glm-5": "GLM-5", "glm-5.1": "GLM-5.1",
    "glm-5.2": "GLM-5.2", "glm-5-turbo": "GLM-5 Turbo", "glm-5v-turbo": "GLM-5V Turbo",
    "kimi-k2.6": "Kimi K2.6", "kimi-k2.5": "Kimi K2.5", "mimo-v2.5-pro": "MiMo V2.5 Pro",
    "qwen3.5-flash": "Qwen3.5 Flash", "qwen3.5-plus": "Qwen3.5 Plus",
}


def build_env(base_env, main_model):
    """保留非 ANTHROPIC_ 变量，重写 ANTHROPIC_* 为网关版 + CUSTOM_MODEL_OPTION。"""
    env = {}
    for k, v in (base_env or {}).items():
        if not k.startswith("ANTHROPIC_"):
            env[k] = v
    mm = main_model + "[1m]"
    env["ANTHROPIC_BASE_URL"] = GATEWAY
    env["ANTHROPIC_AUTH_TOKEN"] = AUTH_PLACEHOLDER  # 占位，网关不校验；真鉴权走 TOKENHUB_API_KEY
    env["ANTHROPIC_API_KEY"] = ""
    env["ANTHROPIC_MODEL"] = mm
    for role in ("SONNET", "OPUS", "HAIKU", "FABLE"):
        env[f"ANTHROPIC_DEFAULT_{role}_MODEL"] = mm
    env["ANTHROPIC_REASONING_MODEL"] = mm
    env["ANTHROPIC_SUBAGENT_MODEL"] = mm
    # 正解：让 CC 跳过对非 Anthropic 模型名的校验（Ollama 本地模型同机制）
    env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = mm
    return env


def build_settings(base, main_model):
    cfg = json.loads(json.dumps(base))  # deepcopy
    cfg["env"] = build_env(base.get("env", {}), main_model)
    cfg["model"] = main_model + "[1m]"
    cfg.pop("modelOverrides", None)  # 当前版本 modelOverrides 对未知模型无效，移除避免混淆
    return cfg


def build_env_all25(base_env):
    """聚合档：一个网关档覆盖全部 25 款（/model 可切换）。"""
    env = {}
    for k, v in (base_env or {}).items():
        if not k.startswith("ANTHROPIC_"):
            env[k] = v
    default = "deepseek-v4-flash[1M]"
    env["ANTHROPIC_BASE_URL"] = GATEWAY
    env["ANTHROPIC_AUTH_TOKEN"] = AUTH_PLACEHOLDER  # 占位，网关不校验；真鉴权走 TOKENHUB_API_KEY
    env["ANTHROPIC_API_KEY"] = ""
    env["ANTHROPIC_MODEL"] = default
    for role in ("SONNET", "OPUS", "HAIKU", "FABLE"):
        env[f"ANTHROPIC_DEFAULT_{role}_MODEL"] = default
        env[f"ANTHROPIC_DEFAULT_{role}_MODEL_NAME"] = default
    env["ANTHROPIC_REASONING_MODEL"] = default
    env["ANTHROPIC_SUBAGENT_MODEL"] = default
    # 正解：多行 CUSTOM_MODEL_OPTION 把全部 25 款都声明为合法自定义模型
    env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = "\n".join(m + "[1m]" for m in MODELS)
    # 网关发现：让 CC 从 localhost:4000 的 /v1/models 拉出全部 25 款（与 CUSTOM 双保险）
    env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    return env


def build_settings_all25(base):
    cfg = json.loads(json.dumps(base))  # deepcopy
    cfg["env"] = build_env_all25(base.get("env", {}))
    cfg["model"] = "deepseek-v4-flash[1M]"
    cfg.pop("modelOverrides", None)
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--really", action="store_true", help="真正写入；否则仅 dry-run 预览")
    args = ap.parse_args()

    if not os.path.exists(SETTINGS):
        print(f"❌ 找不到 {SETTINGS}"); sys.exit(1)
    if not os.path.exists(DB):
        print(f"❌ 找不到 cc-switch 数据库 {DB}"); sys.exit(1)

    with open(SETTINGS, encoding="utf-8") as f:
        base = json.load(f)
    has_hooks = "hooks" in base

    # 档位：1 个网关默认档 + 25 个单模型档 + 1 个「网关全25款」聚合档
    profiles = [("tokenhub-gateway", "TokenHub·网关默认(DeepSeek)", "deepseek-v4-flash")]
    for m in MODELS:
        profiles.append((f"tokenhub-{m}", f"TokenHub·{DISPLAY.get(m, m)}", m))

    print(f"读取真实 settings.json：含 hooks={'是' if has_hooks else '否'}")
    built = []
    for pid, name, main in profiles:
        cfg = build_settings(base, main)
        env = cfg["env"]
        built.append((pid, name, main, cfg))
        print(f"  {name:28} | base={env['ANTHROPIC_BASE_URL']} | model={env['ANTHROPIC_MODEL']} | auth=占位 | custom={env['ANTHROPIC_CUSTOM_MODEL_OPTION']}")
    # 聚合档：一个网关档覆盖全部 25 款（/model 可切换）
    all25_cfg = build_settings_all25(base)
    built.append(("tokenhub-gateway-all25", "TokenHub·网关全25款", "deepseek-v4-flash", all25_cfg))
    a25 = all25_cfg["env"]["ANTHROPIC_CUSTOM_MODEL_OPTION"]
    print(f"  {'TokenHub·网关全25款':30} | base=localhost:4000 | model=deepseek-v4-flash[1M] | auth=占位 | custom={len(a25.splitlines())}款(多行)")
    print(f"\n=== 将生成 {len(built)} 个 TokenHub 档位（含 1 个聚合全25款）===")

    if not args.really:
        print("\n[dry-run] 未写入。确认无误后加 --really 执行。")
        return

    con = sqlite3.connect(DB)
    cur = con.cursor()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    bak = os.path.join(BACKUP_DIR, f"cc-switch.db.bak-{int(time.time())}")
    shutil.copy2(DB, bak)
    print(f"\n✅ db 已备份: {bak}")

    # 清理旧的 tokenhub-* 档，避免残留
    cur.execute("DELETE FROM providers WHERE id LIKE 'tokenhub-%'")
    deleted = cur.rowcount
    print(f"🧹 清除旧 tokenhub 档: {deleted} 条")

    now_ms = int(time.time() * 1000)
    for pid, name, main, cfg in built:
        cfg_json = json.dumps(cfg, ensure_ascii=False)
        meta = json.dumps({"commonConfigEnabled": True, "endpointAutoSelect": True}, ensure_ascii=False)
        try:
            cur.execute(
                "INSERT INTO providers (id, app_type, name, settings_config, website_url, category, created_at, meta, is_current, sort_index) "
                "VALUES (?, 'claude', ?, ?, 'https://console.cloud.tencent.com/tokenhub', 'custom', ?, ?, 0, ?)",
                (pid, name, cfg_json, now_ms, meta, now_ms),
            )
            print(f"  ✅ {name}")
        except sqlite3.Error as e:
            print(f"  ❌ {name}: {e}")
    con.commit()
    con.close()
    print(f"\n✅ 完成。共写入 {len(built)} 个档位。请重启 cc-switch 桌面应用让它重新加载 db。")


if __name__ == "__main__":
    main()
