"""执行派发：把 run 交给队列或就地执行。

生产用 arq 队列（Redis）；测试/单机回退到就地执行，接口形状一致。
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.runs import execute_run, get_run


class RunDispatcher(Protocol):
    async def dispatch(self, run_id: UUID, session: AsyncSession) -> None: ...


class InlineDispatcher:
    """就地执行：POST 返回前跑完（测试、单机、无 Redis 时的兜底）。"""

    async def dispatch(self, run_id: UUID, session: AsyncSession) -> None:
        run = await get_run(session, run_id)
        if run is None:
            return
        await execute_run(session, run)


class ArqDispatcher:
    """投递到 arq 队列，由 worker 进程消费。"""

    def __init__(self, pool) -> None:  # pool: arq.connections.ArqRedis
        self._pool = pool

    async def dispatch(self, run_id: UUID, session: AsyncSession) -> None:
        # session 参数只为协议一致；队列任务自己开会话
        await self._pool.enqueue_job("execute_run_task", str(run_id))


def get_dispatcher(request: Request) -> RunDispatcher:
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        dispatcher = InlineDispatcher()
        request.app.state.dispatcher = dispatcher
    return dispatcher
