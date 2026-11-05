#!/bin/bash
# stage2_cloud_process.sh — 阶段2：增量抓全文 + 归档入库（可云端跑）
# ============================================================
# 依赖只有三样：① 阶段1 产出的 yuanbao_cards.json（随 vault/仓库同步上云）
#                ② vault 仓库（水位线 / 增量批次 / 全文主仓库都在里面）
#                ③ 出网能力（抓元宝分享页）
# 不碰微信库、不碰密钥 —— 因此这一阶段可以搬到云端/CI 跑。
#
# 用法：
#   XT_ROOT=/path/to/xingtu bash stage2_cloud_process.sh
#   DRY_RUN=1 XT_ROOT=... bash stage2_cloud_process.sh   # 只看待抓清单
set -e

XT_ROOT="${XT_ROOT:?必须设置 XT_ROOT（工作区根，含 github/xingtu-vault）}"
PY="${PY:-python3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
VAULT_INV="$XT_ROOT/github/xingtu-vault/12_工具研究室/yuanbao_inventory"
VAULT_YB="$XT_ROOT/github/xingtu-vault/02_内容仓库 (Content Hub)/06_元宝对话挖掘"

echo "[$(date '+%F %H:%M')] stage2 增量抓取开始（root=$XT_ROOT）"
if [ "${DRY_RUN:-0}" = "1" ]; then
  "$PY" "$HERE/bin/yuanbao_incremental_fetch.py" --dry-run
  exit 0
fi
"$PY" "$HERE/bin/yuanbao_incremental_fetch.py"

echo "[$(date '+%F %H:%M')] 同步新全文到 vault/06_元宝对话挖掘（幂等）"
SYNCED=0
for f in "$VAULT_INV"/增量批次/*/*.md; do
  [ -e "$f" ] || continue
  bf=$(basename "$f")
  case "$bf" in _*) continue ;; esac
  token=$(echo "$bf" | grep -oE '_[A-Za-z0-9]{10,}\.md$' | sed 's/^_//;s/\.md$//')
  title=$(echo "$bf" | sed 's/^[0-9_]*//;s/_[A-Za-z0-9]*\.md$//')
  [ -z "$token" ] && continue
  dst="$VAULT_YB/元宝分享文章_${title}_${token}.md"
  if [ ! -f "$dst" ]; then cp "$f" "$dst" && SYNCED=$((SYNCED+1)); fi
done
echo "[i] 新同步 $SYNCED 篇到 vault/06（已存在跳过）"

echo "[$(date '+%F %H:%M')] 归档入库（时间线/选题池/会话归档）"
"$PY" "$HERE/bin/ingest_yuanbao_archive.py" yuanbao || echo "[!] ingest 返回非零（无新增待归档属幂等，需人工确认）"

echo "[$(date '+%F %H:%M')] stage2 完成"
