"""本地执行目标：在开发机上真实起进程，模拟一台测试机。

它不是 mock —— 真的创建进程、真的写文件、真的收退出码与超时，
所以 transport 一致性与 runner 逻辑可以在这里被验证。
它无法模拟的部分（网络延迟、域认证、WinRM 报文分片）在
docs 里明确列出，并靠真机 spike 覆盖。

超时语义与远端对齐：超时会杀**整个进程树**（POSIX 进程组 / Windows
``taskkill /T``），而不是只杀直接子进程 —— 否则测试框架拉起的孙进程
会继续占着管道，把 1.5 秒的超时拖成几十秒。
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.transport.base import (
    DEFAULT_MAX_OUTPUT_BYTES,
    ExecResult,
    TargetInfo,
    TransportError,
    append_capped,
    elapsed_ms,
)


class LocalTransport:
    """在当前机器上执行命令，行为对齐远端实现（见 base.Transport）。"""

    name = "local"

    def __init__(
        self,
        *,
        default_timeout: float = 60.0,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self._default_timeout = default_timeout
        self._max_output_bytes = max_output_bytes

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
        max_output_bytes: int | None = None,
    ) -> ExecResult:
        merged_env = {**os.environ, **(env or {})}
        timeout = timeout or self._default_timeout
        cap = max_output_bytes or self._max_output_bytes
        start = time.monotonic()

        popen_kwargs: dict[str, object] = {
            "cwd": str(cwd) if cwd else None,
            "env": merged_env,
            "stdin": subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen([str(a) for a in argv], **popen_kwargs)  # type: ignore[arg-type]
        except FileNotFoundError as exc:
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

        out_parts: list[bytes] = []
        err_parts: list[bytes] = []
        flags = {"truncated": False}

        def drain(stream, sink: list[bytes]) -> None:
            buffer = bytearray()
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    if append_capped(buffer, chunk, cap):
                        flags["truncated"] = True
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
            sink.append(bytes(buffer))

        out_thread = threading.Thread(target=drain, args=(proc.stdout, out_parts), daemon=True)
        err_thread = threading.Thread(target=drain, args=(proc.stderr, err_parts), daemon=True)
        out_thread.start()
        err_thread.start()

        if stdin is not None:
            def feed() -> None:
                try:
                    assert proc.stdin is not None
                    proc.stdin.write(stdin)
                    proc.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

            threading.Thread(target=feed, daemon=True).start()

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        out_thread.join(timeout=2.0)
        err_thread.join(timeout=2.0)
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

        return ExecResult(
            exit_code=-1 if timed_out or proc.returncode is None else proc.returncode,
            stdout=out_parts[0] if out_parts else b"",
            stderr=err_parts[0] if err_parts else b"",
            duration_ms=elapsed_ms(start),
            timed_out=timed_out,
            truncated=bool(flags["truncated"]),
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """结束整个进程树：孙进程持有管道时，只杀直接子进程会拖死超时。"""

        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass

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
        """与远端实现保持同样的生命周期接口；本地无常驻连接。"""
