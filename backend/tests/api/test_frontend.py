"""前端交互约定：HTMX 轮询只在执行未结束时挂载（D32）。"""

from __future__ import annotations

import uuid

from app.models import Run
from app.worker.dispatch import get_dispatcher
from tests.plugins import make_plugin


class RecordingDispatcher:
    """只记录，不执行 —— 让 run 停在 queued，方便测轮询。"""

    async def dispatch(self, run_id, session) -> None:
        return None


async def _queued_run(client, app, tmp_path) -> dict:
    app.dependency_overrides[get_dispatcher] = lambda: RecordingDispatcher()
    try:
        product = (
            await client.post(
                "/api/v1/products", json={"code": "F-1", "name": "前端用例"}
            )
        ).json()
        version = (
            await client.post(
                f"/api/v1/products/{product['id']}/versions",
                json={"version": "1.0.0"},
            )
        ).json()
        plan = await client.post(
            "/api/v1/plans",
            json={
                "product_version_id": version["id"],
                "name": "前端计划",
                "definition": {
                    "nodes": [
                        {
                            "key": "n1",
                            "plugin": str(
                                make_plugin(
                                    tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n'
                                )
                            ),
                            "timeout": 30,
                        }
                    ]
                },
            },
        )
        assert plan.status_code == 201, plan.text

        created = await client.post(
            "/api/v1/runs", json={"plan_id": plan.json()["id"]}
        )
        assert created.status_code == 201, created.text
        return created.json()
    finally:
        app.dependency_overrides.pop(get_dispatcher, None)


async def _set_status(session, run_id: uuid.UUID, status: str) -> None:
    run = await session.get(Run, run_id)
    assert run is not None
    run.status = status
    await session.commit()


async def test_vendor_assets_are_served(client):
    htmx = await client.get("/static/vendor/htmx.min.js")
    chart = await client.get("/static/vendor/chart.umd.min.js")

    assert htmx.status_code == 200
    assert "javascript" in htmx.headers["content-type"]
    assert chart.status_code == 200
    assert "javascript" in chart.headers["content-type"]
