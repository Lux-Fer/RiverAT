# 插件契约（v0）

> 一句话：**一个 tar.gz + 一份 plugin.json**，平台负责送过去、跑起来、把证据收回来；
> 用例怎么判、测什么，插件自己说了算（D2/D3）。

## 1. 包结构

```
my-plugin/
├── plugin.json        # 必需：清单
├── main.sh            # Linux/macOS 入口（示例）
├── main.ps1           # Windows 入口（示例）
└── ...                # 你的代码、配置、数据
```

打包成 `.tar.gz` 后由平台上传；平台记录包的 `sha256` 作为证据的一部分。

## 2. plugin.json

```json
{
  "name": "smoke-check",
  "version": "1.2.0",
  "timeout_seconds": 300,
  "description": "可选说明",
  "capabilities": ["http", "device:usb"],
  "entrypoints": {
    "linux":   ["sh", "main.sh"],
    "windows": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "main.ps1"]
  }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` / `version` | 是 | 写进执行记录，用于追溯 |
| `entrypoints` | 是 | 按目标系统声明 argv；没有对应系统时回退到 `linux` |
| `timeout_seconds` | 否 | 默认 60；单次执行的上限，超时会被**杀掉整个进程树** |
| `capabilities` | 否 | 能力标签，将来用于"这套计划缺哪个能力"的缺口分析 |
| `description` | 否 | 给人看的一句话 |

## 3. 运行时约定

- 工作目录 = 包解压后的目录（插件根）。
- **唯一参数**：`argv[1]` 是 `job.json` 的路径，里面是这次步骤的输入（`step_id`、参数等）。
- 输出：**退出码**决定成败；需要更细的结论时写 `plugin_result.json`；产物放 `artifacts/`。

`job.json` 示例：

```json
{"step_id": "login-flow", "args": {"env": "staging"}, "timeout_seconds": 300}
```

`plugin_result.json`（可选，覆盖退出码判定）：

```json
{"status": "skipped", "reason": "测试机没有 USB 设备"}
```

`status` 只接受 `passed` / `failed` / `skipped` / `error`；不写就按退出码判：
`0 → passed`，非 0 → `failed`，超时 → `error`。

## 4. 平台保证与限制

| 平台保证 | 说明 |
|---|---|
| 独立工作目录 | 每个步骤一个目录，互不干扰；执行完自动清理（排障时可用 `keep_remote=True` 保留） |
| 超时真结束 | 到点杀整个进程树；SSH 用 `timeout -k 5` 包裹，退出码 124/137 判为超时 |
| 输出有上限 | stdout / stderr 各 8 MiB，超出截断并标记 `truncated` |
| 证据回收 | 日志、`plugin_result.json`、`artifacts/` 顶层文件；不支持子目录 |
| 不干预 | 平台不改你的代码、不重写断言、不猜结果 |

## 5. 踩过的坑（写插件的人会遇到）

1. **`.sh` 必须是 LF 换行**。在 Windows 上写 `exit 7\r` 会得到
   `Illegal number: 7`、`sleep 30\r` 会得到 `invalid number` —— 症状是"脚本莫名其妙退出 2"。
2. **`artifacts/` 只收顶层文件**，子目录不会被打包回收。
3. 文件名不要带 `/`、`\`、`..`（平台会跳过这类条目）。
4. Windows 上平台用 `Start-Process` 重定向，保证子进程输出按原始字节落盘
   （避免 PowerShell 5.1 的 UTF-16 重定向把日志变成乱码）。
5. 平台给的是**一次性**执行环境：不要假设上一轮留下的文件还在。
