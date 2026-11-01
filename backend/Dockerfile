# syntax=docker/dockerfile:1
# 构建上下文是仓库根（要同时拷 backend 与 frontend），见 docker-compose.yml。
FROM python:3.11-slim

WORKDIR /app/backend

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 依赖先装，利用层缓存；requirements.txt 由 uv.lock 导出（见 docs/deploy.md）
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY backend/docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# 前端与 backend 平级：config.BASE_DIR.parent / "frontend"
COPY frontend /app/frontend

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
