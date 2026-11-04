"""项目支流总览（D121/D122）：排序与空态。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Task, WorkProduct


async def _product(session, code: str, name: str) -> WorkProduct:
    row = WorkProduct(code=code, name=name)
    session.add(row)
    await session.flush()
    return row


async def test_overview_orders_running_upcoming_idle(session, client):
    now = datetime.now(UTC)
    running = await _product(session, "RUN-1", "运行产品")
    upcoming = await _product(session, "UP-1", "待确认产品")
    idle = await _product(session, "IDLE-1", "静水产品")

    session.add_all(
        [
            Task(
                product_id=running.id,
                title="运行中的任务",
                status="running",
                created_at=now - timedelta(minutes=5),
                approved_at=now - timedelta(minutes=5),
            ),
            Task(
                product_id=upcoming.id,
                title="待确认的任务",
                status="draft",
                created_at=now - timedelta(minutes=3),
            ),
            Task(
                product_id=idle.id,
                title="昨天的任务",
                status="passed",
                created_at=now - timedelta(hours=3),
                finished_at=now - timedelta(hours=2),
            ),
        ]
    )
    await session.commit()

    page = await client.get("/")

    assert page.status_code == 200
    text = page.text
    assert text.index("RUN-1") < text.index("UP-1") < text.index("IDLE-1")
    assert "运行中的任务" in text
    assert "1 运行" in text


async def test_overview_empty_state(session, client):
    page = await client.get("/")

    assert page.status_code == 200
    assert "还没有产品" in page.text


async def test_product_detail_flow(session, client):
    now = datetime.now(UTC)
    product = await _product(session, "DETAIL-1", "详情产品")
    session.add(
        Task(
            product_id=product.id,
            title="详情里的运行任务",
            status="running",
            created_at=now - timedelta(minutes=2),
            approved_at=now - timedelta(minutes=2),
        )
    )
    await session.commit()

    page = await client.get(f"/products/{product.id}")

    assert page.status_code == 200
    assert "详情里的运行任务" in page.text
    assert "NOW" in page.text


async def test_product_detail_404(session, client):
    page = await client.get("/products/00000000-0000-0000-0000-000000000000")

    assert page.status_code == 404
