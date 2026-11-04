"""v1.1 僵尸任务回收（D109）：心跳过期 → 标记失败 + 审计。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.models import Task
from tests.api.test_v11 import _tool_bundle


async def _approved_tool(client) -> dict:
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    assert (await client.post(f"/api/v1/tools/{tool['id']}/approve")).status_code == 200
    return tool


async def _draft_task(client, title: str = "卡死测试") -> dict:
    tool = await _approved_tool(client)
    response = await client.post(
        "/api/v1/tasks",
        json={
            "tool_id": tool["id"],
            "args": {"base_url": "http://10.0.0.6:8080"},
            "title": title,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _make_stale(session, task_id: str) -> None:
    task = await session.get(Task, UUID(task_id))
    task.status = "running"
    task.heartbeat_at = datetime.now(UTC) - timedelta(minutes=30)
    await session.commit()


async def test_stale_task_shows_and_recovers_via_page(session, client):
    draft = await _draft_task(client, "卡死的任务")
    await _make_stale(session, draft["id"])

    page = await client.get("/tasks")
    assert page.status_code == 200
    assert "疑似卡住" in page.text
    assert "卡死的任务" in page.text

    response = await client.post(f"/tasks/{draft['id']}/recover", follow_redirects=False)

    assert response.status_code == 303
    await session.refresh(await session.get(Task, UUID(draft["id"])))
    task = await session.get(Task, UUID(draft["id"]))
    assert task.status == "error"
    assert "心跳超时" in " ".join(task.draft.get("errors", []))

    logs = (await client.get("/api/v1/audit?action=task.recover")).json()
    assert logs
    assert logs[0]["target_id"] == draft["id"]


async def test_recover_api_rejects_fresh_task(session, client):
    draft = await _draft_task(client, "还没卡死")

    response = await client.post(f"/api/v1/tasks/{draft['id']}/recover")

    assert response.status_code == 409


async def test_recover_stale_tasks_service(session, client):
    from app.services.tasks import recover_stale_tasks

    draft = await _draft_task(client, "启动时回收")
    await _make_stale(session, draft["id"])

    recovered = await recover_stale_tasks(session)
    await session.commit()

    assert recovered == 1
    task = await session.get(Task, UUID(draft["id"]))
    assert task.status == "error"


async def test_viewer_does_not_see_stale_section(session, client, login_as):
    draft = await _draft_task(client, "只给管理员看")
    await _make_stale(session, draft["id"])
    login_as("viewer")

    page = await client.get("/tasks")

    assert page.status_code == 200
    assert "疑似卡住" not in page.text
