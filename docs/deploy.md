# 部署（单机 Docker Compose）

> 目标形态：一台 Linux 服务器上 `docker compose up -d` 起三件套 —— 后端、PostgreSQL、Redis。
> 客户内网不能出公网时，用镜像 `save` / `load` 离线搬运。

## 1. 组成

| 容器 | 镜像 | 说明 |
|---|---|---|
| `riverat-backend` | `riverat-backend:0.1.0`（本地构建） | FastAPI + 页面；启动时自动跑 `alembic upgrade head` |
| `riverat-db` | `postgres:17` | 数据卷 `pgdata` |
| `riverat-redis` | `redis:7` | 会话存储，数据卷 `redisdata` |

端口：`8000`（Web）、`5433`（PG，仅调试用）、`6379`（Redis，仅调试用）。

### 依赖清单

`backend/requirements.txt` 是从 `uv.lock` 导出的运行时依赖，镜像构建直接用它
（容器里不装 uv，只用 pip）。改了依赖后重新生成：

```bash
cd backend
uv export --frozen --no-dev --format requirements-txt --no-hashes \
  --output-file requirements.txt
```

### 构建时的 pip 源

镜像构建默认走清华镜像（国内访问 `files.pythonhosted.org` 容易读超时）：

```bash
docker compose build backend
# 海外网络可切回官方源
docker compose build backend --build-arg PIP_INDEX_URL=https://pypi.org/simple
```

## 2. 首次启动

```bash
# 必改：SECRET_KEY 同时用于会话签名和测试机凭据加密；
# 换了它，已存的测试机密码就解不开了。
export SECRET_KEY="$(openssl rand -hex 32)"
# 可选：首次启动时自动建管理员（库里没有用户才生效）
export ADMIN_PASSWORD="your-strong-password"

docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health     # {"status":"ok","env":"prod"}
```

浏览器打开 `http://<服务器>:8000/login`，用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录（默认 `admin`）。
登录后在「用户」页给同事建账号、分配 `viewer` / `engineer` 角色。

## 3. 数据与备份

| 数据 | 位置 |
|---|---|
| 数据库 | Docker 卷 `pgdata` |
| Redis（会话，可丢） | Docker 卷 `redisdata` |
| 插件包 / 运行时文件 | 宿主机 `backend/var/`（挂载进容器 `/app/backend/var`） |

```bash
# 备份
docker compose exec -T db pg_dump -U riverat riverat > riverat-$(date +%F).sql
# 恢复
cat riverat-2026-11-01.sql | docker compose exec -T db psql -U riverat riverat
```

## 4. 离线部署（客户内网）

在**能联网的机器**上构建并导出：

```bash
docker compose build
docker save riverat-backend:0.1.0 postgres:17 redis:7 -o riverat-images.tar
# 连同仓库代码一起拷走
tar czf riverat-src.tar.gz docker-compose.yml backend/Dockerfile backend/migrations ...
```

在**目标机器**上：

```bash
docker load -i riverat-images.tar
docker compose up -d --no-build
```

`--no-build` 是关键：它只拉本地已有镜像，不会去公网。

## 5. 升级

```bash
docker compose build backend
docker compose up -d backend      # 入口脚本会自动 alembic upgrade head
```

迁移是幂等的，重复启动不会重复执行。

## 6. 已知取舍

- **没有反向代理 / HTTPS**：v1 假设部署在内网。要对外时在前面加 Nginx/Caddy 终止 TLS。
- **没有日志收集**：容器日志走 Docker 默认驱动（`docker logs riverat-backend`）。
- **单实例**：会话在 Redis、任务同步执行，暂不支持多副本；队列化之后再谈水平扩展。
- **POSTGRES 密码是 compose 里的明文**：仅适合内网首装；正式环境请换成 Docker secret 或外部数据库。
