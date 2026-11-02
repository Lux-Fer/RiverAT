"""执行列表的状态筛选（D78：看板上的数字要能点进去）。"""

from __future__ import annotations

from tests.plugins import make_plugin


async def _one_failed_run(client, tmp_path) -> None:
    ok = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    bad = make_plugin(tmp_path, "bad", "exit 9\n", "exit 9\n")
    product = (
        await client.post("/api/v1/products", json={"code": "F-2", "name": "筛选产品"})
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
            "name": "筛选计划",
            "definition": {
                "nodes": [
                    {"key": "ok", "plugin": str(ok), "timeout": 30},
                    {"key": "bad", "plugin": str(bad), "timeout": 30},
                ]
            },
        },
    )
    assert plan.status_code == 201, plan.text
    await client.post("/api/v1/runs", json={"plan_id": plan.json()["id"]})


async def test_runs_page_filters_by_status(session, client, tmp_path):
    await _one_failed_run(client, tmp_path)

    failed = await client.get("/?status=bad")
    assert failed.status_code == 200
    assert "筛选" in failed.text
    assert "失败/异常" in failed.text

    empty = await client.get("/?status=blocked")
    assert empty.status_code == 200
    assert "这个筛选下没有执行记录" in empty.text


async def test_dashboard_counts_link_to_filtered_list(session, client, tmp_path):
    await _one_failed_run(client, tmp_path)

    page = await client.get("/dashboard")

    assert page.status_code == 200
    assert 'href="/?status=bad"' in page.text
    assert 'href="/?status=passed"' in page.text
