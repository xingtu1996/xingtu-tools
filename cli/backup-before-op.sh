#!/bin/bash
# backup-before-op.sh — 批量操作前快照备份（遵守 Boss“做好备份”铁律）
# 用法: backup-before-op.sh <操作描述> <路径1> [路径2 ...]
#  示例: backup-before-op.sh '重组目录' ./dir1 ./dir2
#
# 备份默认落在 <xingtu>/.backups（脚本自动定位工作区根），可用环境变量
# BACKUP_BEFORE_OP_DIR 覆盖。每次操作打包成带时间戳+描述的 tar.gz，
# 并写 .meta 记录原路径，便于回滚。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XINGTU_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKUP_DIR="${BACKUP_BEFORE_OP_DIR:-${XINGTU_ROOT}/.backups}"
mkdir -p "${BACKUP_DIR}"

if [[ $# -lt 2 ]]; then
  echo "用法: backup-before-op.sh <操作描述> <路径1> [路径2 ...]"
  echo "示例: backup-before-op.sh '重组目录' ./dir1 ./dir2"
  exit 1
fi

DESCRIPTION="$1"
shift

TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_NAME="${TIMESTAMP}_${DESCRIPTION// /-}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"

echo "=== 操作前快照 ==="
echo "操作: ${DESCRIPTION}"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "路径: $@"
echo ""

MISSING=()
for P in "$@"; do
  [[ ! -e "${P}" ]] && MISSING+=("${P}")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "警告: 以下路径不存在，将从备份中排除:"
  for P in "${MISSING[@]}"; do echo "  - ${P}"; done
  echo ""
fi

EXISTING=()
for P in "$@"; do
  [[ -e "${P}" ]] && EXISTING+=("${P}")
done
if [[ ${#EXISTING[@]} -eq 0 ]]; then
  echo "错误: 没有可备份的路径"
  exit 1
fi

echo "创建备份: ${BACKUP_NAME}.tar.gz"
tar -czf "${BACKUP_PATH}" "${EXISTING[@]}" 2>/dev/null

SIZE="$(du -h "${BACKUP_PATH}" | cut -f1)"
echo "完成 (${SIZE})"

cat > "${BACKUP_PATH}.meta" << EOF
time: $(date '+%Y-%m-%d %H:%M:%S')
description: ${DESCRIPTION}
paths: ${*}
backup_file: ${BACKUP_NAME}.tar.gz
EOF

echo ""
echo "现有备份 (最近 10 个):"
ls -lt "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | head -10 | awk '{print $6, $7, $8, $9}' || echo "  (无)"
