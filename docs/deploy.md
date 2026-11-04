# 部署（单机 Docker Compose）

> 目标形态：一台 Linux 服务器上 `docker compose up -d` 起四件套 —— backend、worker、PostgreSQL、Redis。
> 客户内网不能出公网时，用镜像 `save` / `load` 离线搬运。

## 1. 组成

| 容器 | 镜像 | 说明 |
|---|---|---|
| `riverat-backend` | `riverat-backend:0.1.0`（本地构建） | FastAPI + 服务端渲染页面；启动时自动跑 `alembic upgrade head` |
| `riverat-worker` | 同上镜像 | arq worker，执行任务；启动时回收卡死任务 |
| `riverat-db` | `postgres:17` | 数据卷 `pgdata` |
| `riverat-redis` | `redis:7` | 会话与队列；数据卷 `redisdata`（可丢） |

端口：`8000`（Web）、`5433`（PG，仅调试）、`6379`（Redis，仅调试）。
生产建议只暴露 8000，并在前面加反向代理。

### 构建时的 pip 源

镜像构建默认走清华镜像（国内访问 `files.pythonhosted.org` 容易读超时）：

```bash
docker compose build backend
# 海外网络可切回官方源
docker compose build backend --build-arg PIP_INDEX_URL=https://pypi.org/simple
```

依赖清单 `backend/requirements.txt` 从 `uv.lock` 导出，改依赖后重新生成：

```bash
cd backend
uv export --frozen --no-dev --format requirements-txt --no-hashes \
  --output-file requirements.txt
```

## 2. 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `SECRET_KEY` | **是** | 会话签名 + 凭据加密；换掉它，已存的加密凭据就解不开 |
| `ADMIN_PASSWORD` | 首次启动 | 库里没有用户时才生效，用来建 `admin` |
| `ADMIN_USERNAME` | 否 | 默认 `admin` |

DB / Redis 地址在 compose 里已固定为服务名 `db` / `redis`，无需配置。

**模型端点**写进 `backend/.env`，compose 通过 `env_file` 注入 backend 与 worker：

```bash
RIVERAT_LLM_BASE_URL=https://api.deepseek.com
RIVERAT_LLM_MODEL=deepseek-flash
RIVERAT_LLM_API_KEY=sk-...
```

> 注意：compose 的 `environment` 里 `SECRET_KEY` 用的是 shell 变量 `${SECRET_KEY}`，优先级高于 `backend/.env`。
> 所以 **SECRET_KEY 必须用 shell export**，写进 `backend/.env` 会被覆盖成默认值 `change-me-in-production`。

模型也可以启动后在「模型设置」页配置：数据库配置优先于 `.env`，key 以 Fernet 加密存储。

## 3. 首次启动

```bash
export SECRET_KEY="$(openssl rand -hex 32)"
export ADMIN_PASSWORD="your-strong-password"

cat > backend/.env <<'EOF'
RIVERAT_LLM_BASE_URL=https://api.deepseek.com
RIVERAT_LLM_MODEL=deepseek-flash
RIVERAT_LLM_API_KEY=sk-...
EOF

docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health     # {"status":"ok","env":"prod"}
```

浏览器打开 `http://<服务器>:8000/login` 登录（默认 `admin`）。
登录后在「用户」页给同事建账号，分配 `viewer` / `engineer` / `admin`。

## 4. 数据与备份

| 数据 | 位置 |
|---|---|
| 数据库（用户/产品/工具元数据/任务/审计） | Docker 卷 `pgdata` |
| 工具包（`<sha256>.tar.gz`） | 宿主 `backend/var/tools/`（挂载进 `/app/backend/var`） |
| 工具工作目录（解压 + 依赖） | `backend/var/tools/work/<sha256>/`（可删，下次执行重建） |
| Redis（会话 + 队列） | Docker 卷 `redisdata`，可丢 |

```bash
# 备份
docker compose exec -T db pg_dump -U riverat riverat > riverat-$(date +%F).sql
tar czf riverat-tools-$(date +%F).tar.gz -C backend var/tools

# 恢复
cat riverat-2026-11-04.sql | docker compose exec -T db psql -U riverat riverat
tar xzf riverat-tools-2026-11-04.tar.gz -C backend
```

**只备份数据库不够**：工具包在文件系统里，丢了包，任务就跑不起来；`work/` 目录不用备份。

占空间时清工作目录（不影响已上传的包，下次执行会重新解压/安装）：

```bash
rm -rf backend/var/tools/work/*
```

## 5. 升级

```bash
git pull
docker compose build backend          # backend 与 worker 共用同一镜像
docker compose up -d                  # 入口脚本自动 alembic upgrade head
```

worker 重启时会自动回收上次崩溃留下的卡死任务（心跳超 10 分钟，审计记 `system`）。

## 6. 离线部署（客户内网）

在**能联网的机器**上构建并导出：

```bash
docker compose build
docker save riverat-backend:0.1.0 postgres:17 redis:7 -o riverat-images.tar
tar czf riverat-src.tar.gz docker-compose.yml backend frontend docs
```

在**目标机器**上：

```bash
docker load -i riverat-images.tar
tar xzf riverat-src.tar.gz
export SECRET_KEY="$(openssl rand -hex 32)"
export ADMIN_PASSWORD="your-strong-password"
docker compose up -d --no-build
```

`--no-build` 是关键：它只拉本地已有镜像，不会去公网。

## 7. 日常运维

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f worker
curl http://127.0.0.1:8000/health
```

- 任务卡住：worker 重启自动回收，或 admin 在「任务」页「疑似卡住」区手动标记失败。
- worker 与 backend 必须用同一镜像版本，否则协议可能不一致。
- 队列并发由 worker 的 `max_jobs` 控制（默认 4）。

## 8. 已知取舍

- **没有反向代理 / HTTPS**：v1.1 假设内网部署；对外请在前面加 Nginx/Caddy 终止 TLS。
- **没有监控告警、日志收集**：容器日志走 Docker 默认驱动（`docker logs`）。
- **单实例**：会话在 Redis、执行在单 worker；暂不支持多副本与水平扩展。
- **Postgres 密码是 compose 里的明文**：仅适合内网首装；正式环境请换 Docker secret 或外部数据库。
- **工具无沙箱**：工具以服务进程权限执行，只应安装可信工具（见 `docs/tool-contract.md`）。
