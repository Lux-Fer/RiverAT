"""领导页：五个数字的聚合口径（D29）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Plan, Product, ProductVersion, Run, RunStep

_NODES = [{"key": "a", "plugin": "x"}, {"key": "b", "plugin": "x"}]


async def _seed(session) -> None:
    product = Product(code="D-1", name="仪表盘产品")
    session.add(product)
    await session.flush()

    v1 = ProductVersion(product_id=product.id, version="1.0.0")
    v2 = ProductVersion(product_id=product.id, version="2.0.0")
    session.add_all([v1, v2])
    await session.flush()

    plan = Plan(
        product_version_id=v1.id,
        name="dash",
        definition={"nodes": _NODES},
        snapshot={"nodes": _NODES},
    )
    session.add(plan)
    await session.flush()

    now = datetime.now(UTC)
    passed = Run(
        plan_id=plan.id,
        product_version_id=v1.id,
        trigger="manual",
        status="passed",
        started_at=now - timedelta(seconds=10),
        finished_at=now,
    )
    failed = Run(
        plan_id=plan.id,
        product_version_id=v2.id,
        trigger="manual",
        status="failed",
        started_at=now - timedelta(seconds=20),
        finished_at=now,
    )
    session.add_all([passed, failed])
    await session.flush()

    session.add_all(
        [
            RunStep(run_id=passed.id, node_key="a", status="passed"),
            RunStep(run_id=passed.id, node_key="b", status="passed"),
            RunStep(run_id=failed.id, node_key="a", status="failed"),
        ]
    )
    await session.commit()


async def test_dashboard_api_numbers(session, client):
    await _seed(session)

    response = await client.get("/api/v1/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 2
    assert data["pass_rate"] == 0.5
    assert data["coverage"]["complete"] == 1
    assert data["coverage"]["finished"] == 2
    assert data["coverage"]["ratio"] == 0.5
    assert data["risk_versions"] == 1  # v2 从未成功
    assert data["duration"]["p50"] == 15.0
    assert data["duration"]["p90"] == 19.0
    # 近 14 天趋势固定 14 个点，今天的桶里 1 通过 1 失败
    assert len(data["trend"]) == 14
    today = data["trend"][-1]
    assert today["passed"] == 1
    assert today["failed"] == 1


async def test_dashboard_page_renders(session, client):
    await _seed(session)

    page = await client.get("/dashboard")

    assert page.status_code == 200
    assert "通过率" in page.text
    assert "50.0%" in page.text
    assert "风险敞口" in page.text


async def test_dashboard_empty_state(session, client):
    response = await client.get("/api/v1/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 0
    assert data["pass_rate"] is None
    assert data["coverage"]["ratio"] is None
    assert data["duration"]["p50"] is None
