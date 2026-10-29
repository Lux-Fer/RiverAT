"""Transport 一致性测试的夹具。

参数化规则：``local`` 永远参与；设置了 ``RIVERAT_TEST_SSH=host:port:user:password``
时再加上真实的 SSH 目标（用 docker-compose.test.yml 里的 sshd 即可）。
同一套断言必须在两者上都通过 —— 这是"本地模拟可信"的定义。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from app.transport.local import LocalTransport
from app.transport.ssh import SshTransport


def _targets() -> list[pytest.param]:
    params = [pytest.param("local", id="local")]
    spec = os.environ.get("RIVERAT_TEST_SSH")
    if spec:
        params.append(pytest.param(spec, id="ssh"))
    return params


@pytest.fixture(params=_targets())
def transport(request):
    value = request.param
    if value == "local":
        impl = LocalTransport()
        yield impl
        impl.close()
        return

    host, port, user, password = value.split(":", 3)
    impl = SshTransport(host=host, username=user, port=int(port), password=password)
    yield impl
    impl.close()


@pytest.fixture
def target_os(transport) -> str:
    return transport.probe().os


@pytest.fixture
def ps_shell() -> str:
    """Windows 上优先 PowerShell 7（默认 UTF-8 输出）。"""

    return "pwsh" if shutil.which("pwsh") else "powershell"


@pytest.fixture
def workdir(transport, target_os):
    """目标机上一个全新的临时目录，测试结束清理。"""

    name = f"riverat-contract-{uuid.uuid4().hex}"
    path = (
        str(Path(tempfile.gettempdir()) / name)
        if target_os == "windows"
        else f"/tmp/{name}"
    )

    if isinstance(transport, LocalTransport):
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        yield path
        shutil.rmtree(directory, ignore_errors=True)
        return

    transport.exec(["mkdir", "-p", path])
    yield path
    transport.exec(["rm", "-rf", path])
