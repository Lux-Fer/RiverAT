"""失败归因：失败执行入库，相似失败可检索（D25 v1）。"""

from __future__ import annotations

from tests.plugins import make_plugin


async def _plan_with_plugin(client, plugin) -> str:
    product = (
        await client.post("/api/v1/products", json={"code": "K-1", "name": "知识库产品"})
    ).json()
    version = (
        await client.post(
            f"/api/v1/products/{product['id']}/versions", json={"version": "1.0.0"}
        )
    ).json()
    plan = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": version["id"],
            "name": "知识库计划",
            "definition": {
                "nodes": [{"key": "db", "plugin": str(plugin), "timeout": 30}]
            },
        },
    )
    assert plan.status_code == 201, plan.text
    return plan.json()["id"]


async def test_failed_run_is_indexed_and_similar_found(session, client, tmp_path):
    plugin = make_plugin(
        tmp_path,
        "broken",
        'echo "connection refused to postgres" >&2\nexit 7\n',
        '[Console]::Error.WriteLine("connection refused to postgres")\nexit 7\n',
    )
    plan_id = await _plan_with_plugin(client, plugin)

    first = (
        await client.post("/api/v1/runs", json={"plan_id": plan_id})
    ).json()
    second = (
        await client.post("/api/v1/runs", json={"plan_id": plan_id})
    ).json()
    assert first["status"] == "failed"
    assert second["status"] == "failed"

    response = await client.get(f"/api/v1/runs/{second['id']}/similar")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 1
    run_ids = [item["run_id"] for item in body["items"]]
    assert first["id"] in run_ids
    assert body["items"][0]["score"] > 0


async def test_passed_run_has_no_similar_section(session, client, tmp_path):
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    plan_id = await _plan_with_plugin(client, plugin)

    run = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()
    assert run["status"] == "passed"

    page = await client.get(f"/runs/{run['id']}")
    assert page.status_code == 200
    assert "相似历史失败" not in page.text


async def test_failed_run_page_shows_similar_section(session, client, tmp_path):
    plugin = make_plugin(
        tmp_path, "bad", 'echo "boom" >&2\nexit 3\n', '[Console]::Error.WriteLine("boom")\nexit 3\n'
    )
    plan_id = await _plan_with_plugin(client, plugin)
    run = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()

    page = await client.get(f"/runs/{run['id']}")

    assert page.status_code == 200
    assert "相似历史失败" in page.text
