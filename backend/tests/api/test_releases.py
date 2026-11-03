"""发布单：建单、质量统计、看板"本周待发"（D72）。"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.models import Run
from tests.plugins import make_plugin


async def _version(client, tmp_path):
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    product = (
        await client.post("/api/v1/products", json={"code": "REL-1", "name": "发布产品"})
    ).json()
    version = (
        await client.post(
            f"/api/v1/products/{product['id']}/versions", json={"version": "2.0.0"}
        )
    ).json()
    plan = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": version["id"],
            "name": "发布计划",
            "definition": {
                "nodes": [{"key": "n1", "plugin": str(plugin), "timeout": 30}]
            },
        },
    )
    assert plan.status_code == 201, plan.text
    return version["id"], plan.json()["id"]


async def test_release_quality_and_dashboard_upcoming(session, client, tmp_path):
    version_id, plan_id = await _version(client, tmp_path)
    target = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()

    created = await client.post(
        "/api/v1/releases",
        json={"product_version_id": version_id, "target_date": target, "name": "2.0 首发"},
    )
    assert created.status_code == 201, created.text
    release = created.json()
    assert release["status"] == "planned"
    assert release["quality"]["runs"] == 0

    run = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()
    assert run["status"] == "passed"

    listed = (await client.get("/api/v1/releases")).json()
    assert listed[0]["quality"]["runs"] == 1
    assert listed[0]["quality"]["passed"] == 1
    assert listed[0]["quality"]["pass_rate"] == 1.0
    assert listed[0]["quality"]["last_status"] == "passed"

    dashboard = (await client.get("/api/v1/dashboard")).json()
    upcoming_ids = [item["id"] for item in dashboard["upcoming"]]
    assert release["id"] in upcoming_ids
    assert dashboard["release_summary"] == {"total": 1, "no_runs": 0}


async def test_dashboard_shows_release_first_with_link(session, client, tmp_path):
    version_id, _ = await _version(client, tmp_path)
    target = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()
    release = (
        await client.post(
            "/api/v1/releases",
            json={"product_version_id": version_id, "target_date": target},
        )
    ).json()

    page = await client.get("/dashboard")

    assert page.status_code == 200
    assert f'href="/releases/{release["id"]}"' in page.text
    assert "个还没有执行" in page.text
    assert page.text.index("未来 7 天待发") < page.text.index("全平台累计")


async def test_released_release_leaves_upcoming(session, client, tmp_path):
    version_id, _ = await _version(client, tmp_path)
    target = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    release = (
        await client.post(
            "/api/v1/releases",
            json={"product_version_id": version_id, "target_date": target},
        )
    ).json()

    patched = await client.patch(
        f"/api/v1/releases/{release['id']}", json={"status": "released"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "released"
    assert patched.json()["quality"]["last_status"] is None

    dashboard = (await client.get("/api/v1/dashboard")).json()
    assert release["id"] not in [item["id"] for item in dashboard["upcoming"]]


async def test_release_page_creates_and_marks_released(session, client, tmp_path):
    version_id, _ = await _version(client, tmp_path)

    page = await client.get("/releases")
    assert page.status_code == 200
    assert "新建发布单" in page.text

    created = await client.post(
        "/releases",
        data={
            "product_version_id": version_id,
            "target_date": date.today().isoformat(),
            "name": "页面发布",
        },
    )
    assert created.status_code == 303

    page = await client.get("/releases")
    assert "页面发布" in page.text

    release = (await client.get("/api/v1/releases")).json()[0]
    marked = await client.post(
        f"/releases/{release['id']}/status", data={"status": "released"}
    )
    assert marked.status_code == 303
    assert (await client.get("/api/v1/releases")).json()[0]["status"] == "released"


async def test_release_detail_page_lists_its_runs(session, client, tmp_path):
    version_id, plan_id = await _version(client, tmp_path)
    target = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    release = (
        await client.post(
            "/api/v1/releases",
            json={"product_version_id": version_id, "target_date": target},
        )
    ).json()

    run = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()

    page = await client.get(f"/releases/{release['id']}")
    assert page.status_code == 200
    assert "这次发布包含的执行" in page.text
    assert run["id"][:8] in page.text
    assert "通过" in page.text

    missing = await client.get(f"/releases/{uuid.uuid4()}")
    assert missing.status_code == 404

async def test_last_status_respects_release_window(session, client, tmp_path):
    """建单前的执行不能冒充「最近一次」—— 否则会出现 0 次 + 绿色通过（D76）。"""

    version_id, plan_id = await _version(client, tmp_path)
    before = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()
    assert before["status"] == "passed"

    # 把这次执行挪到一小时前，避免 now() 精度导致「建单前/后」判定抖动
    run_row = await session.get(Run, uuid.UUID(before["id"]))
    run_row.created_at = datetime.now(UTC) - timedelta(hours=1)
    await session.commit()

    target = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()
    release = (
        await client.post(
            "/api/v1/releases",
            json={"product_version_id": version_id, "target_date": target},
        )
    ).json()
    assert release["quality"]["runs"] == 0
    assert release["quality"]["last_status"] is None

    listed = (await client.get("/api/v1/releases")).json()[0]
    assert listed["quality"]["runs"] == 0
    assert listed["quality"]["last_status"] is None
    assert listed["quality"]["last_run_id"] is None

    # 建单后再跑一次，才应该出现在「最近」
    after = (await client.post("/api/v1/runs", json={"plan_id": plan_id})).json()
    assert after["status"] == "passed"

    listed = (await client.get("/api/v1/releases")).json()[0]
    assert listed["quality"]["runs"] == 1
    assert listed["quality"]["last_status"] == "passed"
    assert listed["quality"]["last_run_id"] == after["id"]