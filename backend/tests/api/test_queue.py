"""队列语义：POST 只建记录并投递，执行由 worker（这里是手动触发）完成（D65）。"""

from __future__ import annotations

import uuid

import pytest

from app.models import Run
from app.services.runs import execute_run
from app.worker.dispatch import get_dispatcher
from tests.plugins import make_plugin


class RecordingDispatcher:
    """只记录，不执行 —— 模拟"已投递到队列"。"""

    def __init__(self) -> None:
        self.dispatched: list[uuid.UUID] = []

    async def dispatch(self, run_id, session) -> None:
        self.dispatched.append(run_id)


@pytest.fixture
def queued(app):
    dispatcher = RecordingDispatcher()
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    yield dispatcher
    app.dependency_overrides.pop(get_dispatcher, None)


async def _plan(client, plugin) -> str:
    product = (
        await client.post("/api/v1/products", json={"code": "Q-1", "name": "队列产品"})
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
            "name": "队列计划",
            "definition": {
                "nodes": [{"key": "run", "plugin": str(plugin), "timeout": 30}]
            },
        },
    )
    assert plan.status_code == 201, plan.text
    return plan.json()["id"]


async def test_create_run_is_queued_then_worker_executes(session, client, queued, tmp_path):
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    plan_id = await _plan(client, plugin)

    created = await client.post("/api/v1/runs", json={"plan_id": plan_id})

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "queued"
    assert body["steps"] == []
    assert uuid.UUID(body["id"]) in queued.dispatched

    # 模拟 worker 消费
    run = await session.get(Run, uuid.UUID(body["id"]))
    assert run is not None
    await execute_run(session, run)
    await session.commit()

    finished = await client.get(f"/api/v1/runs/{body['id']}")
    assert finished.status_code == 200
    assert finished.json()["status"] == "passed"
    assert {step["node_key"]: step["status"] for step in finished.json()["steps"]} == {
        "run": "passed"
    }
