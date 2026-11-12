"""V0.2.2 知识控制台：可见性、审核、过期清理。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import AuditLog, KnowledgeEvent, KnowledgeItem, Task, WorkProduct
from app.services.knowledge_base import console_counts, console_items


async def _item(session, *, key: str, **overrides) -> KnowledgeItem:
    values = {
        "item_key": key,
        "kind": "failure_pattern",
        "title": f"知识 {key}",
        "body": "登录失败时先检查目标服务",
        "scope": "global",
        "confidence": 0.5,
        "status": "tentative",
    }
    values.update(overrides)
    item = KnowledgeItem(**values)
    session.add(item)
    await session.flush()
    return item


async def test_console_lists_product_and_global_but_not_other_user(session):
    product = WorkProduct(code="CONSOLE", name="控制台产品", status="active")
    session.add(product)
    await session.flush()
    owner = uuid.uuid4()
    other = uuid.uuid4()
    await _item(session, key="console-global")
    await _item(
        session, key="console-product", scope="product", product_id=product.id
    )
    await _item(session, key="console-own", scope="user", owner_id=owner)
    await _item(session, key="console-other", scope="user", owner_id=other)
    await session.commit()

    rows = await console_items(session, user_id=owner, limit=20)
    keys = {row["item"].item_key for row in rows}

    assert "console-global" in keys
    assert "console-product" in keys
    assert "console-own" in keys
    assert "console-other" not in keys


async def test_console_page_and_admin_review(session, client):
    product = WorkProduct(code="CONSOLE-UI", name="控制台页面", status="active")
    task = Task(title="控制台任务", request_text="登录", status="failed", product_id=None)
    session.add_all([product, task])
    await session.flush()
    item = await _item(
        session,
        key="console-ui",
        title="登录连接被拒绝",
        scope="product",
        product_id=product.id,
        task_id=task.id,
    )
    await session.commit()

    page = await client.get("/knowledge")
    assert page.status_code == 200
    assert "登录连接被拒绝" in page.text
    assert "归档过期知识" in page.text

    response = await client.post(
        f"/knowledge/{item.id}/status",
        data={"status": "approved"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    await session.refresh(item)
    assert item.status == "approved"
    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "knowledge.review")
        )
    ).scalars().all()
    assert logs
    events = (
        await session.execute(
            select(KnowledgeEvent).where(KnowledgeEvent.kind == "knowledge.review")
        )
    ).scalars().all()
    assert events


async def test_expired_knowledge_is_archived(session, client):
    item = await _item(
        session,
        key="expired",
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )
    await session.commit()

    response = await client.post("/knowledge/expire", follow_redirects=False)

    assert response.status_code == 303
    await session.refresh(item)
    assert item.status == "archived"
    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "knowledge.expire")
        )
    ).scalars().all()
    assert logs


async def test_counts_include_status(session):
    owner = uuid.uuid4()
    await _item(session, key="count-a", status="approved")
    await _item(session, key="count-b", status="archived")
    await session.commit()

    counts = await console_counts(session, user_id=owner)

    assert counts["total"] == 2
    assert counts["approved"] == 1
    assert counts["archived"] == 1
