"""执行目标（transport）契约。

为什么要有这份契约：本地实现只是"远端测试机"的**模拟**。只有同一套
一致性测试（tests/transport）在每一个实现上都通过，本地的通过才是有意义的；
否则它只是一个会撒谎的 mock。

契约规则
--------
* 非零退出码是**数据**，不是异常：exec() 返回它。
* 超时同样是数据：``ExecResult.timed_out=True``、``exit_code=-1``。
* 只有连接 / 认证 / 传输失败才抛 ``TransportError``。
* stdout/stderr 保持 bytes，要不要解码由调用方决定。
* ``put()`` 负责在目标机上创建缺失的父目录。

调用方异步上下文里请用 ``asyncio.to_thread(transport.exec, ...)``：
实现本身是同步阻塞的（paramiko / subprocess 都是），把线程留给 IO。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class TransportError(RuntimeError):
    """Transport 层失败基类。"""


class ConnectError(TransportError):
    """连不上目标机（网络、端口、协议握手失败）。"""


class AuthError(TransportError):
    """连上了但认证失败。"""


class TransferError(TransportError):
    """文件上传 / 下载失败。"""


@dataclass(frozen=True, slots=True)
class TargetInfo:
    """目标机自报的身份，用于选择引导脚本与产物布局。"""

    os: str  # "linux" | "windows" | "darwin"
    arch: str  # "x86_64" | "aarch64" | "amd64" ...
    hostname: str


@dataclass(frozen=True, slots=True)
class ExecResult:
    """一次远端执行的结果。"""

    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", "replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", "replace")


class Transport(Protocol):
    """一个可执行目标。实现必须通过 tests/transport 的一致性测试。"""

    name: str

    def probe(self, *, timeout: float = 10.0) -> TargetInfo:
        """探测目标机身份；连不上时抛 ``ConnectError``。"""

    def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        timeout: float = 60.0,
    ) -> ExecResult:
        """执行一条命令（argv 形式，不经过 shell 拼接）。

        非零退出码与超时都通过返回值表达，不抛异常；
        连接 / 认证失败抛对应 ``TransportError`` 子类。
        """

    def put(self, local: Path, remote: str) -> None:
        """上传文件，自动创建父目录。"""

    def get(self, remote: str, local: Path) -> None:
        """下载文件，自动创建本地父目录。"""


def elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
