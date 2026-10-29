"""计划接口：JSON / YAML 创建 + 结构校验。"""

from __future__ import annotations

from app.models import Product, ProductVersion


async def _seed_version(session) -> ProductVersion:
    product = Product(code="P-PLAN", name="被测产品")
    session.add(product)
    await session.flush()
    version = ProductVersion(product_id=product.id, version="1.0.0")
    session.add(version)
    await session.commit()
    return version


async def test_create_plan_from_yaml(session, client):
    version = await _seed_version(session)
    yaml_text = "nodes:\n  - key: login\n    plugin: /tmp/demo\n"

    response = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": str(version.id),
            "name": "YAML 计划",
            "definition": yaml_text,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["definition"]["nodes"][0]["key"] == "login"

    listing = await client.get("/api/v1/plans")
    assert any(plan["id"] == body["id"] for plan in listing.json())


async def test_plan_with_cycle_is_rejected(session, client):
    version = await _seed_version(session)
    definition = {
        "nodes": [
            {"key": "a", "plugin": "/tmp/a", "depends_on": ["b"]},
            {"key": "b", "plugin": "/tmp/b", "depends_on": ["a"]},
        ]
    }

    response = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": str(version.id),
            "name": "环",
            "definition": definition,
        },
    )

    assert response.status_code == 422
    assert "成环" in response.json()["detail"]


async def test_plan_with_missing_dependency_is_rejected(session, client):
    version = await _seed_version(session)
    definition = {
        "nodes": [{"key": "a", "plugin": "/tmp/a", "depends_on": ["ghost"]}]
    }

    response = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": str(version.id),
            "name": "缺依赖",
            "definition": definition,
        },
    )

    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


async def test_unknown_product_version_is_rejected(session, client):
    response = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": "00000000-0000-0000-0000-000000000000",
            "name": "孤儿计划",
            "definition": {"nodes": [{"key": "a", "plugin": "/tmp/a"}]},
        },
    )

    assert response.status_code == 422
