"""所有测试共用的夹具：执行目标（local/ssh）与数据库（真 PG + 真迁移）。

* transport：``local`` 永远参与；``RIVERAT_TEST_SSH=host:port:user:password``
  时再加上真实 SSH 目标。
* database：每次会话建一个临时库 ``riverat_test``，跑真实迁移，用完即删；
  每个用例开始前 TRUNCATE，互不影响。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import BASE_DIR, get_settings
from app.transport.local import LocalTransport
from app.transport.ssh import SshTransport

TEST_DATABASE = "riverat_test"


# -- transport --------------------------------------------------------


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


# -- database ---------------------------------------------------------


async def _admin_execute(*statements: str) -> None:
    url = make_url(get_settings().database_url)
    connection = await asyncpg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        for statement in statements:
            await connection.execute(statement)
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    """建干净的测试库 → 跑真实迁移 → 结束时删除。"""

    url = make_url(get_settings().database_url)
    asyncio.run(
        _admin_execute(
            f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)',
            f'CREATE DATABASE "{TEST_DATABASE}"',
        )
    )

    test_url = url.set(database=TEST_DATABASE).render_as_string(hide_password=False)
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_url)
    command.upgrade(config, "head")

    yield test_url

    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)'))


@pytest_asyncio.fixture
async def engine(database_url):
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(
            text(
                "TRUNCATE task_step, chat_message, task, llm_config, tool, work_product, audit_log, "
                "knowledge_feedback, knowledge_item_source, knowledge_item, knowledge_event, "
                'run_step, run, plan, version_component, product_version, product, host, "user" RESTART IDENTITY CASCADE'
            )
        )
        await session.commit()
        yield session
        await session.rollback()


@pytest.fixture(scope="session", autouse=True)
def disable_agent_recovery():
    """测试默认不调用真实模型；恢复测试自己打开开关并 mock LLM。"""

    from app.core.config import get_settings

    get_settings().agent_recovery_enabled = False
    get_settings().agent_step_review_enabled = False
    get_settings().agent_step_repair_enabled = False


@pytest.fixture(scope="session", autouse=True)
def clean_uploaded_tool_bundles():
    """测试上传的工具包只属于测试库；session 结束删除新增文件，避免 var/tools 堆积。"""

    root = Path(get_settings().tools_root)
    before = {path.name for path in root.glob("*.tar.gz")} if root.exists() else set()
    yield
    if root.exists():
        for path in root.glob("*.tar.gz"):
            if path.name not in before:
                path.unlink(missing_ok=True)
