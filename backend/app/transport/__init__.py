"""执行目标层：本地 / SSH /（后续）WinRM 共用一份契约。"""

from app.transport.base import (
    AuthError,
    ConnectError,
    ExecResult,
    TargetInfo,
    TransferError,
    Transport,
    TransportError,
)
from app.transport.local import LocalTransport
from app.transport.ssh import SshTransport

__all__ = [
    "AuthError",
    "ConnectError",
    "ExecResult",
    "LocalTransport",
    "SshTransport",
    "TargetInfo",
    "TransferError",
    "Transport",
    "TransportError",
]
