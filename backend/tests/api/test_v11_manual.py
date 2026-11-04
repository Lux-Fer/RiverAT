"""v1.1 手动创建任务（D108）：模型不可用时的降级入口。"""

from __future__ import annotations

import json

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


async def test_manual_task_creates_draft(session, client):
    tool = await _approved_tool(client)

    response = await client.post(
        "/api/v1/tasks",
        json={
            "tool_id": tool["id"],
            "args": {"base_url": "http://10.0.0.6:8080"},
            "title": "手动冒烟",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["title"] == "手动冒烟"
    assert body["steps"][0]["tool"] == "login_smoke"
    assert body["steps"][0]["args"]["base_url"] == "http://10.0.0.6:8080"

    logs = (await client.get("/api/v1/audit?action=task.create")).json()
    assert logs
    assert logs[0]["detail"]["tool"] == "login_smoke"


async def test_manual_task_rejects_bad_args(session, client):
    tool = await _approved_tool(client)

    response = await client.post(
        "/api/v1/tasks",
        json={"tool_id": tool["id"], "args": {"user": "only-user"}},
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["detail"]


async def test_manual_task_rejects_unapproved_tool(session, client):
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    tool = uploaded.json()

    response = await client.post(
        "/api/v1/tasks",
        json={"tool_id": tool["id"], "args": {"base_url": "http://x"}},
    )

    assert response.status_code == 422
    assert "审核" in response.json()["detail"]


async def test_manual_task_page_renders_and_submits(session, client):
    tool = await _approved_tool(client)

    page = await client.get("/tasks/new")
    assert page.status_code == 200
    assert "手动创建任务" in page.text
    assert "login_smoke" in page.text

    response = await client.post(
        "/tasks/manual",
        data={
            "tool_id": tool["id"],
            "title": "页面手动任务",
            "product_id": "",
            "args": json.dumps({"base_url": "http://10.0.0.6:8080"}),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/tasks/")


async def test_manual_task_page_invalid_json(session, client):
    tool = await _approved_tool(client)

    response = await client.post(
        "/tasks/manual",
        data={"tool_id": tool["id"], "args": "not json"},
    )

    assert response.status_code == 422
    assert "不是合法 JSON" in response.text


async def test_viewer_cannot_open_manual_task_page(session, client, login_as):
    login_as("viewer")
    assert (await client.get("/tasks/new")).status_code == 403
