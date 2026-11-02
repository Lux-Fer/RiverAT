"""改密码即下线：旧会话立即失效（D74）。"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import get_session_store, require_user
from app.core.sessions import InMemorySessionStore
from app.services.auth import create_user


@pytest.fixture
async def auth(app, session):
    store = InMemorySessionStore()
    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides[get_session_store] = lambda: store
    await create_user(
        session, username="root-admin", password="admin-pass", role="admin"
    )
    await session.commit()
    yield store
    await store.close()


async def test_reset_password_kicks_existing_sessions(app, client, session, auth):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "root-admin", "password": "admin-pass"},
    )
    assert login.status_code == 200, login.text

    bob = (
        await client.post(
            "/api/v1/users",
            json={"username": "bob", "password": "bob-pass-1", "role": "viewer"},
        )
    ).json()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as bob_client:
        bob_login = await bob_client.post(
            "/api/v1/auth/login",
            json={"username": "bob", "password": "bob-pass-1"},
        )
        assert bob_login.status_code == 200, bob_login.text
        assert (await bob_client.get("/api/v1/plans")).status_code == 200

        reset = await client.patch(
            f"/api/v1/users/{bob['id']}", json={"password": "bob-pass-2"}
        )
        assert reset.status_code == 200, reset.text

        # 旧 cookie 立即失效
        assert (await bob_client.get("/api/v1/plans")).status_code == 401

        # 新密码可以登录
        again = await bob_client.post(
            "/api/v1/auth/login",
            json={"username": "bob", "password": "bob-pass-2"},
        )
        assert again.status_code == 200, again.text
