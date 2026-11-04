"""任务台账（D132）：运行中 → 将进行 → 已完成。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Task, TaskStep, WorkProduct


async def _product(session) -> WorkProduct:
    row = WorkProduct(code="BOARD-1", name="台账产品")
    session.add(row)
    await session.flush()
    return row


async def _task(session, product, title: str, status: str, **kwargs) -> Task:
    row = Task(product_id=product.id, title=title, status=status, **kwargs)
    session.add(row)
    await session.flush()
    return row


async def test_task_board_orders_running_upcoming_done(session, client):
    now = datetime.now(UTC)
    product = await _product(session)

    running = await _task(
        session,
        product,
        "正在跑的回归",
        "running",
        created_at=now - timedelta(minutes=8),
        approved_at=now - timedelta(minutes=7),
    )
    session.add_all(
        [
            TaskStep(
                task_id=running.id,
                seq=1,
                tool_name="web-login",
                tool_version="1.0.0",
                status="passed",
            ),
            TaskStep(
                task_id=running.id,
                seq=2,
                tool_name="api-pay",
                tool_version="1.0.0",
                status="running",
            ),
        ]
    )
    await _task(
        session,
        product,
        "等人确认的草案",
        "draft",
        created_at=now - timedelta(minutes=4),
    )
    await _task(
        session,
        product,
        "上次跑完的任务",
        "passed",
        created_at=now - timedelta(hours=2),
        approved_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1),
    )
    await session.commit()

    page = await client.get("/tasks")

    assert page.status_code == 200
    text = page.text
    assert text.index("正在跑的回归") < text.index("等人确认的草案") < text.index("上次跑完的任务")
    assert "1 进行 · 1 将进行 · 1 完成" in text
    assert "1 / 2 步 · api-pay" in text
    assert "BOARD-1 · 台账产品" in text


async def test_task_board_empty_state(session, client):
    page = await client.get("/tasks")

    assert page.status_code == 200
    assert "还没有任务" in page.text
