"""任务派发（M4）：确认后交给 arq 队列；测试/单机就地执行。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tasks import execute_task, get_task


class TaskDispatcher(Protocol):
    async def dispatch(self, task_id: UUID, session: AsyncSession) -> None: ...


class InlineTaskDispatcher:
    async def dispatch(self, task_id: UUID, session: AsyncSession) -> None:
        task = await get_task(session, task_id)
        if task is None:
            return
        await execute_task(session, task)


class ArqTaskDispatcher:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def dispatch(self, task_id: UUID, session: AsyncSession) -> None:
        await self._pool.enqueue_job("execute_task_task", str(task_id))


def get_task_dispatcher(request: Request) -> TaskDispatcher:
    dispatcher = getattr(request.app.state, "task_dispatcher", None)
    if dispatcher is None:
        dispatcher = InlineTaskDispatcher()
        request.app.state.task_dispatcher = dispatcher
    return dispatcher
