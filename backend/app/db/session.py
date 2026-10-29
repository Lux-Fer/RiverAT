"""异步引擎与会话工厂。

模块级引擎按需创建（第一次用到时才连），测试可以直接用
``build_engine(url)`` 指向临时库，不碰全局状态。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None


def build_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        url or get_settings().database_url,
        pool_pre_ping=True,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return build_sessionmaker(get_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求结束时关闭会话。"""

    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """应用关闭 / 测试结束时释放连接池。"""

    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
