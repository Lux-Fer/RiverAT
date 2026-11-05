"""登录与会话：API 401、页面跳转、表单登录、登出。"""

from __future__ import annotations

import pytest

from app.api.deps import COOKIE_NAME, get_session_store, require_user
from app.core.sessions import InMemorySessionStore
from app.services.auth import create_user


@pytest.fixture
async def real_auth(app, session):
    """移除假登录用户，换成内存会话存储 + 一个真实账号。"""

    store = InMemorySessionStore()
    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides[get_session_store] = lambda: store
    await create_user(session, username="alice", password="pw-123456", role="admin")
    await session.commit()
    yield store
    await store.close()


async def test_api_requires_login(session, client, real_auth):
    response = await client.get("/api/v1/products")
    assert response.status_code == 401


async def test_login_sets_cookie_and_me_works(session, client, real_auth):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "pw-123456"},
    )
    assert login.status_code == 200, login.text
    assert COOKIE_NAME in client.cookies

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"

    products = await client.get("/api/v1/products")
    assert products.status_code == 200


async def test_wrong_password_is_rejected(session, client, real_auth):
    response = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "wrong"}
    )
    assert response.status_code == 401
    assert COOKIE_NAME not in client.cookies


async def test_pages_redirect_to_login(session, client, real_auth):
    response = await client.get("/products", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


async def test_form_login_then_logout(session, client, real_auth):
    login = await client.post(
        "/login",
        data={"username": "alice", "password": "pw-123456"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/"

    home = await client.get("/")
    assert home.status_code == 200
    assert "alice" in home.text

    logout = await client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"

    after = await client.get("/api/v1/products")
    assert after.status_code == 401


async def test_login_page_has_form(session, client):
    page = await client.get("/login")

    assert page.status_code == 200
    assert "内网部署" in page.text
    assert 'action="/login"' in page.text
    assert "用户名" in page.text
    assert "密码" in page.text
    assert "进入" in page.text


async def test_bad_form_password_shows_error(session, client, real_auth):
    response = await client.post(
        "/login", data={"username": "alice", "password": "nope"}
    )
    assert response.status_code == 401
    assert "用户名或密码错误" in response.text
    assert 'value="alice"' in response.text
