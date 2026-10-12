#!/bin/bash
# safe-delete.sh — 安全删除：mv 到工作区本地回收站，永不 rm 用户文件
# 用法:
#   safe-delete.sh <path> [path2 ...]      把文件/目录移入回收站
#   safe-delete.sh --list                  列出回收站条目及原路径
#   safe-delete.sh --restore <trash-name>  恢复到原位
#   safe-delete.sh --clean [days]          清理 N 天前的回收站条目（仅限回收站内部）
#
# 回收站默认位于 <xingtu>/.trash（脚本自动定位工作区根），可用环境变量
# SAFE_DELETE_TRASH 覆盖。
#
# ⛔ 设计铁律（Boss 要求）：工作区文件只进回收站，绝不 rm。
#    --clean 只删除“回收站内部”已删除的条目，且做了禁区越界防护，
#    任何情况下都不会触碰工作区真实文件。

set -euo pipefail

# 定位工作区根（脚本位于 <root>/tools/safety/ 下）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XINGTU_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRASH_DIR="${SAFE_DELETE_TRASH:-${XINGTU_ROOT}/.trash}"
LOG_FILE="${TRASH_DIR}/trash.log"
mkdir -p "${TRASH_DIR}"

# 越界防护：TRASH_DIR 不得落在系统根 / 家目录等禁区
guard_trash_dir() {
  case "${TRASH_DIR}" in
    /|/Users|/Home|/home|"${HOME}"|"${HOME}/"*)
      echo "安全拦截：TRASH_DIR=${TRASH_DIR} 处于禁区，拒绝操作。" >&2
      exit 3 ;;
  esac
  [[ -d "${TRASH_DIR}" ]] || mkdir -p "${TRASH_DIR}"
}

log_entry() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_FILE}"; }

if [[ "${1:-}" == "--list" ]]; then
  echo "=== 回收站 (${TRASH_DIR}) ==="
  entries="$(ls -A "${TRASH_DIR}" 2>/dev/null | grep -v '^trash\.log$' | grep -v '^\.origin_')"
  if [[ -z "${entries}" ]]; then
    echo "  (空)"
  else
    for e in ${entries}; do
      origin="$(cat "${TRASH_DIR}/.origin_${e}" 2>/dev/null || echo '(未知原路径)')"
      printf '  %s  <-  %s\n' "${e}" "${origin}"
    done
  fi
  exit 0
fi

if [[ "${1:-}" == "--clean" ]]; then
  guard_trash_dir
  DAYS="${2:-30}"
  echo "清理 ${DAYS} 天前的回收站条目（仅限回收站内部，绝不触碰工作区）..."
  find "${TRASH_DIR}" -maxdepth 1 -mindepth 1 ! -name 'trash.log' ! -name '.origin_*' -mtime "+${DAYS}" -exec rm -rf {} \; 2>/dev/null || true
  # 同步清理孤儿 .origin 副作用文件
  for o in "${TRASH_DIR}"/.origin_*; do
    [[ -e "${o}" ]] || continue
    base="${o#${TRASH_DIR}/.origin_}"
    [[ -e "${TRASH_DIR}/${base}" ]] || rm -f "${o}" 2>/dev/null || true
  done
  log_entry "CLEAN: 清理了 ${DAYS} 天前的回收站条目"
  echo "完成"
  exit 0
fi

if [[ "${1:-}" == "--restore" ]]; then
  TRASH_NAME="${2:-}"
  if [[ -z "${TRASH_NAME}" ]]; then echo "用法: safe-delete.sh --restore <trash-name>"; exit 1; fi
  SOURCE="${TRASH_DIR}/${TRASH_NAME}"
  if [[ ! -e "${SOURCE}" ]]; then echo "错误: ${TRASH_NAME} 不在回收站中"; exit 1; fi
  ORIGINAL_PATH="$(cat "${TRASH_DIR}/.origin_${TRASH_NAME}" 2>/dev/null || echo "")"
  if [[ -z "${ORIGINAL_PATH}" ]]; then echo "错误: 找不到原始路径记录，无法恢复"; exit 1; fi
  if [[ -e "${ORIGINAL_PATH}" ]]; then echo "错误: 原路径已存在文件，中止以免覆盖: ${ORIGINAL_PATH}"; exit 1; fi
  mv "${SOURCE}" "${ORIGINAL_PATH}"
  rm -f "${TRASH_DIR}/.origin_${TRASH_NAME}" 2>/dev/null || true
  log_entry "RESTORE: ${TRASH_NAME} -> ${ORIGINAL_PATH}"
  echo "完成 -> ${ORIGINAL_PATH}"
  exit 0
fi

if [[ $# -eq 0 ]]; then
  echo "用法: safe-delete.sh [--list|--restore <name>|--clean [days]| <path>...]"
  exit 1
fi

for TARGET in "$@"; do
  if [[ ! -e "${TARGET}" ]]; then
    echo "警告: ${TARGET} 不存在，跳过"
    log_entry "SKIP: ${TARGET}"
    continue
  fi
  ABS_PATH="$(cd "$(dirname "${TARGET}")" 2>/dev/null && pwd)/$(basename "${TARGET}")"
  TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
  BASENAME="$(basename "${TARGET}")"
  TRASH_NAME="${TIMESTAMP}_${BASENAME}"
  DEST="${TRASH_DIR}/${TRASH_NAME}"
  if [[ -e "${DEST}" ]]; then
    TRASH_NAME="${TIMESTAMP}_${BASENAME}_$((RANDOM % 1000))"
    DEST="${TRASH_DIR}/${TRASH_NAME}"
  fi
  mv "${TARGET}" "${DEST}"
  echo "${ABS_PATH}" > "${TRASH_DIR}/.origin_${TRASH_NAME}"
  log_entry "DELETE: ${ABS_PATH} -> ${TRASH_NAME}"
  echo "已移至回收站: ${TRASH_NAME}"
done
