"""v1.1 M3：对话 → 任务草案（模型用 monkeypatch 假实现）。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.deps import require_user
from app.models import ChatMessage, Task
from app.services.tasks import task_title
from tests.api.test_v11 import _tool_bundle


def test_task_title_prefers_first_clause():
    assert (
        task_title("请调用工具 acc-echo，对产品 ACC 做一次验收，参数 label 设为 assistant")
        == "请调用工具 acc-echo"
    )
    assert task_title("你好，帮我测登录") == "你好，帮我测登录"
    long = task_title("长" * 80)
    assert len(long) == 61 and long.endswith("…")


async def _approved_tool(client) -> dict:
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    assert (await client.post(f"/api/v1/tools/{tool['id']}/approve")).status_code == 200
    return tool


def _fake_chat(arguments: dict, *, name: str = "login_smoke", content: str = "打算跑登录冒烟"):
    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        return {
            "content": content,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        }

    return fake_chat


async def test_assistant_receives_recent_conversation(
    session, client, app, monkeypatch
):
    await _approved_tool(client)
    actor = SimpleNamespace(
        id=uuid.uuid4(), username="history-user", display_name="", role="admin"
    )
    app.dependency_overrides[require_user] = lambda: actor
    previous = Task(
        title="上一轮登录检查",
        request_text="登录地址是 10.0.0.6",
        status="passed",
        created_by=actor.id,
    )
    session.add(previous)
    await session.flush()
    session.add_all(
        [
            ChatMessage(
                task_id=previous.id,
                role="user",
                content="登录地址是 10.0.0.6",
                created_at=datetime.now(UTC) - timedelta(seconds=2),
            ),
            ChatMessage(
                task_id=previous.id,
                role="assistant",
                content="收到，用这个地址",
                created_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
        ]
    )
    await session.flush()

    seen: list[list[dict]] = []

    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        seen.append(messages)
        return {
            "content": "继续用上一轮地址",
            "tool_calls": [
                {
                    "id": "call-history",
                    "type": "function",
                    "function": {
                        "name": "login_smoke",
                        "arguments": json.dumps(
                            {"base_url": "http://10.0.0.6:8080", "user": "tester"}
                        ),
                    },
                }
            ],
        }

    monkeypatch.setattr("app.services.llm.chat", fake_chat)

    response = await client.post(
        "/api/v1/assistant/messages", json={"text": "用刚才那个地址再跑一次"}
    )

    assert response.status_code == 201, response.text
    contents = [message["content"] for message in seen[0]]
    assert "登录地址是 10.0.0.6" in contents
    assert any("用刚才那个地址再跑一次" in content for content in contents)
    assert [message["role"] for message in seen[0]][:3] == ["system", "user", "assistant"]


async def test_assistant_creates_draft(session, client, monkeypatch):
    await _approved_tool(client)
    monkeypatch.setattr(
        "app.services.llm.chat",
        _fake_chat({"base_url": "http://10.0.0.6:8080", "user": "tester"}),
    )

    response = await client.post(
        "/api/v1/assistant/messages",
        json={"text": "对 DEMO 的登录做冒烟检查"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["errors"] == []
    assert body["steps"][0]["tool"] == "login_smoke"
    assert body["steps"][0]["args"]["user"] == "tester"
    assert "登录冒烟" in body["reply"]

    page = await client.get("/assistant")
    assert page.status_code == 200
    assert 'class="chat-msg user"' in page.text
    assert 'class="chat-avatar"' in page.text
    assert "最新草案" in page.text
    assert "login_smoke" in page.text
    assert "确认执行" in page.text


async def test_assistant_flags_missing_arguments(session, client, monkeypatch):
    await _approved_tool(client)
    monkeypatch.setattr("app.services.llm.chat", _fake_chat({"user": "tester"}))

    response = await client.post(
        "/api/v1/assistant/messages", json={"text": "缺参数"}
    )

    assert response.status_code == 201
    errors = response.json()["errors"]
    assert any("缺少 base_url" in item for item in errors)

    page = await client.get("/assistant")
    assert "⚠" in page.text
    assert "缺少 base_url" in page.text


async def test_assistant_rejects_unknown_tool(session, client, monkeypatch):
    await _approved_tool(client)
    monkeypatch.setattr(
        "app.services.llm.chat",
        _fake_chat({"x": 1}, name="not_a_tool"),
    )

    response = await client.post(
        "/api/v1/assistant/messages", json={"text": "调不存在的工具"}
    )

    assert response.status_code == 201
    assert any("未知工具" in item for item in response.json()["errors"])
    assert response.json()["steps"] == []


async def test_assistant_requires_approved_tools(session, client):
    response = await client.post(
        "/api/v1/assistant/messages", json={"text": "还没有工具"}
    )

    assert response.status_code == 422
    assert "工具" in response.json()["detail"]


async def test_assistant_form_submit_redirects(session, client, monkeypatch):
    await _approved_tool(client)
    monkeypatch.setattr(
        "app.services.llm.chat",
        _fake_chat({"base_url": "http://x", "user": "u"}),
    )

    response = await client.post(
        "/assistant/messages",
        data={"text": "表单提交", "product_id": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/assistant"


@pytest.mark.parametrize(
    ("schema", "args", "expected"),
    [
        ({"required": ["a"]}, {}, "缺少 a"),
        ({"properties": {"a": {"type": "string"}}}, {"a": 1}, "a 应为 string"),
        ({"properties": {"a": {"type": "object"}}}, {"a": []}, "a 应为 object"),
    ],
)
def test_validate_args(schema, args, expected):
    from app.services.tasks import validate_args

    assert any(expected in item for item in validate_args(schema, args))
