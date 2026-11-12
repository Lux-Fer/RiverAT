# 部署（单机 Docker Compose）

> 目标形态：一台 Linux 服务器上 `docker compose up -d` 起四件套 —— backend、worker、PostgreSQL、Redis。
> 客户内网不能出公网时，用镜像 `save` / `load` 离线搬运。

## 1. 组成

| 容器 | 镜像 | 说明 |
|---|---|---|
| `riverat-backend` | `riverat-backend:0.2.2`（本地构建） | FastAPI + 服务端渲染页面；启动时自动跑 `alembic upgrade head` |
| `riverat-worker` | 同上镜像 | arq worker，执行任务；启动时回收卡死任务、补发丢失的 queued job |
| `riverat-db` | `postgres:17` | 数据卷 `pgdata` |
| `riverat-redis` | `redis:7` | 会话与队列；数据卷 `redisdata`（可丢） |

端口：`8000`（Web）、`5433`（PG，仅本机调试）、`6379`（Redis，仅本机调试）。
生产只暴露 `8000`，由反向代理终止 TLS；数据库/Redis 已绑定 `127.0.0.1`，不应从外网访问。

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
> 所以 `SECRET_KEY` 必须用 shell export，或写进**项目根目录** `.env`（不是 `backend/.env`）；两种方式都缺失时会使用默认值并被生产守卫拒绝启动。
>
> 生产环境还会拒绝 `DEBUG=true`、默认/短于 16 字符的 `SECRET_KEY`。`validate_production_settings()` 在应用创建时执行，启动失败会在日志里给出明确原因。

模型也可以启动后在「设置」页配置：数据库配置优先于 `.env`，key 以 Fernet 加密存储。

V0.1.2 的失败恢复有三个开关：`AGENT_RECOVERY_ENABLED`（默认 `true`）、
`AGENT_RECOVERY_MAX_STEPS`（默认 `3`）、`AGENT_REPLAN_LIMIT`（默认 `2`）。
关闭后失败任务只记录结果，不调用模型生成修复草案。

V0.2.0 的 `knowledge_event` / `knowledge_item` 随常规迁移创建，不需要额外配置；
知识检索使用 PostgreSQL `pg_trgm`，不依赖外部向量服务。

V0.2.1 增加知识作用域（global/product/user）、失败/成功知识有效期，以及任务内
“有用/不相关”反馈；同样随常规迁移创建，不需要额外配置。

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
# 推荐：一条命令备份数据库 + 工具包
bash scripts/backup.sh

# 等价手工命令
docker compose exec -T db pg_dump -U riverat riverat > riverat-$(date +%F).sql
tar czf riverat-tools-$(date +%F).tar.gz --exclude='var/tools/work' -C backend var/tools

# 恢复（脚本会二次确认并先停 backend/worker）
bash scripts/restore.sh backups/db-YYYYmmdd-HHMMSS.sql.gz backups/tools-YYYYmmdd-HHMMSS.tar.gz
```

**只备份数据库不够**：工具包在文件系统里，丢了包，任务就跑不起来；`work/` 目录不用备份。脚本默认保留 14 天，生产应把 `backups/` 同步到远端或对象存储，并用 cron 每天执行。

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

worker 重启时会自动回收上次崩溃留下的卡死任务（心跳超 10 分钟，审计记 `system`），并把超过 30 秒仍在 `queued` 的任务重新入队；任务详情也提供“重新入队 →”。

## 6. 离线部署（客户内网）

在**能联网的机器**上构建并导出：

```bash
docker compose build
docker save riverat-backend:0.2.2 postgres:17 redis:7 -o riverat-images.tar
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

### 7.1 HTTPS / 反向代理

仓库提供 [deploy/Caddyfile](../deploy/Caddyfile) 作为 Caddy 示例；默认 compose 不自动启动 TLS，避免在没有域名/DNS 的环境里反复申请证书失败。

```bash
# 宿主机已有 Caddy，且 riverat.example.com 已解析到本机
export RIVERAT_DOMAIN=riverat.example.com
caddy run --config deploy/Caddyfile
```

- 只对外开放 `80/443`，把 `8000` 限制在本机或内网；
- Caddy 负责证书与 `encode zstd gzip`，RiverAT 仍只跑 HTTP；
- 若前面是 Nginx，把 `proxy_pass http://127.0.0.1:8000` 指过来，并设置 `X-Forwarded-Proto`。
- 生产不要把 `5433` / `6379` 暴露到外网；compose 已把它们绑定在 `127.0.0.1`。

## 8. 已知取舍

- **默认不启动 TLS**：仓库提供 `deploy/Caddyfile` 示例，正式环境需自行准备域名、DNS 与证书；不要长期用 HTTP 暴露到公网。
- **没有监控告警、日志收集**：容器日志走 Docker 默认驱动（`docker logs`）。
- **单实例**：会话在 Redis、执行在单 worker；暂不支持多副本与水平扩展。
- **Postgres 密码是 compose 里的明文**：仅适合内网首装；正式环境请换 Docker secret 或外部数据库。
- **工具无沙箱**：工具以服务进程权限执行，只应安装可信工具（见 `docs/tool-contract.md`）。
