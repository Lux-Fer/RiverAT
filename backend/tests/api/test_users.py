"""用户管理：admin 能建账号、改角色；停用的账号不能登录（D63）。"""

from __future__ import annotations

import uuid

from app.api.deps import require_user
from app.models import User
from app.services.auth import authenticate


async def test_admin_creates_user(session, client):
    response = await client.post(
        "/api/v1/users",
        json={
            "username": "bob",
            "password": "bob-pass-123",
            "role": "engineer",
            "display_name": "Bob",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "bob"
    assert body["role"] == "engineer"
    assert body["is_active"] is True

    listing = await client.get("/api/v1/users")
    assert listing.status_code == 200
    assert any(item["username"] == "bob" for item in listing.json())


async def test_duplicate_username_is_rejected(session, client):
    payload = {"username": "bob", "password": "dup-pass-1", "role": "viewer"}
    assert (await client.post("/api/v1/users", json=payload)).status_code == 201

    duplicate = await client.post("/api/v1/users", json=payload)
    assert duplicate.status_code == 422


async def test_non_admin_cannot_manage_users(session, client, login_as):
    login_as("engineer")

    response = await client.post(
        "/api/v1/users", json={"username": "eve", "password": "x", "role": "viewer"}
    )
    assert response.status_code == 403


async def test_admin_changes_role(session, client):
    created = (
        await client.post(
            "/api/v1/users",
            json={"username": "carol", "password": "carol-pass-1", "role": "viewer"},
        )
    ).json()

    patched = await client.patch(
        f"/api/v1/users/{created['id']}", json={"role": "engineer"}
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["role"] == "engineer"


async def test_deactivated_user_cannot_authenticate(session, client):
    created = (
        await client.post(
            "/api/v1/users",
            json={"username": "dave", "password": "pw-123456", "role": "viewer"},
        )
    ).json()

    patched = await client.patch(
        f"/api/v1/users/{created['id']}", json={"is_active": False}
    )
    assert patched.status_code == 200

    assert await authenticate(session, username="dave", password="pw-123456") is None


async def test_admin_cannot_deactivate_self(session, client, app):
    # 造一个真实 admin，并把当前登录用户换成它，验证自我保护
    admin = User(
        username="root-admin",
        display_name="root",
        role="admin",
        password_hash=None,
    )
    session.add(admin)
    await session.commit()

    app.dependency_overrides[require_user] = lambda: admin

    response = await client.patch(
        f"/api/v1/users/{admin.id}", json={"is_active": False}
    )

    assert response.status_code == 422
    assert "不能停用自己" in response.json()["detail"]


async def test_admin_cannot_demote_self(session, client, app):
    admin = User(
        username="root-admin2",
        display_name="root",
        role="admin",
        password_hash=None,
    )
    session.add(admin)
    await session.commit()

    app.dependency_overrides[require_user] = lambda: admin

    response = await client.patch(f"/api/v1/users/{admin.id}", json={"role": "viewer"})

    assert response.status_code == 422
    assert "不能降级" in response.json()["detail"]


async def test_unknown_user_patch_returns_404(session, client):
    response = await client.patch(
        f"/api/v1/users/{uuid.uuid4()}", json={"role": "viewer"}
    )
    assert response.status_code == 404
