# 工具契约 v2

> 一句话：**一个 `tar.gz` + 一份 `tool.json`**。平台负责解压、调用、收结果；
> 工具内部怎么写、用什么框架，平台不管（D99 / D108）。

## 1. 包结构

```
login-smoke/
├── tool.json          # 必需：清单
├── main.py            # 入口（示例）
└── requirements.txt   # 可选；平台不会自动安装（见 §6）
```

打包成 `.tar.gz` 上传。包根目录可以直接是这些文件，也可以多一层目录（平台会自动识别）。

## 2. tool.json

```json
{
  "name": "login_smoke",
  "version": "1.0.0",
  "description": "对被测产品执行登录冒烟，返回用例级结果",
  "risk": "read_only",
  "entrypoint": {
    "linux":   ["python", "main.py"],
    "windows": ["python", "main.py"]
  },
  "input_schema": {
    "type": "object",
    "properties": {
      "base_url": {"type": "string"},
      "user": {"type": "string"}
    },
    "required": ["base_url", "user"]
  },
  "output_schema": {
    "type": "object",
    "properties": {"cases": {"type": "array"}},
    "required": ["cases"]
  },
  "timeout_seconds": 600,
  "runtime": {
    "setup": ["pip", "install", "-r", "requirements.txt"],
    "setup_timeout_seconds": 300
  }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` / `version` | 是 | 唯一键；同名同版本不能重复上传 |
| `entrypoint` | 是 | `{系统: [argv...]}`；按目标系统取，没有则回退 `linux` |
| `input_schema` | 是 | JSON Schema，`type` 必须是 `object`；平台据此校验参数与生成表单 |
| `output_schema` | 否 | 只作文档用途，平台不强制校验 |
| `description` | 否 | 会直接给模型看，写清楚"做什么、怎么用" |
| `risk` | 否 | `read_only` / `write` / `dangerous`，默认 `write`；只有全部步骤显式 `read_only` 才可被自动确认 |
| `timeout_seconds` | 否 | 默认 600；到点终止**整个进程树** |
| `runtime.setup` | 否 | 依赖安装命令（argv 数组）；每份包**首次执行前跑一次**，成功后不再跑 |
| `runtime.setup_timeout_seconds` | 否 | 默认 300；安装超时同样终止进程树 |

## 3. 调用协议

平台把工具解压到**持久目录**（`backend/var/tools/work/<sha256>/`），以包根为工作目录启动入口：

**stdin**（平台 → 工具，一行 JSON）：

```json
{
  "args": {"base_url": "http://10.0.0.6:8080", "user": "tester"},
  "product": {"code": "DEMO", "name": "演示产品", "base_url": "http://10.0.0.6:8080"}
}
```

`args` 是任务步骤里保存的参数（人可以在草案阶段改）；`product` 可能为 `null`（手动创建时没选产品）。

**环境变量**（平台注入）：

| 变量 | 说明 |
|---|---|
| `RIVERAT_TASK_ID` | 任务 UUID |
| `RIVERAT_TOOL_NAME` | 工具名 |
| `RIVERAT_PRODUCT_CODE` / `RIVERAT_PRODUCT_BASE_URL` | 被测产品（没有则为空串） |

**stdout**（工具 → 平台，必须是 **JSON 对象**）：

```json
{
  "cases": [
    {"case_id": "login-001", "status": "passed", "duration_ms": 12},
    {"case_id": "login-002", "status": "failed", "duration_ms": 30, "reason": "expected 200 got 500"}
  ]
}
```

- `cases[]` 是平台展示与统计的唯一来源；字段：`case_id`、`status`（`passed/failed/skipped/error`）、`duration_ms`、`reason`。
- 可以返回顶层 `{"status": "skipped", "reason": "环境不可用"}` 覆盖按退出码的判定。
- **退出码 0 = 成功**；非 0 = `failed`；超时 = `error`；stdout 不是 JSON 对象 = `error`。
- stderr 会被截取（最多 64 KiB）存进证据，便于排障。

## 4. 最小示例（Python）

```python
import json
import sys

job = json.loads(sys.stdin.read() or "{}")
args = job.get("args", {})
base_url = args["base_url"]

# 这里放真实测试逻辑……
cases = [{"case_id": "login-001", "status": "passed", "duration_ms": 12}]
print(json.dumps({"cases": cases}, ensure_ascii=False))
```

`tool.json` 里 `entrypoint.linux = ["python", "main.py"]`。

## 5. 依赖安装（runtime.setup）

```json
"runtime": {
  "setup": ["pip", "install", "-r", "requirements.txt"],
  "setup_timeout_seconds": 300
}
```

- 工具第一次被执行时，平台先在**持久工作目录**里跑 `setup`；成功后写 `.riverat-setup-done`，之后不再跑。
- `setup` 以 argv 数组执行（不经过 shell），stdin 不传入，stdout/stderr 被截取；非 0 退出或超时 → 该步骤 `error`，错误信息带 stderr 尾部。
- 依赖装在工具自己的目录里（例如 `pip install --target .` 或 venv），不会污染平台环境。
- 修改依赖 = 上传一个新版本（新 sha256 → 新目录 → 重新安装）；旧目录不会自动删除，见 §7。
- 离线环境：把 wheel 放进包里，`setup` 写 `["pip", "install", "--no-index", "--find-links", "wheels", "-r", "requirements.txt"]`。
- **安全边界**：`setup` 与入口一样以服务进程权限运行，admin 审核工具即视为批准这段代码；只上传可信包。

## 6. 审核与生命周期

```
engineer 上传 → pending → admin「工具」页点「通过」→ approved → 可在任务里调用
                              └「拒绝」→ rejected（不能再被选中）
```

- 上传即校验：`tool.json` 字段、`input_schema` 形状、包大小（≤ 50 MiB）、同名同版本去重。
- 工具包按内容寻址存放：`backend/var/tools/<sha256>.tar.gz`。
- 已被引用的工具不会因为新版本上传而被替换；同名取**创建时间最新且 approved** 的那个。

## 7. 限制与清理（v1.1 如实说明）

- **没有沙箱**：工具与 `setup` 都以 RiverAT 服务进程的权限运行，能读写主机文件。只安装可信工具。
- **工作目录不会自动清理**：每份包解压并装好依赖后长期保留在 `backend/var/tools/work/<sha256>/`；
  占空间时手动删（删掉后下次执行会重新解压/安装），或按 `sha256` 只删旧版本。
- **不回收产物**：平台只收 stdout JSON 与 stderr，不抓 `artifacts/`、截图、日志文件（v1.0 的产物回收没有带过来）。
- **只在本机执行**：没有远程 runner，工具自己连被测产品（网络可达性由部署方保证）。
- **失败不重试**：单步失败就记失败，不自动重跑；需要重跑请用任务的「重跑」生成新草案。
- **超时杀进程树**：POSIX 用进程组、Windows 用 `taskkill /T`；工具再 fork 的守护进程不保证清理。
