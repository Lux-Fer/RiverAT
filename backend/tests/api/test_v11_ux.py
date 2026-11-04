"""v1.1 UX：首次使用引导、运行中自动刷新。"""

from __future__ import annotations

from uuid import UUID

from app.models import Task
from tests.api.test_v11 import _tool_bundle


async def _approved_tool(client) -> dict:
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    tool = uploaded.json()
    assert (await client.post(f"/api/v1/tools/{tool['id']}/approve")).status_code == 200
    return tool


async def _draft(client, tool: dict) -> dict:
    response = await client.post(
        "/api/v1/tasks",
        json={
            "tool_id": tool["id"],
            "args": {"base_url": "http://10.0.0.6:8080"},
            "title": "刷新测试",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_assistant_shows_setup_checklist_when_empty(session, client):
    page = await client.get("/assistant")

    assert page.status_code == 200
    assert "首次使用" in page.text
    assert "去注册" in page.text
    assert "去上传" in page.text


async def test_assistant_checklist_disappears_after_setup(session, client):
    await client.post(
        "/api/v1/work-products", json={"code": "UX-1", "name": "UX 产品"}
    )
    await _approved_tool(client)

    page = await client.get("/assistant")

    assert "去注册" not in page.text
    assert "去上传" not in page.text


async def test_task_detail_auto_refreshes_while_running(session, client):
    tool = await _approved_tool(client)
    draft = await _draft(client, tool)

    task = await session.get(Task, UUID(draft["id"]))
    task.status = "queued"
    await session.commit()

    page = await client.get(f"/tasks/{draft['id']}")

    assert page.status_code == 200
    assert 'http-equiv="refresh"' in page.text


async def test_completed_task_does_not_auto_refresh(session, client):
    tool = await _approved_tool(client)
    draft = await _draft(client, tool)
    await client.post(f"/api/v1/tasks/{draft['id']}/approve")

    page = await client.get(f"/tasks/{draft['id']}")

    assert 'http-equiv="refresh"' not in page.text


async def test_tasks_page_auto_refreshes_with_active_task(session, client):
    tool = await _approved_tool(client)
    draft = await _draft(client, tool)

    task = await session.get(Task, UUID(draft["id"]))
    task.status = "running"
    await session.commit()

    page = await client.get("/tasks")

    assert 'http-equiv="refresh"' in page.text
