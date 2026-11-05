# RiverAT

**承接多个被测产品的测试工作**：工程师配置模型、注册产品、安装工具；用一句话提出测试需求，
平台生成**任务草案**，人确认后调用工具执行，并把工作流与结果（精确到用例）展示出来。

- 平台不规定测试怎么写：工具由测试团队自己开发，包成 `tar.gz` 上传。
- 平台不替人做主：任何有副作用的动作都要人确认（v1.1 不做自主执行）。
- 平台不猜结果：工具返回结构化 JSON，平台只负责调度、执行、记录。

## 现在能做什么

| 能力 | 说明 |
|---|---|
| 模型配置 | OpenAI 兼容端点（云端 API 或本地服务）；key 加密存库 |
| 产品注册 | 名称、编码、地址、CI 配置（v1.1 只保存占位） |
| 工具安装 | 上传 `tar.gz` + `tool.json`；engineer 上传、admin 审核 |
| 对话 → 草案 | 把请求转成工具调用草案，参数按 `input_schema` 校验 |
| 人确认 → 执行 | 可改参数；确认后由 worker 执行；单步失败不中断后续步骤 |
| 工作流 | 将进行 / 进行中 / 已完成；取消（含运行中）、重跑、手动创建 |
| 结果 | 步骤状态、退出码、用例级结果、stderr；审计可查 |
| 可靠性 | worker 心跳 + 卡死任务回收（启动自动、admin 手动） |
| 界面 | 浅色/深色跟随系统；顶栏读数条常驻平台状态 |

## 快速开始（Docker Compose）

```bash
# 1) 必改：会话签名与凭据加密都依赖它
export SECRET_KEY="$(openssl rand -hex 32)"
# 2) 首次启动自动建管理员（库里没有用户时才生效）
export ADMIN_PASSWORD="your-strong-password"

# 3) 模型端点：写进 backend/.env，compose 会注入容器
cat > backend/.env <<'EOF'
RIVERAT_LLM_BASE_URL=https://api.deepseek.com
RIVERAT_LLM_MODEL=deepseek-flash
RIVERAT_LLM_API_KEY=sk-你的key
EOF

docker compose up -d --build
curl http://127.0.0.1:8000/health     # {"status":"ok","env":"prod"}
```

打开 `http://<服务器>:8000/login`，用 `admin` / `ADMIN_PASSWORD` 登录。

> 模型也可以不写 `.env`：登录后到「模型设置」页填 base_url / model / key，保存后以数据库配置为准。

## 走一遍完整链路

1. **模型设置**（admin）→ 填端点 → 「测试连接」真实调用一次模型。
2. **产品** → 注册被测产品（编码、名称、地址）。
3. **工具** → 上传 `tar.gz` → admin 在「工具」页点「通过」。
4. **助手** → 选产品，说一句"用账号 tester 对 DEMO 的登录做冒烟检查" → 生成草案。
5. 草案里可以**改参数**（JSON 文本域）→ 点「确认执行」。
6. **任务** → 「已完成」里点进去看步骤与用例结果；「审计」里看谁确认、谁改过参数。
7. 模型不可用时：**任务 → 手动创建任务**，直接选工具填参数（同样走草案与确认）。

## 工具契约（摘要）

工具 = 一个 `tar.gz`，根目录含 `tool.json`：

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

平台通过 **stdin 传 JSON**（`{"args": ..., "product": ...}`），工具往 **stdout 写 JSON**（含 `cases[]`），
退出码非 0 记 `failed`，超时终止进程树。完整字段、示例与限制见 [docs/tool-contract.md](docs/tool-contract.md)。

## 目录

```
backend/app
  api/v1/         # REST：assistant / tasks / tools / work-products / llm-config / audit
  services/       # 业务：llm、tasks、tool_exec、tools、work_products、audit、readout
  web/            # 服务端渲染页面：助手 / 任务 / 产品 / 工具 / 设置 / 用户 / 审计
  worker/         # arq worker：执行任务、启动时回收卡死任务
frontend/         # Jinja2 模板 + 静态资源（无 Node 构建）
docs/             # 部署、契约、决策记录、v1.1 设计
backend/migrations# Alembic（12 个，启动自动 upgrade head）
```

## 开发

```bash
cd backend
uv sync
uv run pytest                 # 需要本地 PostgreSQL/Redis；见 tests/conftest.py
uv run ruff check app tests
uv run alembic upgrade head
```

前端是服务端渲染，改模板/CSS 后重启 backend 即可（Docker 部署需重建镜像）。

## 文档

| 文件 | 内容 |
|---|---|
| [docs/deploy.md](docs/deploy.md) | 部署、环境变量、备份、离线安装、升级 |
| [docs/tool-contract.md](docs/tool-contract.md) | 工具契约 v2：包结构、JSON 输入输出、限制 |
| [docs/design-v1.1.md](docs/design-v1.1.md) | v1.1 设计：数据模型、流程、里程碑 |
| [docs/decisions-riverat-requirements.md](docs/decisions-riverat-requirements.md) | 决策记录 D1–D109（含 v1.1 转向） |
| [tools/text-doc-check](tools/text-doc-check/README.md) | 示例工具：本地文本文档检查 |
| [PRODUCT.md](PRODUCT.md) | 产品定位、用户、原则 |
| [DESIGN.md](DESIGN.md) | 视觉系统：精密仪表、token、组件 |

## 已知限制（v1.1 如实说明）

- 单机 Docker Compose；**没有 HTTPS/反向代理、监控告警、自动备份**，内网试点可，直接公网不行。
- 工具以**服务进程权限**在 RiverAT 主机运行，**没有沙箱**：只安装可信工具。
- 工具可在 `tool.json` 里声明 `runtime.setup`，首次执行前安装依赖并缓存；离线环境把 wheel 放进包里。
- 不回收工具产物文件（只收 stdout JSON 与 stderr）；工具工作目录不会自动清理。
- 只支持本地执行（无远程 runner / WinRM）；CI webhook 只有配置占位。
- v1.0 遗留 API（`/api/v1/plans`、`/runs`、`/releases` 等）仍挂载但已冻结，页面已下线，不要在其上开发。
