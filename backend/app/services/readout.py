"""平台状态读数（UI 用）：模型是否配置、任务分布、待审工具。

只读、轻量；每个页面渲染时取一次，放在顶栏下方的读数条里。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, Tool
from app.services.llm import get_active

DONE_STATUSES = ("passed", "failed", "error", "skipped", "cancelled")


async def get_readout(session: AsyncSession) -> dict:
    rows = await session.execute(
        select(Task.status, func.count()).group_by(Task.status)
    )
    counts = {status: count for status, count in rows.all()}

    pending_tools = await session.scalar(
        select(func.count()).select_from(Tool).where(Tool.status == "pending")
    )

    config = await get_active(session)
    return {
        "model_ready": config is not None,
        "model": config.model if config else None,
        "draft": counts.get("draft", 0),
        "active": counts.get("queued", 0) + counts.get("running", 0),
        "done": sum(counts.get(status, 0) for status in DONE_STATUSES),
        "pending_tools": pending_tools or 0,
    }
