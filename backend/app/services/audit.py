"""审计日志（D82）：把"谁改了什么"落库，供 admin 查询。

写日志和业务写在同一事务里（服务层调用），业务失败则日志也不留 ——
避免出现"改了但没记录"或"记录了但没改成"。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

ACTION_LABELS = {
    "plan.create": "创建计划",
    "plan.update": "编辑计划",
    "user.create": "新建用户",
    "user.update": "修改用户",
    "release.create": "新建发布单",
    "release.update": "更新发布单",
    "host.create": "注册测试机",
    "task.create": "新建任务",
    "task.approve": "确认任务",
    "task.cancel": "取消任务",
    "task.edit": "编辑任务参数",
    "task.rerun": "重跑任务",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


async def record(
    session: AsyncSession,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | UUID | None = None,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=actor.id if actor is not None else None,
        username=actor.username if actor is not None else "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail or {},
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_logs(
    session: AsyncSession,
    *,
    username: str | None = None,
    action: str | None = None,
    limit: int = 200,
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if username:
        stmt = stmt.where(AuditLog.username == username)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())
