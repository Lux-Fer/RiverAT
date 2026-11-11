"""产品编辑/归档与工具停用/启用。"""

from __future__ import annotations

from tests.api.test_v11 import _tool_bundle


async def _product(client, code: str = "EDIT-1") -> dict:
    response = await client.post(
        "/api/v1/work-products",
        json={"code": code, "name": "原名称", "base_url": "http://old.example:8080"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _approved_tool(client) -> dict:
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    assert (await client.post(f"/api/v1/tools/{tool['id']}/approve")).status_code == 200
    return tool


async def test_product_update_archive_restore(session, client):
    product = await _product(client)

    patched = await client.patch(
        f"/api/v1/work-products/{product['id']}",
        json={
            "name": "新名称",
            "base_url": "http://new.example:8080",
            "description": "改了地址",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "新名称"
    assert patched.json()["base_url"] == "http://new.example:8080"

    archived = await client.patch(
        f"/api/v1/work-products/{product['id']}", json={"status": "archived"}
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    listed = (await client.get("/api/v1/work-products")).json()
    assert product["id"] not in [item["id"] for item in listed]

    page = await client.get("/products")
    assert "已归档" in page.text
    assert "EDIT-1" in page.text

    restored = await client.patch(
        f"/api/v1/work-products/{product['id']}", json={"status": "active"}
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


async def test_product_update_page_and_archive(session, client):
    product = await _product(client, "EDIT-PAGE")

    response = await client.post(
        f"/products/{product['id']}",
        data={
            "name": "页面改名",
            "base_url": "http://page.example:8080",
            "description": "页面编辑",
            "ci_provider": "",
            "ci_webhook_url": "",
            "ci_secret": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = await client.get(f"/products/{product['id']}")
    assert "页面改名" in detail.text
    assert "归档产品" in detail.text

    archived = await client.post(
        f"/products/{product['id']}/archive", follow_redirects=False
    )
    assert archived.status_code == 303
    detail = await client.get(f"/products/{product['id']}")
    assert "已归档" in detail.text
    assert "恢复产品" in detail.text

    restored = await client.post(
        f"/products/{product['id']}/restore", follow_redirects=False
    )
    assert restored.status_code == 303
    assert "已归档" not in (await client.get(f"/products/{product['id']}")).text


async def test_archived_product_cannot_create_task(session, client):
    product = await _product(client, "ARCH-1")
    tool = await _approved_tool(client)
    await client.patch(
        f"/api/v1/work-products/{product['id']}", json={"status": "archived"}
    )

    response = await client.post(
        "/api/v1/tasks",
        json={
            "tool_id": tool["id"],
            "product_id": product["id"],
            "args": {"base_url": "http://example:8080"},
        },
    )

    assert response.status_code == 422
    assert "已归档" in response.text


async def test_tool_disable_enable_and_page(session, client):
    tool = await _approved_tool(client)

    disabled = await client.post(f"/api/v1/tools/{tool['id']}/disable")
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"

    blocked = await client.post(
        "/api/v1/tasks",
        json={
            "tool_id": tool["id"],
            "args": {"base_url": "http://example:8080"},
        },
    )
    assert blocked.status_code == 422

    page = await client.get("/tools")
    assert "已停用" in page.text
    assert "启用" in page.text

    ended = await client.post(f"/api/v1/tools/{tool['id']}/enable")
    assert ended.status_code == 200
    assert ended.json()["status"] == "approved"

    # 页面动作
    response = await client.post(
        f"/tools/{tool['id']}/state", data={"decision": "disable"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "已停用" in (await client.get("/tools")).text
