"""SSH 执行目标（Linux 为主，v1 只保证 POSIX）。

与 LocalTransport 走同一套契约（见 base.Transport）：
非零退出码与超时都是返回值，不是异常。

超时语义：优先用远端 ``timeout -k 5 <t>s`` 包一层，保证通道关闭时
远端进程（含其子进程）真的退出；退出码 124 / 137 映射为超时。
目标机没有 ``timeout`` 命令时退化为"本地等 deadline 后关通道"，
此时远端进程可能残留 —— 这一点写进 docs/transport-contract.md。

注意：
* 主机密钥校验在 ``strict_host_key=False`` 时使用 AutoAddPolicy，
  只适合开发/内网首次接入；生产应打开严格校验并预置 known_hosts。
* stdout/stderr 用增量读取（每块 64 KiB）并受 ``max_output_bytes`` 限制，
  超出部分丢弃、置 ``truncated``；不会把整份日志堆进内存。
* 连接在命令结束前中断（拿不到退出码）时抛 ``ConnectError``，而不是返回 -1。
"""

from __future__ import annotations

import posixpath
import shlex
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import paramiko

from app.transport.base import (
    DEFAULT_MAX_OUTPUT_BYTES,
    AuthError,
    ConnectError,
    ExecResult,
    TargetInfo,
    TransferError,
    append_capped,
    elapsed_ms,
)

# GNU coreutils / busybox `timeout` 的退出码：超时 124，KILL 后 137。
_TIMEOUT_EXIT_CODES = frozenset({124, 137})
_TIMEOUT_GRACE_SECONDS = 5.0


class SshTransport:
    name = "ssh"

    def __init__(
        self,
        host: str,
        username: str,
        *,
        port: int = 22,
        password: str | None = None,
        key_filename: str | None = None,
        strict_host_key: bool = False,
        connect_timeout: float = 10.0,
        default_timeout: float = 60.0,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_filename = key_filename
        self._strict_host_key = strict_host_key
        self._connect_timeout = connect_timeout
        self._default_timeout = default_timeout
        self._max_output_bytes = max_output_bytes
        self._client: paramiko.SSHClient | None = None
        self._has_timeout_cmd: bool | None = None

    # -- 连接 ---------------------------------------------------------

    def _connect(self) -> paramiko.SSHClient:
        if self._client is not None:
            return self._client
        client = paramiko.SSHClient()
        if self._strict_host_key:
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                key_filename=self._key_filename,
                timeout=self._connect_timeout,
                banner_timeout=self._connect_timeout,
                auth_timeout=self._connect_timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException as exc:
            client.close()
            raise AuthError(f"SSH 认证失败 {self._username}@{self._host}: {exc}") from exc
        except (paramiko.SSHException, OSError) as exc:
            client.close()
            raise ConnectError(f"SSH 连接失败 {self._host}:{self._port}: {exc}") from exc
        self._client = client
        return client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- 探测 ---------------------------------------------------------

    def probe(self, *, timeout: float = 10.0) -> TargetInfo:
        uname = self.exec(["uname", "-s"], timeout=timeout)
        if uname.exit_code == 0:
            os_name = uname.stdout_text.strip().lower()
            machine = self.exec(["uname", "-m"], timeout=timeout).stdout_text.strip().lower()
        else:  # Windows OpenSSH 默认 shell 下没有 uname
            ps = self.exec(
                ["powershell", "-NoProfile", "-Command", "$env:OS"],
                timeout=timeout,
            )
            os_name = "windows" if "windows" in ps.stdout_text.lower() else "unknown"
            machine = self.exec(
                ["powershell", "-NoProfile", "-Command", "$env:PROCESSOR_ARCHITECTURE"],
                timeout=timeout,
            ).stdout_text.strip().lower()
        hostname = self.exec(["hostname"], timeout=timeout).stdout_text.strip()
        return TargetInfo(os=os_name or "unknown", arch=machine or "unknown", hostname=hostname)

    # -- 执行 ---------------------------------------------------------

    @staticmethod
    def _compose(
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
    ) -> str:
        command = shlex.join([str(a) for a in argv])
        if env:
            assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            command = f"env {assignments} {command}"
        if cwd:
            command = f"cd {shlex.quote(str(cwd))} && {command}"
        return command

    def _exec_raw(self, command: str, *, timeout: float = 10.0) -> bytes:
        """内部使用：跑一条短命令，不走超时包装，避免递归探测。"""

        client = self._connect()
        chan = client.get_transport().open_session(timeout=timeout)
        try:
            chan.settimeout(timeout)
            chan.exec_command(command)
            return chan.makefile("rb").read() or b""
        finally:
            chan.close()

    def _supports_timeout_cmd(self) -> bool:
        if self._has_timeout_cmd is None:
            try:
                probe = self._exec_raw("command -v timeout 2>/dev/null", timeout=10)
                self._has_timeout_cmd = bool(probe.strip())
            except (TimeoutError, paramiko.SSHException, OSError):
                self._has_timeout_cmd = False
        return self._has_timeout_cmd

    def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        timeout: float | None = None,
        max_output_bytes: int | None = None,
    ) -> ExecResult:
        timeout = timeout or self._default_timeout
        cap = max_output_bytes or self._max_output_bytes
        client = self._connect()

        command = self._compose(argv, cwd, env)
        if self._supports_timeout_cmd():
            command = shlex.join(
                ["timeout", "-k", "5", f"{int(timeout)}s", "sh", "-c", command]
            )

        start = time.monotonic()
        deadline = start + timeout + _TIMEOUT_GRACE_SECONDS
        chan = client.get_transport().open_session(timeout=timeout)
        stdout = bytearray()
        stderr = bytearray()
        truncated = False
        timed_out = False
        abnormal = False
        exit_code: int | None = None

        try:
            chan.settimeout(timeout + _TIMEOUT_GRACE_SECONDS)
            chan.exec_command(command)
            if stdin is not None:
                chan.sendall(stdin)
                chan.shutdown_write()

            while True:
                if chan.recv_ready():
                    truncated = append_capped(stdout, chan.recv(65536), cap) or truncated
                    continue
                if chan.recv_stderr_ready():
                    truncated = append_capped(stderr, chan.recv_stderr(65536), cap) or truncated
                    continue
                if chan.exit_status_ready():
                    break
                if chan.closed:
                    abnormal = True
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                time.sleep(0.01)

            if not timed_out and not abnormal:
                exit_code = chan.recv_exit_status()
        except TimeoutError:
            timed_out = True
        except (EOFError, OSError, paramiko.SSHException) as exc:
            raise ConnectError(f"SSH 连接异常中断: {exc}") from exc
        finally:
            chan.close()

        if timed_out:
            return ExecResult(
                exit_code=-1,
                stdout=bytes(stdout),
                stderr=bytes(stderr),
                duration_ms=elapsed_ms(start),
                timed_out=True,
                truncated=truncated,
            )

        if abnormal or exit_code is None:
            raise ConnectError("SSH 连接在命令结束前中断，未收到退出码")

        if exit_code in _TIMEOUT_EXIT_CODES:
            return ExecResult(
                exit_code=-1,
                stdout=bytes(stdout),
                stderr=bytes(stderr),
                duration_ms=elapsed_ms(start),
                timed_out=True,
                truncated=truncated,
            )

        if exit_code < 0:
            raise ConnectError(f"SSH 未返回有效退出码（{exit_code}）")

        return ExecResult(
            exit_code=exit_code,
            stdout=bytes(stdout),
            stderr=bytes(stderr),
            duration_ms=elapsed_ms(start),
            truncated=truncated,
        )

    # -- 文件 ---------------------------------------------------------

    def _sftp(self) -> paramiko.SFTPClient:
        try:
            return self._connect().open_sftp()
        except (paramiko.SSHException, OSError) as exc:
            raise TransferError(f"SFTP 连接失败: {exc}") from exc

    @staticmethod
    def _ensure_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
        if not remote_dir or remote_dir == "/":
            return
        current = "/" if remote_dir.startswith("/") else ""
        for token in remote_dir.strip("/").split("/"):
            current = posixpath.join(current, token) if current else token
            try:
                sftp.stat(current)
            except FileNotFoundError:
                try:
                    sftp.mkdir(current)
                except OSError as exc:
                    raise TransferError(f"创建远端目录失败 {current}: {exc}") from exc

    def put(self, local: Path, remote: str) -> None:
        src = Path(local)
        if not src.is_file():
            raise TransferError(f"本地文件不存在: {src}")
        sftp = self._sftp()
        try:
            self._ensure_remote_dir(sftp, posixpath.dirname(remote))
            sftp.put(str(src), remote)
        except OSError as exc:
            raise TransferError(f"上传失败 {src} -> {remote}: {exc}") from exc
        finally:
            sftp.close()

    def get(self, remote: str, local: Path) -> None:
        dst = Path(local)
        sftp = self._sftp()
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote, str(dst))
        except OSError as exc:
            raise TransferError(f"下载失败 {remote} -> {dst}: {exc}") from exc
        finally:
            sftp.close()
