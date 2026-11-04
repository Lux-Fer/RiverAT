# Transport 契约与"本地模拟"的可信度

> **v1.0 遗留文档**：v1.1 的页面与任务执行已改为「平台本机执行工具进程」，不再使用这里的
> SSH/本地 transport；对应代码仅服务于冻结的 v1.0 API（`/api/v1/runs` 等）。工具契约见
> [tool-contract.md](tool-contract.md)。

> 目标：在没有测试机的情况下，本地跑通的东西**不能是自欺欺人**。
> 本文定义"什么算准确"、"什么算权威"、"本地模拟不了什么"。

## 1. 三层保证

| 层 | 内容 | 位置 |
|---|---|---|
| **契约** | 一次远端执行的语义：非零退出码是数据、超时是数据、只有连接/认证/传输失败才抛异常、`put` 自动建父目录 | `app/transport/base.py` |
| **一致性测试** | 同一套断言跑**每一个**实现（local / ssh / 将来的 winrm） | `tests/transport/test_contract.py` |
| **真机放行** | 契约测试在真实测试机上跑通，才算"能上客户环境" | 真机 spike 检查表（见第 5 节） |

**判据**：本地通过 ≠ 真机通过。本地通过只证明"逻辑与契约正确"；真机通过才证明"协议与权限正确"。

## 2. 当前状态

- `LocalTransport`：17 项断言通过（本机 Windows）；面向对方的 3 项用例自动跳过。
- `SshTransport`：同一套断言通过 —— 对手是真实 sshd（`docker-compose.test.yml`，真实 SSH 协议、SFTP、shell）。
- 同一套断言、两个实现、同一份结果：**34 passed / 3 skipped**。

```powershell
# 仅本地
uv run pytest tests/transport -q

# 加上真实 SSH 目标
docker compose -f docker-compose.test.yml up -d
$env:RIVERAT_TEST_SSH = "127.0.0.1:2222:riverat:riverat"
uv run pytest tests/transport -q
```

## 3. LocalTransport 真实模拟了什么

不是 mock：真的创建进程、真的落盘、真的计时。

| 行为 | 验证方式 |
|---|---|
| 退出码（含非零、含命令不存在→127） | `test_nonzero_exit_*` / `test_missing_command_*` |
| 超时立刻返回，且**杀掉整个进程树**（孙进程拖不住） | `test_timeout_is_reported_not_raised` / `test_timeout_kills_child_processes` |
| 远端超时后不留进程 | `test_ssh_timeout_leaves_no_remote_process` |
| 连接中断抛错，而不是伪装成 `exit_code=-1` | `test_connection_drop_raises` |
| 输出超过上限被截断并标记 | `test_output_is_capped` |
| 中文 + 空格的路径可写可读 | `test_paths_with_spaces_and_unicode` |
| stdout / stderr 分离 | `test_stderr_is_separate_from_stdout` |
| cwd、环境变量、stdin | `test_cwd_*` / `test_env_*` / `test_stdin_*` |
| 中文 + 重音 + 符号的编码往返 | `test_unicode_survives_roundtrip` |
| 200 KB 输出不阻塞（管道缓冲区） | `test_large_output_does_not_deadlock` |
| 二进制文件上传/下载与父目录创建 | `test_file_roundtrip_creates_parents` |

### 3.1 三条硬语义（2026-10-29 补，全部有实测证据）

| 语义 | 修之前 | 现在 |
|---|---|---|
| **超时必须结束执行** | 本地 `timeout=1.5s` 被孙进程拖到 **29.3 秒**；SSH 超时后容器里 `sleep 30` 仍在跑 | 本地 `killpg` / `taskkill /T` 杀进程树；SSH 用 `timeout -k 5` 包一层，退出码 124/137 判为超时 |
| **断连必须抛错** | 连接中断返回 `exit_code=-1, timed_out=False`，看起来像"命令正常结束" | 未收到退出码即抛 `ConnectError` |
| **输出必须封顶** | 全量进内存（paramiko 自身缓冲 + 整体 `read()`） | 每路 8 MiB，超出截断并置 `truncated` |

另外更正一条我之前写错的结论：SSH 下"先读完 stdout 再读 stderr"**不会**死锁（实测 1 MB stderr 14 ms 读完），真实风险是内存没有上限。

顺带说明：这套测试在第一次跑 SSH 时就抓到一个真实缺陷 —— `env` 前缀被 `&&` 拆成了两条命令，导致环境变量根本没传进去。这就是契约测试的价值，本地"看起来能跑"是抓不到它的。

## 4. LocalTransport **不能**模拟什么（诚实清单）

这些必须在真机 spike 里验证，不能靠本地推断：

1. **网络行为**：延迟、丢包、半开连接、断线重连、代理。
2. **认证模型**：域账号（NTLM/Kerberos）、WinRM 的权限与 UAC 限制、SSH 的 known_hosts 策略。
3. **WinRM 协议细节**：报文分片（默认 ~150 KB 上限）、传输限速、大文件回传的吞吐。
4. **目标机环境差异**：Python 版本/缺失、杀软拦截、路径含空格或中文、磁盘权限、编码（GBK 控制台）。
5. **并发与资源竞争**：多任务同机、端口/设备/license 抢占。
6. **系统级差异**：Linux 无 `sh`、Windows 无 `unzip`、PowerShell 执行策略（ExecutionPolicy）。

## 5. 真机 spike 检查表（放行条件）

在一台真实 Windows 和一台真实 Linux 上，逐项打勾才算通过：

- [ ] 用目标账号建立会话（Windows：WinRM 或 OpenSSH；Linux：SSH）
- [ ] 执行一条命令并拿到退出码
- [ ] 传入 10 MB 文件，校验哈希
- [ ] 取回 10 MB 文件，测吞吐（决定产物通道要不要换共享盘）
- [ ] 命令超时后能杀干净（无残留进程）
- [ ] 中文路径 / 带空格路径可执行
- [ ] 断线重连：执行中拔网线，任务不悬挂、能给出明确失败态
- [ ] 目标机没有 Python 时，便携运行时能起来（若采用）

任何一项失败：先改 transport 契约或执行模型，**不要继续写业务代码**。

## 6. 已知限制（当前版本）

| 限制 | 影响 | 处理 |
|---|---|---|
| 目标机没有 `timeout` 命令 | 超时只能关通道，远端进程可能残留 | 探测后降级，并在目标机能力里标记"弱超时保证" |
| `timeout` 的 137 也按超时处理 | 被外部 KILL 的命令会被判超时 | 原始退出码仍写进证据，可复查 |
| SSH 未做断线重连 | 连接断了任务直接失败 | v1.1 加重连与重试 |
| 输出上限 8 MiB/路 | 超大日志被截断 | 需要全量日志时落文件、走产物通道 |
| `strict_host_key=False` 用 AutoAddPolicy | 只适合首次接入 | 生产打开严格校验并预置 known_hosts |
| SSH 到 Windows 未支持 | Windows 走 WinRM 或 OpenSSH 另行实现 | 等真机 |
| WinRM 实现未写 | 无 Windows 传输 | 真机到位后补 `WinRmTransport`，跑同一套契约 |
| 本地模拟不含 WinRM 报文分片 | 大文件回传速度无法预估 | 真机 spike 第 4 项 |
