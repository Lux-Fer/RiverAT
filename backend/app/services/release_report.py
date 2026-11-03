"""发布报告（D86）：把一次发布的验证结果渲染成一个自包含 HTML 文件。

* 单文件：样式内联、不引用任何外部资源，离线可打开/归档；
* 内容：封面信息、质量摘要、执行明细、失败节点证据（stderr 尾部）、口径说明；
* 只读：不改变任何数据。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Release, User
from app.services.releases import decorate, runs_for_release
from app.services.runs import list_steps


async def build_context(
    session: AsyncSession, release: Release, *, generated_by: User | None
) -> dict:
    runs = await runs_for_release(session, release)

    entries = []
    for run in runs:
        steps = await list_steps(session, run.id)
        entries.append(
            {
                "run": run,
                "steps": steps,
                "failed_steps": [
                    step for step in steps if step.status in ("failed", "error")
                ],
            }
        )

    tz = ZoneInfo(get_settings().display_timezone)
    generated_at = datetime.now(tz)

    return {
        "release": await decorate(session, release),
        "entries": entries,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M"),
        "generated_by": generated_by.username if generated_by else "system",
        "passed": sum(1 for entry in entries if entry["run"].status == "passed"),
        "failed": sum(
            1 for entry in entries if entry["run"].status in ("failed", "error")
        ),
    }
