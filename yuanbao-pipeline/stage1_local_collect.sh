#!/bin/bash
# stage1_local_collect.sh — 阶段1：本地私有采集（必须在有微信客户端的机器上跑）
# ============================================================
# 为什么必须本地：要读微信本地数据库并解密（db_storage + keys.json），
# 这两个资产是个人私有文件，永不上云、永不入库。
#
# 产出（交接给阶段2 的唯一凭证）：
#   $XT_ROOT/outputs/yuanbao_inventory/yuanbao_cards.json   最新卡片全集
#   $XT_ROOT/outputs/yuanbao_inventory/yuanbao_all_messages.json
# 阶段1 不抓全文、不归档、不推进水位线——那些全部归阶段2（可云端跑）。
#
# 用法：
#   XT_ROOT=/path/to/xingtu bash stage1_local_collect.sh
#   WECHAT_DB_DIR=... WECHAT_KEYS=... WXID=... XT_ROOT=... bash stage1_local_collect.sh
set -e

XT_ROOT="${XT_ROOT:?必须设置 XT_ROOT（工作区根，含 github/xingtu-vault）}"
PY="${PY:-python3}"
WECHAT_DB_DIR="${WECHAT_DB_DIR:-}"
WECHAT_KEYS="${WECHAT_KEYS:-$XT_ROOT/data/wechat_decrypted/keys.json}"
WXID="${WXID:-}"
WXID="${WXID// /}"
if [ -z "$WXID" ]; then
  echo "[!] 未设置 WXID（目标微信账号 id，形如 wxid_xxxxxxxxxxxx）"
  exit 2
fi
DECRYPT_DIR="${DECRYPT_DIR:-$XT_ROOT/data/wechat_decrypted_latest}"

echo "[$(date '+%F %H:%M')] stage1 本地采集开始（root=$XT_ROOT）"

if [ ! -s "$WECHAT_KEYS" ]; then
  echo "[!] 密钥缺失：$WECHAT_KEYS（需在有微信客户端的机器上先提取 key）"
  exit 2
fi
if [ -z "$WECHAT_DB_DIR" ]; then
  echo "[!] 未设置 WECHAT_DB_DIR（微信 db_storage 绝对路径），无法解密"
  exit 2
fi
if [ ! -d "$WECHAT_DB_DIR" ]; then
  echo "[!] 微信库目录不存在：$WECHAT_DB_DIR"
  exit 2
fi

mkdir -p "$DECRYPT_DIR"
# 轮换旧解密副本：B-008 教训（读旧副本 → 连续多天误报「无新增」）
# 安全约束：只轮换本工具自己的解密缓存，不物理删除任何东西
#   ① 目录名必须形如 wechat_decrypted*（防误传别的路径）② 不允许是符号链接
case "$(basename "$DECRYPT_DIR")" in
  wechat_decrypted*) : ;;
  *) echo "[!] DECRYPT_DIR 名称不在白名单（须以 wechat_decrypted 开头）：$DECRYPT_DIR"; exit 2 ;;
esac
if [ -L "$DECRYPT_DIR" ]; then
  echo "[!] DECRYPT_DIR 是符号链接，拒绝轮换：$DECRYPT_DIR"; exit 2
fi
if [ -n "$(ls -A "$DECRYPT_DIR" 2>/dev/null)" ]; then
  PREV="${DECRYPT_DIR%/}.prev.$(date '+%Y%m%d%H%M%S')"
  mkdir -p "$PREV"
  find "$DECRYPT_DIR" -mindepth 1 -maxdepth 1 -exec mv {} "$PREV"/ \;
  # 只保留最近 2 代，更老的移入工作区回收站（.trash，可手工清理，不 rm）
  ls -dt "${DECRYPT_DIR%/}.prev."* 2>/dev/null | tail -n +3 | while read -r old; do
    mkdir -p "$XT_ROOT/.trash"
    mv "$old" "$XT_ROOT/.trash/decrypt_cache_$(basename "$old")"
    echo "[i] 旧解密副本入回收站：$(basename "$old")"
  done
fi

echo "[$(date '+%F %H:%M')] 解密微信库 → $DECRYPT_DIR"
"$PY" - "$XT_ROOT" "$WECHAT_DB_DIR" "$WECHAT_KEYS" "$DECRYPT_DIR" <<'PYCODE'
import sys
root, db_dir, keys, out = sys.argv[1:5]
sys.path.insert(0, root + "/tools/wechatdecryption")
import decrypt
decrypt.decrypt_all(db_dir, keys, out)
PYCODE

echo "[$(date '+%F %H:%M')] 提取元宝卡片 → $XT_ROOT/outputs/yuanbao_inventory"
"$PY" "$XT_ROOT/tools/wechat_chat_analyzer/yuanbao_full_extract.py" \
  --dbdir "$DECRYPT_DIR" --wxid "$WXID" -o "$XT_ROOT/outputs/yuanbao_inventory"

CARDS="$XT_ROOT/outputs/yuanbao_inventory/yuanbao_cards.json"
echo "[$(date '+%F %H:%M')] stage1 完成（cards=$CARDS）"
"$PY" - "$CARDS" <<'PYCODE'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
n = len(d)
latest = max((c.get("share_time") or "" for c in d), default="")
print(f"[i] 卡片总数 {n}｜最新分享时间 {latest}")
PYCODE
