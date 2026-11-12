"""V0.2.0 M1/M2：事件、知识入库、检索注入。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import (
    AuditLog,
    KnowledgeEvent,
    KnowledgeFeedback,
    KnowledgeItem,
    KnowledgeItemSource,
    Task,
    TaskStep,
    Tool,
    WorkProduct,
)
from app.services.agent_recovery import maybe_recover_task
from app.services.knowledge_base import index_task_outcome, record_event, search_knowledge
from tests.api.test_v11 import _tool_bundle


async def _product(session, code: str) -> WorkProduct:
    product = WorkProduct(code=code, name=f"{code} 产品", status="active")
    session.add(product)
    await session.flush()
    return product


async def _failed_task(session, *, product: WorkProduct | None = None):
    tool = Tool(
        name="knowledge_tool",
        version="1.0.0",
        description="知识测试工具",
        manifest={
            "name": "knowledge_tool",
            "version": "1.0.0",
            "entrypoint": {"linux": ["true"]},
            "input_schema": {
                "type": "object",
                "properties": {"base_url": {"type": "string"}},
                "required": ["base_url"],
            },
        },
        bundle_sha256="b" * 64,
        bundle_path="/tmp/tool.tar.gz",
        status="approved",
    )
    task = Task(
        title="登录失败",
        request_text="对登录做冒烟检查，地址 http://bad.example",
        status="failed",
        product_id=product.id if product else None,
        draft={"errors": ["退出码 3"]},
    )
    session.add_all([tool, task])
    await session.flush()
    step = TaskStep(
        task_id=task.id,
        seq=1,
        tool_id=tool.id,
        tool_name=tool.name,
        tool_version=tool.version,
        args={"base_url": "http://bad.example", "password": "super-secret"},
        status="failed",
        exit_code=3,
        error="退出码 3",
        output={"stderr": "token=abc123 connection refused", "cases": []},
        finished_at=datetime.now(UTC),
    )
    session.add(step)
    await session.flush()
    return task, step


async def test_task_creation_records_event(session, client, monkeypatch):
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    await client.post(f"/api/v1/tools/{tool['id']}/approve")

    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        return {
            "content": "准备执行",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "login_smoke",
                        "arguments": json.dumps({"base_url": "http://x:8080"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("app.services.llm.chat", fake_chat)
    created = await client.post(
        "/api/v1/assistant/messages", json={"text": "做一次登录冒烟"}
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    events = (
        await session.execute(
            select(KnowledgeEvent).where(KnowledgeEvent.task_id == task_id)
        )
    ).scalars().all()
    assert "task.created" in {event.kind for event in events}
    assert "knowledge.retrieved" in {event.kind for event in events}


async def test_failed_task_indexes_redacted_knowledge(session):
    product = await _product(session, "KNOW-1")
    task, step = await _failed_task(session, product=product)
    await record_event(
        session,
        event_key=f"task.created:{task.id}",
        kind="task.created",
        product_id=product.id,
        task_id=task.id,
        payload={"request": task.request_text},
    )
    await record_event(
        session,
        event_key=f"step.finished:{step.id}",
        kind="step.finished",
        product_id=product.id,
        task_id=task.id,
        payload={"status": "failed", "stderr": step.output["stderr"]},
    )

    item = await index_task_outcome(session, task, [step])
    await session.commit()

    assert item is not None
    assert item.kind == "failure_pattern"
    assert item.product_id == product.id
    assert item.scope == "product"
    assert item.valid_until is not None
    assert "super-secret" not in item.body
    assert "abc123" not in item.body
    sources = (
        await session.execute(
            select(KnowledgeItemSource).where(KnowledgeItemSource.item_id == item.id)
        )
    ).scalars().all()
    assert len(sources) == 2


async def test_search_respects_product_scope(session):
    product_a = await _product(session, "KNOW-A")
    product_b = await _product(session, "KNOW-B")
    a = KnowledgeItem(
        item_key="a",
        kind="failure_pattern",
        title="产品 A 登录失败",
        body="connection refused 登录失败",
        product_id=product_a.id,
    )
    b = KnowledgeItem(
        item_key="b",
        kind="failure_pattern",
        title="产品 B 登录失败",
        body="connection refused 登录失败",
        product_id=product_b.id,
    )
    global_item = KnowledgeItem(
        item_key="global",
        kind="failure_pattern",
        title="通用登录失败",
        body="connection refused 登录失败",
        product_id=None,
        scope="global",
    )
    session.add_all([a, b, global_item])
    await session.commit()

    items = await search_knowledge(
        session, "登录失败 connection refused", product_id=product_a.id, limit=5
    )

    assert {item["id"] for item in items} == {a.id, global_item.id}


async def test_related_knowledge_appears_on_task_page(session, client):
    product = await _product(session, "KNOW-UI")
    task, _step = await _failed_task(session, product=product)
    session.add(
        KnowledgeItem(
            item_key="ui",
            kind="failure_pattern",
            title="登录连接被拒绝",
            body="登录地址不可达时先检查目标服务是否启动",
            product_id=product.id,
        )
    )
    await session.commit()

    page = await client.get(f"/tasks/{task.id}")

    assert page.status_code == 200
    assert "相关知识" in page.text
    assert "登录连接被拒绝" in page.text


async def test_planning_injects_retrieved_knowledge(session, client, monkeypatch):
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    await client.post(f"/api/v1/tools/{tool['id']}/approve")
    item = KnowledgeItem(
        item_key="plan",
        kind="failure_pattern",
        title="登录冒烟经验",
        body="登录地址不可达时先检查服务是否启动，不要直接重试。",
        product_id=None,
        scope="global",
    )
    session.add(item)
    await session.commit()

    seen: list[list[dict]] = []

    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        seen.append(messages)
        return {
            "content": "参考历史经验",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "login_smoke",
                        "arguments": json.dumps({"base_url": "http://x:8080"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("app.services.llm.chat", fake_chat)
    created = await client.post(
        "/api/v1/assistant/messages", json={"text": "做一次登录冒烟"}
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    prompt = "\n".join(message["content"] for message in seen[0])
    assert "登录冒烟经验" in prompt
    assert "[K1]" in prompt
    events = (
        await session.execute(
            select(KnowledgeEvent).where(KnowledgeEvent.task_id == task_id)
        )
    ).scalars().all()
    assert "knowledge.retrieved" in {event.kind for event in events}


async def test_recovery_injects_retrieved_knowledge(session, client, monkeypatch):
    from app.core.config import get_settings

    product = await _product(session, "KNOW-REC")
    task, _step = await _failed_task(session, product=product)
    session.add(
        KnowledgeItem(
            item_key="recovery",
            kind="failure_pattern",
            title="登录失败：connection refused",
            body="connection refused 时先确认目标服务启动，再重试登录。",
            product_id=product.id,
        )
    )
    await session.commit()
    monkeypatch.setattr(get_settings(), "agent_recovery_enabled", True)
    seen: list[list[dict]] = []

    async def fake_chat(session, messages, *, tools=None, max_tokens=1024, timeout=60.0):
        seen.append(messages)
        return {"content": "建议人工处理", "tool_calls": []}

    monkeypatch.setattr("app.services.llm.chat", fake_chat)

    await maybe_recover_task(session, task)
    await session.commit()

    prompt = "\n".join(message["content"] for message in seen[0])
    assert "登录失败：connection refused" in prompt
    assert "先确认目标服务启动" in prompt


async def test_user_scope_and_expiry_filter(session):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    now = datetime.now(UTC)
    session.add_all(
        [
            KnowledgeItem(
                item_key="user-a",
                kind="preference",
                title="用户 A 的登录偏好",
                body="登录失败时先检查目标服务",
                product_id=None,
                scope="user",
                owner_id=user_a,
                valid_until=now + timedelta(days=10),
            ),
            KnowledgeItem(
                item_key="user-b",
                kind="preference",
                title="用户 B 的登录偏好",
                body="登录失败时先检查目标服务",
                product_id=None,
                scope="user",
                owner_id=user_b,
                valid_until=now + timedelta(days=10),
            ),
            KnowledgeItem(
                item_key="expired",
                kind="failure_pattern",
                title="过期的登录经验",
                body="登录失败时先检查目标服务",
                product_id=None,
                scope="global",
                valid_until=now - timedelta(days=1),
            ),
        ]
    )
    await session.commit()

    items = await search_knowledge(
        session,
        "登录失败 目标服务",
        user_id=user_a,
        limit=5,
    )

    assert {item["id"] for item in items} == {
        item.id
        for item in (
            await session.execute(
                select(KnowledgeItem).where(KnowledgeItem.item_key == "user-a")
            )
        ).scalars()
    }


async def test_feedback_promotes_knowledge(session, client):
    product = await _product(session, "KNOW-FB")
    task, _step = await _failed_task(session, product=product)
    item = KnowledgeItem(
        item_key="feedback",
        kind="failure_pattern",
        title="登录连接被拒绝",
        body="登录地址不可达时先检查目标服务是否启动",
        product_id=product.id,
        confidence=0.5,
        status="tentative",
    )
    session.add(item)
    await session.commit()

    page = await client.get(f"/tasks/{task.id}")
    assert "有用" in page.text and "不相关" in page.text

    response = await client.post(
        f"/tasks/{task.id}/knowledge/{item.id}/feedback",
        data={"helpful": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    await session.refresh(item)
    assert item.status == "approved"
    assert item.confidence == 0.6
    feedback = (
        await session.execute(
            select(KnowledgeFeedback).where(KnowledgeFeedback.item_id == item.id)
        )
    ).scalar_one()
    assert feedback.helpful is True
    events = (
        await session.execute(
            select(KnowledgeEvent).where(KnowledgeEvent.kind == "knowledge.feedback")
        )
    ).scalars().all()
    assert events
    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "knowledge.feedback")
        )
    ).scalars().all()
    assert logs
