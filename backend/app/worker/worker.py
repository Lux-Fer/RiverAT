"""arq 任务定义与 WorkerSettings。"""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.services.runs import execute_run_by_id


async def execute_run_task(ctx, run_id: str) -> None:
    await execute_run_by_id(UUID(run_id))


class WorkerSettings:
    """`python -m app.worker` 的入口配置。"""

    functions: ClassVar[list] = [execute_run_task]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 3600
    keep_result = 3600
