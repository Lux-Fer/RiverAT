"""arq 任务定义与 WorkerSettings。"""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.runs import execute_run_by_id
from app.services.tasks import (
    execute_task_by_id,
    recover_stale_tasks,
    requeue_queued_tasks,
)


async def execute_run_task(ctx, run_id: str) -> None:
    await execute_run_by_id(UUID(run_id))


async def execute_task_task(ctx, task_id: str) -> None:
    await execute_task_by_id(UUID(task_id))


async def startup(ctx) -> None:
    """启动时回收僵尸任务，并补齐丢失的 queued job（D157）。"""

    async with get_sessionmaker()() as session:
        await recover_stale_tasks(session)
        await requeue_queued_tasks(session, ctx["redis"])
        await session.commit()


class WorkerSettings:
    """`python -m app.worker` 的入口配置。"""

    functions: ClassVar[list] = [execute_run_task, execute_task_task]
    on_startup = staticmethod(startup)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 3600
    keep_result = 3600
