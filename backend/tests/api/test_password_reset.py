"""密码重置：管理员改别人的密码，旧密码立即失效（D71）。"""

from __future__ import annotations

from app.services.auth import authenticate


async def _create(client, username: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/users",
        json={"username": username, "password": password, "role": "viewer"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_admin_resets_password(session, client):
    user = await _create(client, "pw-user", "old-pass-1")

    reset = await client.patch(
        f"/api/v1/users/{user['id']}", json={"password": "new-pass-2"}
    )

    assert reset.status_code == 200, reset.text
    assert await authenticate(session, username="pw-user", password="old-pass-1") is None
    assert await authenticate(session, username="pw-user", password="new-pass-2")


async def test_short_password_is_rejected(session, client):
    user = await _create(client, "pw-short", "good-pass-1")

    response = await client.patch(f"/api/v1/users/{user['id']}", json={"password": "123"})

    assert response.status_code == 422
    assert "至少" in response.json()["detail"]


async def test_create_user_enforces_min_length(session, client):
    response = await client.post(
        "/api/v1/users",
        json={"username": "pw-too-short", "password": "123", "role": "viewer"},
    )

    assert response.status_code == 422


async def test_page_resets_password(session, client):
    user = await _create(client, "pw-page", "before-pass")

    response = await client.post(
        f"/users/{user['id']}",
        data={
            "role": "viewer",
            "is_active": "true",
            "display_name": "分页用户",
            "password": "after-pass",
        },
    )

    assert response.status_code == 303
    assert await authenticate(session, username="pw-page", password="after-pass")
