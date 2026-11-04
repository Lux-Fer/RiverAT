# backend

运行代码与服务端渲染页面。项目说明、快速开始、工具契约见仓库根目录 [README.md](../README.md)。

- 启动：`uv run uvicorn app.main:app --reload`（先在 `.env` 配好 `DATABASE_URL` / `REDIS_URL`）
- 迁移：`uv run alembic upgrade head`
- 测试：`uv run pytest`（需要 PostgreSQL 17 + Redis；SSH 测试另需 sshd）
- Worker：`uv run python -m app.worker`
