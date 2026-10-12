#!/usr/bin/env bash
# env-check.sh — 行途工作区环境自检（轻量，内容工作空间适用）
# 用途: 进入工作区前一键确认 工具链 + 结构完整性 + 安全机制 是否就位
# 使用: bash env-check.sh [--verbose]
#
# 区别于 CC 侧 env-check.sh（面向 VDI/Copilot/Java/.NET 开发环境），
# 本版针对 xingtu 内容工作空间：检查磁盘、python/node/git、锚点文件、
# 六层目录、以及安全脚本是否就位。

set -uo pipefail

VERBOSE=false
[[ "${1:-}" == "--verbose" ]] && VERBOSE=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XINGTU_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PASS=0; FAIL=0; SKIP=0; WARN=0
ok()   { echo -e "\033[0;32m[OK]\033[0m      $*";   ((PASS++)); }
fail() { echo -e "\033[0;31m[FAIL]\033[0m    $*";   ((FAIL++)); }
skip() { echo -e "\033[1;33m[SKIP]\033[0m    $*";   ((SKIP++)); }
warn() { echo -e "\033[1;33m[WARN]\033[0m    $*";   ((WARN++)); }

echo "=========================================="
echo "  行途工作区环境自检  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  根: ${XINGTU_ROOT}"
echo "=========================================="

# 1. 磁盘剩余
FREE_G=$(df -g "${XINGTU_ROOT}" 2>/dev/null | awk 'NR==2{print $4}')
if [[ ${FREE_G:-0} -lt 5 ]]; then
  warn "磁盘剩余 ${FREE_G}G（<5G，注意清理，当前机器已 ~93% 占用）"
else
  ok "磁盘剩余 ${FREE_G}G"
fi

# 2. 工具链
for c in python3 node git; do
  if command -v "$c" &>/dev/null; then
    ok "$c 可用: $($c --version 2>&1 | head -1)"
  else
    warn "$c 未安装（内容工作可缺，但脚本类任务需要）"
  fi
done

# 3. 锚点文件（给 AI 进空间时快速定位）
for f in HARNESS.md DIRECTORY.md README.md; do
  if [[ -f "${XINGTU_ROOT}/$f" ]]; then ok "锚点文件存在: $f"; else fail "锚点文件缺失: $f"; fi
done

# 4. 六层目录（harness 体系映射）
for d in "01_战略与规章 (Strategy & Rules)" "02_内容仓库 (Content Hub)" \
         "03_运营工具箱 (Operations Toolkit)" "04_会话与复盘 (Archive & Review)" \
         "06_个人知识库_Obsidian" rules workflows tools; do
  if [[ -d "${XINGTU_ROOT}/$d" ]]; then ok "目录存在: $d"; else warn "目录缺失: $d"; fi
done

# 5. 安全机制就位
[[ -f "${SCRIPT_DIR}/safe-delete.sh" ]] && ok "safe-delete.sh 就位（替代 rm）" || fail "safe-delete.sh 缺失"
[[ -f "${SCRIPT_DIR}/backup-before-op.sh" ]] && ok "backup-before-op.sh 就位（操作前备份）" || fail "backup-before-op.sh 缺失"

echo "=========================================="
echo "  结果: ${PASS} PASS  ${FAIL} FAIL  ${SKIP} SKIP  ${WARN} WARN"
echo "=========================================="

if [[ $FAIL -gt 0 ]]; then
  echo "⚠️  有 $FAIL 项不通过，请先补齐锚点/安全脚本。"
  exit 1
else
  echo "✅ 基础环境就绪。"
  exit 0
fi
