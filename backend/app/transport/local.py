"""本地执行目标：在开发机上真实起进程，模拟一台测试机。

它不是 mock —— 真的创建进程、真的写文件、真的收退出码与超时，
所以 transport 一致性与 runner 逻辑可以在这里被验证。
它无法模拟的部分（网络延迟、域认证、WinRM 报文分片）在
docs 里明确列出，并靠真机 spike 覆盖。
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.transport.base import (
    ExecResult,
    TargetInfo,
    TransportError,
    elapsed_ms,
)


class LocalTransport:
    """在当前机器上执行命令，行为对齐远端实现（见 base.Transport）。"""

    name = "local"

    def __init__(self, *, default_timeout: float = 60.0) -> None:
        self._default_timeout = default_timeout

    # -- 探测 ---------------------------------------------------------

    def probe(self, *, timeout: float = 10.0) -> TargetInfo:
        if os.name == "nt":
            os_name = "windows"
        elif platform.system().lower() == "darwin":
            os_name = "darwin"
        else:
            os_name = "linux"
        return TargetInfo(
            os=os_name,
            arch=platform.machine().lower(),
            hostname=socket.gethostname(),
        )

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
        merged_env = {**os.environ, **(env or {})}
        timeout = timeout or self._default_timeout
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [str(a) for a in argv],
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                input=stdin,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecResult(
                exit_code=-1,
                stdout=exc.stdout or b"",
                stderr=exc.stderr or b"",
                duration_ms=elapsed_ms(start),
                timed_out=True,
            )
        except FileNotFoundError as exc:
            # 远端 shell 对"命令不存在"会返回非零；本地也归一成 127。
            return ExecResult(
                exit_code=127,
                stdout=b"",
                stderr=str(exc).encode("utf-8", "replace"),
                duration_ms=elapsed_ms(start),
            )
        except PermissionError as exc:
            return ExecResult(
                exit_code=126,
                stdout=b"",
                stderr=str(exc).encode("utf-8", "replace"),
                duration_ms=elapsed_ms(start),
            )
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or b"",
            stderr=proc.stderr or b"",
            duration_ms=elapsed_ms(start),
        )

    # -- 文件 ---------------------------------------------------------

    def put(self, local: Path, remote: str) -> None:
        src = Path(local)
        dst = Path(remote)
        if not src.is_file():
            raise TransportError(f"本地文件不存在: {src}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        except OSError as exc:
            raise TransportError(f"上传失败 {src} -> {dst}: {exc}") from exc

    def get(self, remote: str, local: Path) -> None:
        src = Path(remote)
        dst = Path(local)
        if not src.is_file():
            raise TransportError(f"远端文件不存在: {src}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        except OSError as exc:
            raise TransportError(f"下载失败 {src} -> {dst}: {exc}") from exc

    def close(self) -> None:
        """与远端实现保持同样的生命周期接口。"""
