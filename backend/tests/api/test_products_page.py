"""产品注册页（D134）：产品按活动排序，注册表单在工作区右侧。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Task, WorkProduct


async def _product(session, code: str, name: str, *, base_url: str = "") -> WorkProduct:
    row = WorkProduct(code=code, name=name, base_url=base_url)
    session.add(row)
    await session.flush()
    return row


async def test_products_page_orders_running_before_idle(session, client):
    now = datetime.now(UTC)
    idle = await _product(session, "IDLE-1", "没在跑的产品")
    running = await _product(
        session, "RUN-1", "正在跑的产品", base_url="http://10.0.0.8:8080"
    )
    session.add_all(
        [
            Task(
                product_id=idle.id,
                title="昨天的任务",
                status="passed",
                created_at=now - timedelta(hours=2),
                approved_at=now - timedelta(hours=2),
                finished_at=now - timedelta(hours=1),
            ),
            Task(
                product_id=running.id,
                title="正在跑的任务",
                status="running",
                created_at=now - timedelta(minutes=4),
                approved_at=now - timedelta(minutes=3),
            ),
        ]
    )
    await session.commit()

    page = await client.get("/products")

    assert page.status_code == 200
    text = page.text
    assert text.index("RUN-1") < text.index("IDLE-1")
    assert "http://10.0.0.8:8080" in text
    assert "1 进行" in text
    assert 'action="/products"' in text
    assert "注册产品" in text
    assert 'class="ui-select"' in text
    assert "ui-select.js" in text


async def test_products_page_empty_keeps_form_open(session, client):
    page = await client.get("/products")

    assert page.status_code == 200
    assert "还没有产品" in page.text
    assert 'action="/products"' in page.text
    assert "注册产品" in page.text
    assert "必填" in page.text
    assert "选填" in page.text
    assert 'aria-required="true"' in page.text


async def test_products_form_creates_product(session, client):
    response = await client.post(
        "/products",
        data={
            "code": "FORM-1",
            "name": "表单注册产品",
            "base_url": "http://10.0.0.9:8080",
            "description": "从页面注册",
            "ci_provider": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    page = await client.get("/products")
    assert "FORM-1" in page.text
    assert "表单注册产品" in page.text
    assert "http://10.0.0.9:8080" in page.text


async def test_products_form_error_is_inline_and_keeps_values(session, client):
    response = await client.post(
        "/products",
        data={
            "code": "BAD-1",
            "name": "地址写错了",
            "base_url": "10.0.0.9:8080",
            "description": "保留我",
            "ci_provider": "jenkins",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    text = response.text
    assert "注册未完成" in text
    assert "http://" in text
    assert 'value="BAD-1"' in text
    assert 'value="地址写错了"' in text
    assert 'value="10.0.0.9:8080"' in text
    assert 'value="保留我"' in text
    assert "autofocus" in text
    assert 'id="register"' in text
    assert 'role="alert"' in text
    assert "selected" in text
