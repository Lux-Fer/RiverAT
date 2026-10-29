"""数据层测试夹具：真库（PostgreSQL）+ 真迁移。

不用 SQLite 代替 PG —— 测的就是 PG 的类型与约束（UUID / JSONB / 唯一约束），
换一个数据库跑，等于自己考自己。
"""

from __future__ import annotations

import asyncio

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

TEST_DATABASE = "riverat_test"


async def _admin_execute(*statements: str) -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
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
    """建一个干净的测试库，跑真实迁移，结束后删除。"""

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
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine):
    yield
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE run_step, run, plan, version_component, "
                "product_version, product RESTART IDENTITY CASCADE"
            )
        )
