"""SSH 执行目标（Linux 为主，v1 只保证 POSIX）。

与 LocalTransport 走同一套契约（见 base.Transport）：
非零退出码与超时都是返回值，不是异常。

注意：
* 主机密钥校验在 ``strict_host_key=False`` 时使用 AutoAddPolicy，
  只适合开发/内网首次接入；生产应打开严格校验并预置 known_hosts。
* 大输出场景下 stdout/stderr 是顺序读取的（先 stdout 后 stderr）。
  测试脚本把日志写在 stdout、错误写在 stderr 且都很大时，理论上可能
  阻塞；runner 约定单流输出即可规避，后续可换 select/线程读。
"""

from __future__ import annotations

import posixpath
import shlex
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import paramiko

from app.transport.base import (
    AuthError,
    ConnectError,
    ExecResult,
    TargetInfo,
    TransferError,
    TransportError,
    elapsed_ms,
)


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
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_filename = key_filename
        self._strict_host_key = strict_host_key
        self._connect_timeout = connect_timeout
        self._default_timeout = default_timeout
        self._client: paramiko.SSHClient | None = None

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

    def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        timeout = timeout or self._default_timeout
        client = self._connect()

        # 组合顺序：cd <cwd> && env K=V ... <argv>
        command = shlex.join([str(a) for a in argv])
        if env:
            assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            command = f"env {assignments} {command}"
        if cwd:
            command = f"cd {shlex.quote(str(cwd))} && {command}"

        start = time.monotonic()
        try:
            sin, sout, serr = client.exec_command(command, timeout=timeout)
            if stdin is not None:
                sin.write(stdin)
                sin.flush()
                sin.channel.shutdown_write()
            stdout = sout.read()
            stderr = serr.read()
            exit_code = sout.channel.recv_exit_status()
        except TimeoutError:
            return ExecResult(
                exit_code=-1,
                stdout=b"",
                stderr=b"",
                duration_ms=elapsed_ms(start),
                timed_out=True,
            )
        except paramiko.SSHException as exc:
            raise TransportError(f"SSH 执行失败: {exc}") from exc
        return ExecResult(
            exit_code=exit_code,
            stdout=stdout or b"",
            stderr=stderr or b"",
            duration_ms=elapsed_ms(start),
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
