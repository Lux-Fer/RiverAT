"""V0.1.2：失败结果回喂与有限修复草案。"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog, Task, TaskStep, Tool, User
from app.services.agent_recovery import (
    MAX_OBSERVATION_CHARS,
    _observations,
    mark_recovery_resolved,
    maybe_recover_task,
)
from app.services.tasks import execute_task


async def _failed_task(session) -> tuple[Task, Tool]:
    admin = User(username="recovery-admin", role="admin", password_hash="x")
    session.add(admin)
    await session.flush()
    tool = Tool(
        name="login_smoke",
        version="1.0.0",
        description="登录冒烟",
        manifest={
            "name": "login_smoke",
            "version": "1.0.0",
            "entrypoint": {"posix": ["true"]},
            "input_schema": {
                "type": "object",
                "properties": {"base_url": {"type": "string"}},
                "required": ["base_url"],
            },
        },
        bundle_sha256="a" * 64,
        bundle_path="/tmp/tool.tar.gz",
        status="approved",
    )
    task = Task(
        title="登录冒烟失败",
        request_text="对 DEMO 做登录冒烟",
        status="failed",
        draft={"errors": ["工具退出码 3"]},
        created_by=admin.id,
    )
    session.add_all([tool, task])
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_id=tool.id,
            tool_name=tool.name,
            tool_version=tool.version,
            args={"base_url": "http://10.0.0.6:8080"},
            status="failed",
            exit_code=3,
            error="工具退出码 3",
            output={"stderr": "connection refused", "cases": [{"case_id": "login", "status": "failed"}]},
        )
    )
    await session.flush()
    return task, tool


def _fake_chat(*, args: dict | None = None, content: str = "换一个地址重试"):
    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        if args is None:
            return {"content": "建议人工处理", "tool_calls": []}
        return {
            "content": content,
            "tool_calls": [
                {
                    "id": "call-recovery",
                    "type": "function",
                    "function": {"name": "login_smoke", "arguments": json.dumps(args)},
                }
            ],
        }

    return fake_chat


async def test_failure_generates_recovery_draft(session, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_recovery_enabled", True)
    task, _tool = await _failed_task(session)
    seen: list[list[dict]] = []

    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        seen.append(messages)
        return await _fake_chat(args={"base_url": "http://10.0.0.7:8080"})(session, messages)

    monkeypatch.setattr("app.services.llm.chat", fake_chat)

    child = await maybe_recover_task(session, task)
    await session.commit()

    assert child is not None
    assert child.status == "draft"
    assert child.draft["recovery_of"] == str(task.id)
    assert child.draft["replan_count"] == 1
    steps = (
        await session.execute(
            select(TaskStep).where(TaskStep.task_id == child.id).order_by(TaskStep.seq)
        )
    ).scalars().all()
    assert [step.tool_name for step in steps] == ["login_smoke"]
    assert steps[0].args["base_url"] == "http://10.0.0.7:8080"

    await session.refresh(task)
    assert task.draft["agent_recovery"]["task_id"] == str(child.id)
    assert "connection refused" in json.dumps(seen[0], ensure_ascii=False)
    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "task.recovery")
        )
    ).scalars().all()
    assert logs and logs[0].target_id == str(child.id)

    page = await client.get(f"/tasks/{task.id}")
    assert page.status_code == 200
    assert "Agent 修复建议" in page.text
    assert f"/tasks/{child.id}" in page.text


async def test_passed_recovery_marks_parent_resolved(session, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_recovery_enabled", True)
    task, _tool = await _failed_task(session)
    monkeypatch.setattr(
        "app.services.llm.chat", _fake_chat(args={"base_url": "http://10.0.0.7:8080"})
    )
    child = await maybe_recover_task(session, task)
    assert child is not None
    child.status = "passed"
    await session.flush()

    count = await mark_recovery_resolved(session, child)
    await session.commit()

    assert count == 1
    await session.refresh(task)
    assert task.resolved_by_task_id == child.id
    assert task.resolved_at is not None
    page = await client.get(f"/tasks/{task.id}")
    assert "已由后续修复任务解决" in page.text
    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "task.resolved")
        )
    ).scalars().all()
    assert logs and logs[0].target_id == str(task.id)


async def test_no_plan_is_recorded_without_child(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_recovery_enabled", True)
    task, _tool = await _failed_task(session)
    monkeypatch.setattr("app.services.llm.chat", _fake_chat(args=None))

    child = await maybe_recover_task(session, task)
    await session.commit()

    assert child is None
    await session.refresh(task)
    assert task.draft["agent_recovery"]["status"] == "no_plan"
    assert "人工处理" in task.draft["agent_recovery"]["reply"]


async def test_replan_limit_skips_model(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_recovery_enabled", True)
    task, _tool = await _failed_task(session)
    task.draft = {"replan_count": 2}
    await session.flush()
    monkeypatch.setattr(
        "app.services.llm.chat",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应调用模型")),
    )

    child = await maybe_recover_task(session, task)

    assert child is None


def test_observation_is_redacted_and_capped():
    task = Task(
        title="失败",
        request_text="密码 password=super-secret",
        status="failed",
    )
    steps = [
        TaskStep(
            task_id=task.id,
            seq=index,
            tool_name="tool",
            tool_version="1",
            args={"password": "super-secret", "n": index},
            status="failed",
            output={"stderr": "token=abc123 " + "x" * 2000, "cases": []},
        )
        for index in range(1, 20)
    ]

    text = _observations(task, steps)

    assert "super-secret" not in text
    assert "abc123" not in text
    assert len(text) <= MAX_OBSERVATION_CHARS + 20


async def test_agent_failure_stops_following_steps(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_recovery_enabled", True)
    task, tool = await _failed_task(session)
    task.status = "running"
    first = (
        await session.execute(
            select(TaskStep).where(TaskStep.task_id == task.id)
        )
    ).scalar_one()
    first.status = "pending"
    first.output = {}
    first.exit_code = None
    first.error = None
    second = TaskStep(
        task_id=task.id,
        seq=2,
        tool_id=tool.id,
        tool_name=tool.name,
        tool_version=tool.version,
        args={"base_url": "http://second:8080"},
        status="pending",
    )
    session.add(second)
    await session.flush()

    calls: list[str] = []

    async def fake_run_tool(tool, *, args, product, task_id):
        calls.append(str(args.get("n", 0)))
        return {
            "status": "failed",
            "exit_code": 3,
            "output": {"stderr": "first failed", "cases": []},
            "stderr": "first failed",
            "error": "工具退出码 3",
        }

    called_recovery: list[str] = []

    async def fake_recovery(session, failed_task):
        called_recovery.append(str(failed_task.id))

    monkeypatch.setattr("app.services.tool_exec.run_tool", fake_run_tool)
    monkeypatch.setattr(
        "app.services.agent_recovery.maybe_recover_task", fake_recovery
    )

    await execute_task(session, task)
    await session.commit()

    await session.refresh(first)
    await session.refresh(second)
    assert first.status == "failed"
    assert second.status == "skipped"
    assert second.error == "前置步骤失败，未执行"
    assert len(calls) == 1
    assert called_recovery == [str(task.id)]
