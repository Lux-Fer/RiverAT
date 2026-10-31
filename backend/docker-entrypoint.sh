#!/bin/sh
# 容器启动顺序：先跑迁移，再起服务。
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
