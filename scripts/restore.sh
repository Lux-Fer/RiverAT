#!/usr/bin/env bash
# RiverAT 恢复：先停 backend/worker，再导入数据库和工具包。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -ne 2 ]; then
  echo "usage: bash scripts/restore.sh backups/db-YYYYmmdd-HHMMSS.sql.gz backups/tools-YYYYmmdd-HHMMSS.tar.gz" >&2
  exit 2
fi

db_file="$1"
tools_file="$2"
printf 'This overwrites the current database and backend/var/tools. Type YES to continue: '
read -r answer
[ "$answer" = "YES" ] || { echo "aborted"; exit 1; }

docker compose stop backend worker
gunzip -c "$db_file" | docker compose exec -T db psql -U riverat -d riverat
tar -xzf "$tools_file" -C backend
docker compose up -d backend worker
echo "restore complete; verify /health and a recorded task"
