"""v1.1 M4：确认 → 执行 → 结果（用本地 echo 工具端到端验证）。"""

from __future__ import annotations

import io
import json
import tarfile

import pytest


def _echo_bundle(*, exit_code: int = 0, output: str | None = None) -> bytes:
    """一个合法的工具包：读 stdin、输出固定 JSON（跨平台，用当前解释器）。"""

    import sys

    body = output if output is not None else json.dumps(
        {"cases": [{"case_id": "login-001", "status": "passed", "duration_ms": 7}]}
    )
    script = (
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({body!r})\n"
        f"sys.exit({exit_code})\n"
    )

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        entry = [sys.executable, "main.py"]
        manifest = {
            "name": "echo_tool",
            "version": "1.0.0",
            "description": "回声工具",
            "entrypoint": {"linux": entry, "windows": entry},
            "input_schema": {
                "type": "object",
                "properties": {"base_url": {"type": "string"}},
                "required": ["base_url"],
            },
            "timeout_seconds": 20,
        }
        data = json.dumps(manifest).encode()
        info = tarfile.TarInfo("tool.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

        script_bytes = script.encode()
        info = tarfile.TarInfo("main.py")
        info.size = len(script_bytes)
        tar.addfile(info, io.BytesIO(script_bytes))
    return buffer.getvalue()


async def _upload_and_approve(client, bundle: bytes) -> dict:
    uploaded = await client.post(
        "/api/v1/tools", files={"file": ("tool.tar.gz", bundle, "application/gzip")}
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    approved = await client.post(f"/api/v1/tools/{tool['id']}/approve")
    assert approved.status_code == 200
    return approved.json()


def _draft_chat(arguments: dict, name: str = "echo_tool"):
    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        return {
            "content": "准备执行",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        }

    return fake_chat


async def _make_draft(client, monkeypatch) -> dict:
    await _upload_and_approve(client, _echo_bundle())
    monkeypatch.setattr(
        "app.services.llm.chat", _draft_chat({"base_url": "http://target:8080"})
    )
    response = await client.post(
        "/api/v1/assistant/messages", json={"text": "跑一次冒烟"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_confirm_executes_tool_and_records_cases(session, client, monkeypatch):
    draft = await _make_draft(client, monkeypatch)

    approved = await client.post(f"/api/v1/tasks/{draft['id']}/approve")

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "passed"
    assert body["steps"][0]["status"] == "passed"
    assert body["steps"][0]["exit_code"] == 0
    assert body["steps"][0]["output"]["cases"][0]["case_id"] == "login-001"

    detail = (await client.get(f"/api/v1/tasks/{draft['id']}")).json()
    assert detail["status"] == "passed"

    page = await client.get(f"/tasks/{draft['id']}")
    assert page.status_code == 200
    assert "用例结果" in page.text
    assert "login-001" in page.text


async def test_tool_failure_marks_task_failed(session, client, monkeypatch):
    await _upload_and_approve(client, _echo_bundle(exit_code=3))
    monkeypatch.setattr(
        "app.services.llm.chat", _draft_chat({"base_url": "http://target:8080"})
    )
    draft = (
        await client.post("/api/v1/assistant/messages", json={"text": "失败用例"})
    ).json()

    approved = (await client.post(f"/api/v1/tasks/{draft['id']}/approve")).json()

    assert approved["status"] == "failed"
    assert approved["steps"][0]["status"] == "failed"
    assert approved["steps"][0]["exit_code"] == 3


async def test_invalid_json_output_marks_error(session, client, monkeypatch):
    await _upload_and_approve(client, _echo_bundle(output="not json"))
    monkeypatch.setattr(
        "app.services.llm.chat", _draft_chat({"base_url": "http://target:8080"})
    )
    draft = (
        await client.post("/api/v1/assistant/messages", json={"text": "坏输出"})
    ).json()

    approved = (await client.post(f"/api/v1/tasks/{draft['id']}/approve")).json()

    assert approved["status"] == "error"
    assert "JSON" in approved["steps"][0]["error"]


async def test_approve_twice_returns_409(session, client, monkeypatch):
    draft = await _make_draft(client, monkeypatch)
    assert (
        await client.post(f"/api/v1/tasks/{draft['id']}/approve")
    ).status_code == 200

    again = await client.post(f"/api/v1/tasks/{draft['id']}/approve")
    assert again.status_code == 409


async def test_viewer_cannot_approve(session, client, login_as, monkeypatch):
    draft = await _make_draft(client, monkeypatch)
    login_as("viewer")

    response = await client.post(f"/api/v1/tasks/{draft['id']}/approve")
    assert response.status_code == 403


async def test_tasks_page_groups(session, client, monkeypatch):
    draft = await _make_draft(client, monkeypatch)
    await client.post(f"/api/v1/tasks/{draft['id']}/approve")

    page = await client.get("/tasks")
    assert page.status_code == 200
    assert "已完成" in page.text
    assert draft["title"] in page.text


async def test_cancel_draft(session, client, monkeypatch):
    draft = await _make_draft(client, monkeypatch)

    cancelled = await client.post(f"/api/v1/tasks/{draft['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    assert (
        await client.post(f"/api/v1/tasks/{draft['id']}/approve")
    ).status_code == 409


@pytest.mark.parametrize(("statuses", "expected"), [
    (["passed", "passed"], "passed"),
    (["passed", "failed"], "failed"),
    (["failed", "error"], "error"),
])
def test_aggregate_status(statuses, expected):
    from app.services.tasks import _aggregate

    assert _aggregate(statuses) == expected
