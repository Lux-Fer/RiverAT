"""计划快照：创建时冻结展开结果，子计划之后被改也不影响既有计划（D59）。"""

from __future__ import annotations

import uuid

from app.models import Plan
from tests.plugins import make_plugin


async def _product(client, code: str, name: str) -> dict:
    response = await client.post(
        "/api/v1/products", json={"code": code, "name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _version(client, product_id: str, version: str) -> dict:
    response = await client.post(
        f"/api/v1/products/{product_id}/versions", json={"version": version}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _plan(client, version_id: str, name: str, definition: dict) -> dict:
    response = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": version_id,
            "name": name,
            "definition": definition,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_parent_plan_runs_from_frozen_snapshot(client, session, tmp_path):
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')

    a = await _product(client, "A", "部件 A")
    c = await _product(client, "C", "组合产品")
    av = await _version(client, a["id"], "1.0.0")
    cv = await _version(client, c["id"], "1.0.0")

    child = await _plan(
        client,
        av["id"],
        "A 计划",
        {"nodes": [{"key": "login", "plugin": str(plugin), "timeout": 30}]},
    )
    lock = await client.post(
        f"/api/v1/versions/{cv['id']}/components",
        json={"child_product_id": a["id"], "child_version_id": av["id"]},
    )
    assert lock.status_code == 201, lock.text

    parent = await _plan(
        client,
        cv["id"],
        "C 计划",
        {
            "includes": [{"plan_id": child["id"], "prefix": "a"}],
            "nodes": [],
        },
    )

    parent_row = await session.get(Plan, uuid.UUID(parent["id"]))
    assert parent_row is not None
    assert [node["key"] for node in parent_row.snapshot["nodes"]] == ["a.login"]
    assert len(parent_row.snapshot_sha256) == 64

    # 模拟"子计划被编辑"：直接改库里的子计划定义
    child_row = await session.get(Plan, uuid.UUID(child["id"]))
    assert child_row is not None
    child_row.definition = {
        "nodes": [{"key": "changed", "plugin": str(plugin), "timeout": 30}]
    }
    await session.commit()

    run = await client.post("/api/v1/runs", json={"plan_id": parent["id"]})

    assert run.status_code == 201, run.text
    body = run.json()
    assert {step["node_key"] for step in body["steps"]} == {"a.login"}
    assert body["status"] == "passed"
    assert body["plan_sha256"] == parent_row.snapshot_sha256
