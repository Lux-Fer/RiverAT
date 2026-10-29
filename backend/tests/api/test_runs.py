"""执行接口与页面的端到端测试：真 PG、真迁移、真插件（本地 transport）。"""

from __future__ import annotations

import uuid

from app.models import Plan, Product, ProductVersion, Run, RunStep
from tests.plugins import make_plugin


async def _seed_plan(session, nodes: list[dict]) -> Plan:
    product = Product(code="C", name="组合产品")
    session.add(product)
    await session.flush()
    version = ProductVersion(product_id=product.id, version="1.0.0")
    session.add(version)
    await session.flush()
    plan = Plan(
        product_version_id=version.id,
        name="冒烟",
        definition={"nodes": nodes},
    )
    session.add(plan)
    await session.commit()
    return plan


def _pass_fail_plugins(tmp_path):
    ok = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    bad = make_plugin(
        tmp_path,
        "bad",
        'echo "boom" >&2\nexit 7\n',
        '[Console]::Error.WriteLine("boom")\nexit 7\n',
    )
    return ok, bad


async def test_create_run_persists_steps(session, client, tmp_path):
    ok, bad = _pass_fail_plugins(tmp_path)
    plan = await _seed_plan(
        session,
        [
            {"key": "login", "plugin": str(ok), "timeout": 30},
            {"key": "logout", "plugin": str(bad), "timeout": 30},
        ],
    )

    response = await client.post("/api/v1/runs", json={"plan_id": str(plan.id)})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert {step["node_key"]: step["status"] for step in body["steps"]} == {
        "login": "passed",
        "logout": "failed",
    }

    stored = await session.get(Run, uuid.UUID(body["id"]))
    assert stored is not None
    steps = (await session.execute(RunStep.__table__.select())).all()
    assert len(steps) == 2


async def test_run_detail_page_renders_statuses(session, client, tmp_path):
    ok, bad = _pass_fail_plugins(tmp_path)
    plan = await _seed_plan(
        session,
        [
            {"key": "login", "plugin": str(ok), "timeout": 30},
            {"key": "logout", "plugin": str(bad), "timeout": 30},
        ],
    )
    created = await client.post("/api/v1/runs", json={"plan_id": str(plan.id)})
    run_id = created.json()["id"]

    page = await client.get(f"/runs/{run_id}")

    assert page.status_code == 200
    assert 'class="badge passed"' in page.text
    assert 'class="badge failed"' in page.text


async def test_unknown_plan_returns_422(session, client):
    response = await client.post(
        "/api/v1/runs", json={"plan_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert response.status_code == 422


async def test_runs_page_lists_created_run(session, client, tmp_path):
    ok, _ = _pass_fail_plugins(tmp_path)
    plan = await _seed_plan(session, [{"key": "only", "plugin": str(ok), "timeout": 30}])
    created = await client.post("/api/v1/runs", json={"plan_id": str(plan.id)})
    assert created.status_code == 201

    page = await client.get("/")

    assert page.status_code == 200
    assert str(created.json()["id"]) in page.text


async def test_dependency_failure_blocks_downstream(session, client, tmp_path):
    ok, bad = _pass_fail_plugins(tmp_path)
    plan = await _seed_plan(
        session,
        [
            {"key": "login", "plugin": str(ok), "timeout": 30},
            {"key": "logout", "plugin": str(bad), "timeout": 30},
            {
                "key": "report",
                "plugin": str(ok),
                "timeout": 30,
                "depends_on": ["logout"],
            },
        ],
    )

    response = await client.post("/api/v1/runs", json={"plan_id": str(plan.id)})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert {step["node_key"]: step["status"] for step in body["steps"]} == {
        "login": "passed",
        "logout": "failed",
        "report": "blocked",
    }

    page = await client.get(f"/runs/{body['id']}")
    assert page.status_code == 200
    assert 'class="badge blocked"' in page.text
