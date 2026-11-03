"""计划编辑：改 definition 生成新 revision，历史执行不受影响（D70）。"""

from __future__ import annotations

from tests.plugins import make_plugin

_NODES = [{"key": "a", "plugin": "x"}]


async def _setup(client, tmp_path) -> tuple[str, str]:
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    product = (
        await client.post("/api/v1/products", json={"code": "R-1", "name": "修订产品"})
    ).json()
    version = (
        await client.post(
            f"/api/v1/products/{product['id']}/versions", json={"version": "1.0.0"}
        )
    ).json()
    created = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": version["id"],
            "name": "修订计划",
            "definition": {
                "nodes": [{"key": "a", "plugin": str(plugin), "timeout": 30}]
            },
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], str(plugin)


async def test_edit_definition_bumps_revision_and_keeps_history(
    session, client, tmp_path
):
    plan_id, plugin = await _setup(client, tmp_path)

    first = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()
    assert first["status"] == "passed"
    assert first["plan_revision"] == 1
    first_hash = first["plan_sha256"]

    edited = await client.patch(
        f"/api/v1/plans/{plan_id}",
        json={
            "definition": {
                "nodes": [
                    {"key": "a", "plugin": plugin, "timeout": 30},
                    {"key": "b", "plugin": plugin, "timeout": 30, "depends_on": ["a"]},
                ]
            }
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2

    # 旧执行：仍是 1 步、仍指向旧快照
    old = (await client.get(f"/api/v1/runs/{first['id']}")).json()
    assert old["plan_revision"] == 1
    assert old["plan_sha256"] == first_hash
    assert len(old["steps"]) == 1

    # 新执行：用新快照，跑 2 步
    second = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()
    assert second["status"] == "passed"
    assert second["plan_revision"] == 2
    assert second["plan_sha256"] != first_hash
    assert {step["node_key"] for step in second["steps"]} == {"a", "b"}


async def test_rename_does_not_bump_revision(session, client, tmp_path):
    plan_id, _ = await _setup(client, tmp_path)

    renamed = await client.patch(
        f"/api/v1/plans/{plan_id}", json={"name": "新名字"}
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "新名字"
    assert renamed.json()["revision"] == 1


async def test_invalid_definition_is_rejected(session, client, tmp_path):
    plan_id, _ = await _setup(client, tmp_path)

    broken = await client.patch(
        f"/api/v1/plans/{plan_id}",
        json={"definition": {"nodes": [{"key": "a"}]}},
    )

    assert broken.status_code == 422
    assert "plugin" in broken.json()["detail"]


async def test_expected_revision_locks_edits(session, client, tmp_path):
    plan_id, plugin = await _setup(client, tmp_path)

    first = await client.patch(
        f"/api/v1/plans/{plan_id}",
        json={"definition": _definition(plugin), "expected_revision": 1},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 2

    stale = await client.patch(
        f"/api/v1/plans/{plan_id}",
        json={"definition": _definition(plugin), "expected_revision": 1},
    )
    assert stale.status_code == 409
    assert "已被修改" in stale.json()["detail"]


def _definition(plugin: str) -> dict:
    return {"nodes": [{"key": "a", "plugin": plugin, "timeout": 30}]}