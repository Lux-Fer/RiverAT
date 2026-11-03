"""审计日志：谁改了什么可查（D82）。"""

from __future__ import annotations

from tests.plugins import make_plugin


async def _plan(client, tmp_path) -> dict:
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    product = (
        await client.post("/api/v1/products", json={"code": "A-1", "name": "审计产品"})
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
            "name": "审计计划",
            "definition": {
                "nodes": [{"key": "n1", "plugin": str(plugin), "timeout": 30}]
            },
        },
    )
    assert plan.status_code == 201, plan.text
    return plan.json()


async def test_plan_actions_are_audited(session, client, tmp_path):
    plan = await _plan(client, tmp_path)
    await client.patch(f"/api/v1/plans/{plan['id']}", json={"name": "改名"})

    logs = (await client.get("/api/v1/audit")).json()
    actions = [(entry["action"], entry["username"]) for entry in logs]

    assert ("plan.create", "tester") in actions
    assert ("plan.update", "tester") in actions

    update = next(entry for entry in logs if entry["action"] == "plan.update")
    assert update["detail"]["definition_changed"] is False
    assert update["target_id"] == plan["id"]


async def test_user_password_reset_is_audited(session, client):
    created = (
        await client.post(
            "/api/v1/users",
            json={"username": "audit-user", "password": "pass-1234", "role": "viewer"},
        )
    ).json()
    await client.patch(
        f"/api/v1/users/{created['id']}", json={"password": "pass-5678"}
    )

    logs = (await client.get("/api/v1/audit")).json()
    user_updates = [entry for entry in logs if entry["action"] == "user.update"]

    assert user_updates
    assert user_updates[0]["detail"]["password_reset"] is True


async def test_audit_page_and_admin_only(session, client, login_as, tmp_path):
    await _plan(client, tmp_path)

    page = await client.get("/audit")
    assert page.status_code == 200
    assert "审计日志" in page.text
    assert "创建计划" in page.text

    login_as("viewer")
    assert (await client.get("/audit")).status_code == 403
    assert (await client.get("/api/v1/audit")).status_code == 403


async def test_audit_filters(session, client, tmp_path):
    await _plan(client, tmp_path)
    await client.post(
        "/api/v1/users",
        json={"username": "filter-user", "password": "pass-1234", "role": "viewer"},
    )

    only_plans = (await client.get("/api/v1/audit?action=plan.create")).json()
    assert only_plans
    assert {entry["action"] for entry in only_plans} == {"plan.create"}

    by_user = (await client.get("/api/v1/audit?username=tester")).json()
    assert by_user
    assert {entry["username"] for entry in by_user} == {"tester"}

    none = (await client.get("/api/v1/audit?username=ghost")).json()
    assert none == []


async def test_audit_csv_export(session, client, login_as, tmp_path):
    await _plan(client, tmp_path)

    response = await client.get("/api/v1/audit/export.csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "riverat-audit.csv" in response.headers["content-disposition"]
    assert "时间,操作人,动作" in response.text
    assert "创建计划" in response.text

    login_as("viewer")
    assert (await client.get("/api/v1/audit/export.csv")).status_code == 403