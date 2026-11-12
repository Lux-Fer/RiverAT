<div align="center">

# ■ RIVERAT

**River + AT = AutoTest**

把测试团队已有的能力，接成一条可见的工作流。

`V0.1.2`　`私有化 / 内网`　`FastAPI · PostgreSQL · Redis · arq`

</div>

---

> 平台不规定测试怎么写；只规定三件事：工具如何被调用，工作如何被确认，结果如何被记录。

RiverAT 面向 5–20 人的测试团队：一个团队要接多个产品，产品各有地址与 CI，测试能力散落在 pytest、Robot、自研脚本和手工工具里。

RiverAT 不做用例管理，也不规定测试写法。它把团队已有的测试能力包成工具，让一句测试需求变成**可确认、可执行、可追溯**的工作流。

---

## 一条工作流

```text
                    一句话需求
                        │
                        ▼
                  任务草案（工具 + 参数）
                        │
                  人确认 / 改参数
                        │
                        ▼
   tar.gz 工具 ──► arq worker ──► 工具进程 ──► 用例结果
                        │
             超时 / 退出码 / stderr / 证据
                        │ 失败
                        ▼
        失败观察 ──► Agent 修复草案（仍是 draft）
                        │
                  人打开 / 确认
```

**人在环**是产品约束，不是提示语：AI 只负责理解与建议，任何有副作用的动作都要人确认。V0.1.2 增加了失败结果的回喂：模型能看到失败步骤再提修复草案，但新工具不会自动执行。

## 快速开始

需要 Docker Compose。模型端点可选：不配时仍可用「手动创建任务」；要对话生成草案，再在「设置」里配。

```bash
# 1) 会话签名与凭据加密都依赖它；必须用 shell 变量传入
export SECRET_KEY="$(openssl rand -hex 32)"
# 首次启动、库里没有用户时，用它创建 admin
export ADMIN_PASSWORD="your-strong-password"

# 2) 模型端点（可跳过；登录后在「设置」里填）
cat > backend/.env <<'EOF'
RIVERAT_LLM_BASE_URL=https://api.deepseek.com
RIVERAT_LLM_MODEL=deepseek-flash
RIVERAT_LLM_API_KEY=sk-你的key
EOF

# 3) 启动 PostgreSQL、Redis、backend、worker
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

打开 `http://<服务器>:8000/login`，用 `admin` / `ADMIN_PASSWORD` 登录。

> `SECRET_KEY` 和 `ADMIN_PASSWORD` 必须由 shell 传入：compose 里的 `${...}` 优先级高于 `backend/.env`。写进 `.env` 会被默认值覆盖。

<details>
<summary>Windows PowerShell</summary>

```powershell
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:ADMIN_PASSWORD = "your-strong-password"

$envText = @'
RIVERAT_LLM_BASE_URL=https://api.deepseek.com
RIVERAT_LLM_MODEL=deepseek-flash
RIVERAT_LLM_API_KEY=sk-你的key
'@
[IO.File]::WriteAllText("backend/.env", $envText, [Text.UTF8Encoding]::new($false))

docker compose up -d --build
```

</details>

默认端口：`8000` Web，`5433` PostgreSQL，`6379` Redis。生产环境只暴露 `8000`，并在前面加反向代理。

## 第一次使用

1. 登录 → 右上角齿轮「设置」→ 打开模型页，填端点并测试连接。
2. 产品 → 注册被测产品。编码、名称必填；地址可留空，填写时必须以 `http://` 或 `https://` 开头。
3. 工具 → 上传 `tar.gz`，由 admin 审核通过。示例工具见 [tools/text-doc-check](tools/text-doc-check/README.md)。
4. 助手 → 选择产品，说一句要测什么，点「发送」。
5. 在「最新草案」里检查工具与参数，必要时展开任务详情改参数，确认执行。
6. 任务 → 查看步骤、退出码和用例结果；审计在「设置」里查。
7. 模型不可用或不想用模型时：任务 → 手动创建任务，直接选工具填参数，同样走确认流程。

## 工具契约

工具是一个 `tar.gz`，根目录包含 `tool.json` 和入口脚本：

```json
{
  "name": "login_smoke",
  "version": "1.0.0",
  "description": "对被测产品执行登录冒烟",
  "entrypoint": {"linux": ["python", "main.py"]},
  "input_schema": {
    "type": "object",
    "properties": {"base_url": {"type": "string"}},
    "required": ["base_url"]
  },
  "timeout_seconds": 600
}
```

平台通过 **stdin** 传入：

```json
{"args": {"base_url": "http://10.0.0.6:8080"}, "product": {"code": "DEMO"}}
```

工具向 **stdout** 返回：

```json
{"cases": [{"case_id": "login-1", "status": "passed", "duration_ms": 11, "reason": ""}]}
```

退出码非 0 记 `failed`；超时会杀掉整个进程树。完整字段、平台注入的环境变量和限制见 [docs/tool-contract.md](docs/tool-contract.md)。

## 架构

```text
Browser
  │  Jinja2 SSR + HTMX（无 Node 构建）
  ▼
FastAPI backend ────────────── PostgreSQL
  │                                │
  │                                └─ 用户 / 产品 / 工具 / 任务 / 审计
  ▼
Redis ── arq worker ── 工具进程（tar.gz 解压执行）
```

`backend` 与 `worker` 共用同一个镜像；worker 只负责执行和回收卡死任务。数据库与 Redis 默认落在 Docker named volume，工具包留在宿主机的 `backend/var/tools/`。

## 开发

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
```

本地测试需要 PostgreSQL 与 Redis：

```bash
uv run pytest
uv run ruff check app tests
```

前端是服务端渲染。改模板或 `river.css` 后刷新即可；Docker 部署需要重建镜像。开发时只启动一个 worker：要么用 `uv run python -m app.worker`，要么用容器 `riverat-worker`，不要同时启动，避免重复消费队列。

## 已知限制

- 单机 Docker Compose；默认不启动 HTTPS，仓库提供 `deploy/Caddyfile` 示例；没有监控告警 / 自动备份服务，内网试点可以，直接公网不行。
- 生产启动会拒绝默认/过短的 `SECRET_KEY` 和 `DEBUG=true`；首次部署务必用 `openssl rand -hex 32` 生成。
- 工具以服务进程权限在 RiverAT 主机运行，没有沙箱；只安装可信工具。
- 只支持本地执行，没有远程 runner / WinRM。
- 工具产物文件不回收，工具工作目录不会自动清理。
- CI 通知在 V0.1.2 只保存配置占位，不实际收发。
- v1.0 遗留 API（`/api/v1/plans`、`/runs`、`/releases` 等）仍挂载但已冻结，页面已下线，不要在其上开发。

---

<div align="center">

<sub>RiverAT V0.1.2 · 人在环 · 工具即能力 · 工作流可见</sub>

</div>
