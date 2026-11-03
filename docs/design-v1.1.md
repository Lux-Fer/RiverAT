# RiverAT v1.1 设计：AI 承接测试工作

> 状态：**M1–M4 全部实现并验证**（D101–D103），v1.1 闭环可演示。
> 依据：`docs/decisions-riverat-requirements.md` 第 9 节（D87–D96、Q24–Q28）与重写后的 `PRODUCT.md`。

## 1. 目标与非目标

**目标（v1.1）**：工程师配模型 → 注册产品 → 安装工具；用自然语言提工作；平台生成**任务草案**；人确认后调用工具执行；工作流（已完成 / 进行中 / 将进行）与结果可见。

**非目标（v1.1 明确不做）**：全自主执行、CI 实际收发、用例管理、脚本在线编辑、多租户、多机 runner、移动端。

## 2. 概念模型

```
Product（被测产品：地址 + CI 配置）
   │
   ├── Tool（团队写的测试能力：上传 → 审核 → 可用）
   │
   └── Task（一次工作：对话产生草案 → 人确认 → 执行 → 结果）
          └── TaskStep（一次工具调用：工具 + 参数 + 输出）
```

三层职责：

| 层 | 谁负责 | 平台做什么 |
|---|---|---|
| Product | 测试工程师注册 | 存地址与 CI 配置，执行时注入给工具 |
| Tool | 测试团队开发 | 按契约调用、记录输出、超时/失败处理 |
| Task | 对话产生 + 人确认 | 生成草案、入队、执行、汇总、展示 |

## 3. 数据模型（全部新增表，旧表冻结）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `llm_config` | base_url, api_key_enc, model, is_active, updated_by, updated_at | 单条生效配置；key 用 Fernet 加密 |
| `work_product` | code, name, base_url, description, ci_provider, ci_webhook_url, ci_secret_enc, status | v1.1 的"产品"；CI 字段只存不发 |
| `tool` | name, version, description, manifest JSONB, bundle_sha256, bundle_path, status(pending/approved/rejected), uploaded_by, approved_by | 上传即 pending，admin 审核后可用 |
| `task` | product_id, title, request_text, draft JSONB, status(draft/approved/running/passed/failed/cancelled), created_by, approved_by | 工作单元；`draft` 即"将进行" |
| `task_step` | task_id, seq, tool_id, args JSONB, status, output JSONB, exit_code, error, started_at, finished_at | 一次工具调用 |
| `chat_message` | task_id?, role, content | 对话记录，便于回看"为什么这么测" |

旧表（product / product_version / version_component / plan / run / run_step / release / knowledge_*）**保留不删**，作为 v1.0 历史数据；新功能不读它们。

## 4. 主流程

```
① 设置 → 模型配置（admin）：base_url + key + model → 保存（加密）→ 可选"测试连接"
② 产品 → 注册：code / name / base_url / CI 配置（占位）
③ 工具 → 上传 tar.gz（engineer）→ admin 审核 → approved
④ 助手 → 对话："测一下 DEMO-UI 的登录"
      → 后端组装：system prompt + approved tools 的 name/description/input_schema
                    + 产品上下文（code/name/base_url）
      → LLM（OpenAI 兼容 /chat/completions, tools=...）
      → 解析 tool_calls → 校验参数符合 input_schema → 保存 task(status=draft) + 草案
⑤ 助手页显示草案卡片：工具 / 参数 / 预计影响 → 用户点「确认执行」
      → task 入队（arq）
⑥ worker 逐步执行：取工具包 → 解压到临时目录 → 进程调用 → 解析 stdout JSON
      → 写 task_step.output；全部结束聚合 task 状态
⑦ 工作流页：将进行（draft）/ 进行中（approved/running）/ 已完成（终态）
```

失败与降级：

- 模型端点不可用 → 助手页提示，可"手动创建任务"（表单选工具 + 填参数）
- LLM 返回的参数不符合 schema → 草案标记"需人工修正"，允许编辑参数后确认
- 工具超时 → 该步 `error`，任务终态按最坏聚合（沿用 v1.0 的严重度顺序）

## 5. 工具契约 v2

包结构：

```
my-tool/
├── tool.json
├── main.py           # 入口
└── requirements.txt  # 可选，平台不自动安装（v1.1 由工具自带或主机预装）
```

`tool.json`：

```json
{
  "name": "login_smoke",
  "version": "1.0.0",
  "description": "对被测产品执行登录冒烟，返回用例级结果",
  "entrypoint": {"linux": ["python", "main.py"]},
  "input_schema": {
    "type": "object",
    "properties": {"base_url": {"type": "string"}, "user": {"type": "string"}},
    "required": ["base_url", "user"]
  },
  "output_schema": {
    "type": "object",
    "properties": {"cases": {"type": "array"}},
    "required": ["cases"]
  },
  "timeout_seconds": 600
}
```

调用协议：

- 工作目录 = 解压后的工具目录；平台注入环境变量 `RIVERAT_PRODUCT_CODE`、`RIVERAT_PRODUCT_BASE_URL`、`RIVERAT_TASK_ID`
- stdin：`{"args": {...}, "product": {...}}`
- stdout：JSON；`cases[]` 每项 `{case_id, status, duration_ms, reason}`
- 退出码 0 = 成功，非 0 = 失败；stderr 回收为证据
- 超时杀整个进程树（沿用 v1.0）

## 6. 接口与页面

**API**（`/api/v1`）：

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET/PUT | `/llm-config` | admin | 模型配置；GET 不回显 key |
| GET/POST | `/work-products` | user / engineer | 产品注册 |
| POST | `/tools` | engineer | 上传（multipart tar.gz） |
| GET | `/tools` | user | 列表（含状态） |
| POST | `/tools/{id}/approve`、`/reject` | admin | 审核 |
| POST | `/assistant/messages` | engineer | 对话 → 草案 |
| POST | `/tasks/{id}/approve` | engineer | 确认执行 |
| POST | `/tasks/{id}/cancel` | engineer | 取消（未开始/运行中尽力） |
| GET | `/tasks`、`/tasks/{id}` | user | 工作流与详情 |

**页面**：

| 页面 | 内容 |
|---|---|
| `/assistant` | 对话流 + 草案卡片（工具/参数/确认按钮）+ 手动创建入口 |
| `/tasks` | 三列工作流：将进行（draft）/ 进行中 / 已完成 |
| `/tasks/{id}` | 步骤、每步输出与用例结果、失败原因、审计 |
| `/products` | 注册表单 + 列表 |
| `/tools` | 上传、审核、启停、契约说明 |
| `/settings/llm` | 模型配置（admin） |

导航调整为：**助手 · 任务 · 产品 · 工具**（+ admin：用户 · 审计 · 设置）；旧页面（计划/看板/发布）移入"/legacy"或下线，待定（见 §9）。

## 7. 与 v1.0 的关系

| 资产 | 处置 |
|---|---|
| 用户 / 角色 / CSRF / 审计 | **复用** |
| 执行框架（arq 队列、超时、证据回收） | **复用**，调用对象从"插件进程"变为"工具进程" |
| run / run_step / 报告 | 冻结；v1.1 用 task / task_step，报告后续再迁移 |
| product / product_version / plan / release | 冻结；v1.1 用 work_product + task |
| 看板 / 发布页 / 计划页 | 从导航移除，路由保留（`/legacy/...`），不再投入 |

## 8. 里程碑（每步可独立验收）

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1 ✅ | 模型配置 + 设置页 + LLM 客户端 | 已实现：数据库配置优先、`.env` 兜底；"测试连接"真实调用 DeepSeek 成功（1.0s） |
| M2 ✅ | 产品注册 + 工具上传/审核 | 已实现：表单注册、tar.gz 上传、tool.json 校验、pending → approved |
| M3 ✅ | 对话 → 任务草案 | 已实现：`/assistant` 对话 → `task(draft)` + `task_step`；真模型（deepseek-flash）返回 tool_calls 并通过 schema 校验；参数缺失会给出警告 |
| M4 ✅ | 确认 → 队列 → 执行 → 结果 → 工作流 | 已实现并在容器里跑通：草案(`login_smoke`) → 确认 → arq worker → `passed` + 1 条用例 → `/tasks` 完成列表 |

## 9. 风险与未决

| 风险 | 说明 / 缓解 |
|---|---|
| LLM 输出不稳定 | schema 校验 + 允许人工改参数 + 保存原始响应供审计 |
| 云端 API 数据出境 | 客户可能不接受；同一接口支持本地端点，部署时切换 |
| Prompt 注入 | 工具描述来自已审核的上传者；产品名/地址由 admin 维护；仍需在系统提示里声明"只按工具契约调用" |
| 任务取消/超时/重试语义 | v1.1 只做"取消未开始的任务"+"单步超时"；重试留 v1.2 |
| 旧 UI 下线范围 | 需要产品决策：`/plans`、`/dashboard`、`/releases` 是保留入口还是彻底移除 |
| 工具运行时依赖 | v1.1 要求工具自带依赖或宿主预装，平台不自动 pip install（与"离线、可审计"一致） |
