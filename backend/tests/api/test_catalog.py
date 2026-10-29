"""产品目录：产品树、版本、版本锁死（D4/D5）与页面。"""

from __future__ import annotations


async def _product(client, code: str, name: str, parent_id: str | None = None) -> dict:
    response = await client.post(
        "/api/v1/products",
        json={"code": code, "name": name, "parent_id": parent_id},
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
    return await client.post(
        f"/api/v1/versions/{parent_version}/components",
        json={"child_product_id": product_id, "child_version_id": version_id},
    )


async def test_product_tree_and_locked_components(session, client):
    a = await _product(client, "A", "部件 A")
    b = await _product(client, "B", "部件 B")
    c = await _product(client, "C", "组合产品")
    a1 = await _version(client, a["id"], "2.1.0")
    b1 = await _version(client, b["id"], "3.4.0")
    c1 = await _version(client, c["id"], "1.0.0")

    assert (await _lock(client, c1["id"], a["id"], a1["id"])).status_code == 201
    assert (await _lock(client, c1["id"], b["id"], b1["id"])).status_code == 201

    detail = await client.get(f"/api/v1/versions/{c1['id']}")
    assert detail.status_code == 200
    assert {
        item["product_code"]: item["version"] for item in detail.json()["components"]
    } == {"A": "2.1.0", "B": "3.4.0"}


async def test_same_child_product_cannot_lock_twice(session, client):
    a = await _product(client, "A", "部件 A")
    b = await _product(client, "B", "组合产品")
    a1 = await _version(client, a["id"], "1.0.0")
    a2 = await _version(client, a["id"], "1.1.0")
    b1 = await _version(client, b["id"], "1.0.0")

    assert (await _lock(client, b1["id"], a["id"], a1["id"])).status_code == 201
    conflict = await _lock(client, b1["id"], a["id"], a2["id"])

    assert conflict.status_code == 422
    assert "已经锁定" in conflict.json()["detail"]


async def test_component_version_must_belong_to_child_product(session, client):
    a = await _product(client, "A", "部件 A")
    b = await _product(client, "B", "部件 B")
    c = await _product(client, "C", "组合产品")
    b1 = await _version(client, b["id"], "1.0.0")
    c1 = await _version(client, c["id"], "1.0.0")

    response = await _lock(client, c1["id"], a["id"], b1["id"])

    assert response.status_code == 422
    assert "不属于" in response.json()["detail"]


async def test_duplicate_product_code_is_rejected(session, client):
    await _product(client, "A", "部件 A")
    response = await client.post(
        "/api/v1/products", json={"code": "A", "name": "重复"}
    )
    assert response.status_code == 422


async def test_tree_endpoint_nests_children(session, client):
    parent = await _product(client, "C", "组合产品")
    child = await _product(client, "A", "部件 A", parent_id=parent["id"])

    response = await client.get("/api/v1/products")

    assert response.status_code == 200
    roots = response.json()
    assert [node["code"] for node in roots] == ["C"]
    assert [node["code"] for node in roots[0]["children"]] == ["A"]
    assert roots[0]["children"][0]["id"] == child["id"]


async def test_products_and_version_pages(session, client):
    a = await _product(client, "A", "部件 A")
    c = await _product(client, "C", "组合产品")
    a1 = await _version(client, a["id"], "2.1.0")
    c1 = await _version(client, c["id"], "1.0.0")
    assert (await _lock(client, c1["id"], a["id"], a1["id"])).status_code == 201

    products = await client.get("/products")
    assert products.status_code == 200
    assert "部件 A" in products.text
    assert "2.1.0" in products.text

    version = await client.get(f"/versions/{c1['id']}")
    assert version.status_code == 200
    assert "部件 A" in version.text
    assert "2.1.0" in version.text
