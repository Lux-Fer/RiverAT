"""计划继承：父计划引用已锁定子版本的计划（D57）。"""

from __future__ import annotations

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


async def _lock(client, parent_version: str, product_id: str, version_id: str):
    response = await client.post(
        f"/api/v1/versions/{parent_version}/components",
        json={"child_product_id": product_id, "child_version_id": version_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _plan(client, version_id: str, name: str, definition: dict):
    return await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": version_id,
            "name": name,
            "definition": definition,
        },
    )


def _ok_plugin(tmp_path):
    return make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')


async def test_child_plan_nodes_are_included_and_prefixed(client, tmp_path):
    a = await _product(client, "A", "部件 A")
    c = await _product(client, "C", "组合产品")
    av = await _version(client, a["id"], "1.0.0")
    cv = await _version(client, c["id"], "1.0.0")
    plugin = _ok_plugin(tmp_path)

    child = await _plan(
        client,
        av["id"],
        "A 冒烟",
        {"nodes": [{"key": "login", "plugin": str(plugin), "timeout": 30}]},
    )
    assert child.status_code == 201, child.text

    await _lock(client, cv["id"], a["id"], av["id"])

    parent = await _plan(
        client,
        cv["id"],
        "C 组合",
        {
            "includes": [{"plan_id": child.json()["id"], "prefix": "a"}],
            "nodes": [
                {
                    "key": "integration",
                    "plugin": str(plugin),
                    "timeout": 30,
                    "depends_on": ["a.login"],
                }
            ],
        },
    )
    assert parent.status_code == 201, parent.text

    run = await client.post("/api/v1/runs", json={"plan_id": parent.json()["id"]})

    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "passed"
    assert {step["node_key"]: step["status"] for step in body["steps"]} == {
        "a.login": "passed",
        "integration": "passed",
    }


async def test_include_of_unlocked_version_is_rejected(client, tmp_path):
    a = await _product(client, "A", "部件 A")
    c = await _product(client, "C", "组合产品")
    av = await _version(client, a["id"], "1.0.0")
    cv = await _version(client, c["id"], "1.0.0")
    plugin = _ok_plugin(tmp_path)

    child = await _plan(
        client, av["id"], "A 冒烟", {"nodes": [{"key": "login", "plugin": str(plugin)}]}
    )
    assert child.status_code == 201

    # C 的版本没有锁定 A，却想引用 A 的计划
    parent = await _plan(
        client,
        cv["id"],
        "C 组合",
        {"includes": [{"plan_id": child.json()["id"]}], "nodes": []},
    )

    assert parent.status_code == 422
    assert "已锁定" in parent.json()["detail"]


async def test_duplicate_include_prefix_is_rejected(client, tmp_path):
    a = await _product(client, "A", "部件 A")
    b = await _product(client, "B", "部件 B")
    c = await _product(client, "C", "组合产品")
    av = await _version(client, a["id"], "1.0.0")
    bv = await _version(client, b["id"], "1.0.0")
    cv = await _version(client, c["id"], "1.0.0")
    plugin = _ok_plugin(tmp_path)

    plan_a = await _plan(
        client, av["id"], "A 计划", {"nodes": [{"key": "x", "plugin": str(plugin)}]}
    )
    plan_b = await _plan(
        client, bv["id"], "B 计划", {"nodes": [{"key": "y", "plugin": str(plugin)}]}
    )
    await _lock(client, cv["id"], a["id"], av["id"])
    await _lock(client, cv["id"], b["id"], bv["id"])

    parent = await _plan(
        client,
        cv["id"],
        "C 组合",
        {
            "includes": [
                {"plan_id": plan_a.json()["id"], "prefix": "same"},
                {"plan_id": plan_b.json()["id"], "prefix": "same"},
            ],
            "nodes": [],
        },
    )

    assert parent.status_code == 422
    assert "前缀重复" in parent.json()["detail"]


async def test_cross_plan_dependency_to_missing_node_is_rejected(client, tmp_path):
    a = await _product(client, "A", "部件 A")
    c = await _product(client, "C", "组合产品")
    av = await _version(client, a["id"], "1.0.0")
    cv = await _version(client, c["id"], "1.0.0")
    plugin = _ok_plugin(tmp_path)

    child = await _plan(
        client, av["id"], "A 计划", {"nodes": [{"key": "login", "plugin": str(plugin)}]}
    )
    await _lock(client, cv["id"], a["id"], av["id"])

    parent = await _plan(
        client,
        cv["id"],
        "C 组合",
        {
            "includes": [{"plan_id": child.json()["id"], "prefix": "a"}],
            "nodes": [
                {
                    "key": "integration",
                    "plugin": str(plugin),
                    "depends_on": ["a.ghost"],
                }
            ],
        },
    )

    assert parent.status_code == 422
    assert "a.ghost" in parent.json()["detail"]
