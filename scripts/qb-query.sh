#!/bin/bash
# ============================================================================
# qb-query.sh — 统一连库查询入口（行途 · 借鉴 01-db-query/db-query.sh）
# 用法:
#   bash qb-query.sh "<SQL>"                          # 默认 newapi 网关库
#   bash qb-query.sh -prod "<SQL>"                    # prod 只读护栏
# 连接: ${NEWAPI_DB_DSN}（settings.local.json env: newapi:pass@tcp(host:3306)/newapi）
# 依赖: mysql 客户端（brew install mysql-client）
# 安全: ① prod 只读护栏（仅 SELECT/SHOW/DESC/EXPLAIN/WITH）② 密码走 MYSQL_PWD 不进 ps
# ============================================================================
set -euo pipefail

# --- 解析 DSN: user:pass@tcp(host:port)/db ---
parse_dsn() {
  local dsn="${NEWAPI_DB_DSN:-}"
  [ -n "$dsn" ] || { echo "❌ 未配置 NEWAPI_DB_DSN（settings.local.json env）"; exit 1; }
  DB_USER="${dsn%%:*}"
  local rest="${dsn#*:}"
  DB_PASS="${rest%%@*}"
  local hp="${rest#*@tcp(}"
  DB_HOST="${hp%%:*}"
  DB_PORT="${hp##*:}"
  DB_PORT="${DB_PORT%%)*}"
}
parse_dsn

# --- 参数 ---
PROD=0
[ "${1:-}" = "-prod" ] && { PROD=1; shift; }
SQL="${1:-}"
[ -n "$SQL" ] || { echo "❌ 用法: bash qb-query.sh [-prod] \"<SQL>\""; exit 1; }
DB_NAME="${2:-newapi}"

# --- prod 只读护栏 ---
if [ "$PROD" = "1" ]; then
  if echo "$SQL" | grep -qiE '(insert|update|delete|drop|alter|truncate|replace|create|grant|set\s)'; then
    echo "❌ prod 只读护栏: 检测到写操作关键词"; exit 1
  fi
  if ! echo "$SQL" | grep -qiE '^\s*(select|show|desc|explain|with)\b'; then
    echo "❌ prod 只读护栏: 首词非只读语句"; exit 1
  fi
fi

# --- 执行（打印连接目标防连错库；密码走 MYSQL_PWD 不进 ps）---
echo "🔌 [$([ $PROD = 1 ] && echo prod || echo default)] $DB_NAME @ $DB_HOST:$DB_PORT"
MYSQL_PWD="$DB_PASS" mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" "$DB_NAME" -e "$SQL"
unset DB_PASS MYSQL_PWD
