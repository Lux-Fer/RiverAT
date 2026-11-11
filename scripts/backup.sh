#!/usr/bin/env bash
# RiverAT 备份：PostgreSQL + 工具包（不包含可重建的 work/）。
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups
stamp="$(date +%Y%m%d-%H%M%S)"

docker compose exec -T db pg_dump -U riverat -d riverat | gzip > "backups/db-$stamp.sql.gz"
tar -czf "backups/tools-$stamp.tar.gz" \
  --exclude='var/tools/work' \
  -C backend var/tools

# 只保留最近 14 天的本地备份；生产环境请把 backups/ 同步到远端。
find backups -type f -mtime +14 -delete
printf 'backup written: backups/db-%s.sql.gz backups/tools-%s.tar.gz\n' "$stamp" "$stamp"
