"""角色授权：viewer 只读、engineer 可写、admin 管测试机（D62）。"""

from __future__ import annotations


async def test_viewer_cannot_create_product(session, client, login_as):
    login_as("viewer")

    response = await client.post(
        "/api/v1/products", json={"code": "V-1", "name": "只读创建"}
    )
    assert response.status_code == 403

    listing = await client.get("/api/v1/products")
    assert listing.status_code == 200


async def test_viewer_page_hides_create_form(session, client, login_as):
    login_as("viewer")

    page = await client.get("/products")
    assert page.status_code == 200
    # 表单整个不渲染（空态文案里仍会出现"注册产品"四个字）
    assert 'action="/products"' not in page.text

    forbidden = await client.post("/products", data={"code": "V-2", "name": "x"})
    assert forbidden.status_code == 403
    assert "没有权限" in forbidden.text


async def test_forbidden_page_has_way_back(session, client, login_as):
    login_as("engineer")

    page = await client.get("/users")

    assert page.status_code == 403
    assert "没有权限" in page.text
    assert "需要管理员权限" in page.text
    assert "返回工作台" in page.text
    assert 'href="/"' in page.text


async def test_engineer_can_create_but_not_manage_hosts(session, client, login_as):
    login_as("engineer")

    created = await client.post(
        "/api/v1/products", json={"code": "E-1", "name": "工程师创建"}
    )
    assert created.status_code == 201

    host = await client.post(
        "/api/v1/hosts",
        json={
            "name": "h1",
            "hostname": "10.0.0.1",
            "username": "tester",
            "password": "x",
        },
    )
    assert host.status_code == 403


async def test_engineer_sees_create_form(session, client, login_as):
    login_as("engineer")

    page = await client.get("/products")
    assert page.status_code == 200
    assert "注册产品" in page.text


async def test_admin_can_manage_hosts(session, client, login_as):
    login_as("admin")

    response = await client.post(
        "/api/v1/hosts",
        json={
            "name": "admin-host",
            "hostname": "10.0.0.2",
            "username": "tester",
            "password": "x",
        },
    )
    assert response.status_code == 201, response.text

    listing = await client.get("/api/v1/hosts")
    assert listing.status_code == 200
