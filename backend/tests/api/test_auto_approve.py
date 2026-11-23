"""V0.3.1：只读工具自动确认策略。"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog, KnowledgeEvent, Task, TaskStep, Tool
from app.services.tasks import maybe_auto_approve_task


async def _draft(session, risk: str) -> Task:
    tool = Tool(
        name=f"auto-{risk}",
        version="1.0.0",
        description="自动确认策略测试",
        manifest={
            "name": f"auto-{risk}",
            "version": "1.0.0",
            "risk": risk,
            "entrypoint": {"linux": ["true"]},
            "input_schema": {"type": "object", "properties": {}},
        },
        bundle_sha256="c" * 64,
        bundle_path="/tmp/tool.tar.gz",
        status="approved",
    )
    task = Task(title=f"自动确认 {risk}", request_text="检查", status="draft")
    session.add_all([tool, task])
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_id=tool.id,
            tool_name=tool.name,
            tool_version=tool.version,
            args={},
            status="pending",
        )
    )
    await session.flush()
    return task


async def test_read_only_task_is_auto_approved(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_auto_approve_read_only", True)
    task = await _draft(session, "read_only")

    assert await maybe_auto_approve_task(session, task) is True
    await session.commit()

    assert task.status == "queued"
    assert task.draft["auto_approved"] is True
    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "task.auto_approve")
        )
    ).scalars().all()
    assert logs
    events = (
        await session.execute(
            select(KnowledgeEvent).where(KnowledgeEvent.kind == "task.auto_approved")
        )
    ).scalars().all()
    assert events


async def test_write_task_stays_draft(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_auto_approve_read_only", True)
    task = await _draft(session, "write")

    assert await maybe_auto_approve_task(session, task) is False
    assert task.status == "draft"
