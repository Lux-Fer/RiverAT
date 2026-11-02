"""CSRF：表单必须带 token，否则 403（D75）。"""

from __future__ import annotations

import pytest

from app.web.csrf import CSRF_COOKIE, require_csrf


@pytest.fixture
def real_csrf(app):
    """去掉 conftest 里的全局放行，测真实的 CSRF 校验。"""

    app.dependency_overrides.pop(require_csrf, None)
    yield
    app.dependency_overrides[require_csrf] = lambda: None


async def test_page_sets_csrf_cookie(session, client, real_csrf):
    page = await client.get("/login")

    assert page.status_code == 200
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    assert token in page.text


async def test_form_without_token_is_rejected(session, client, real_csrf):
    await client.get("/login")

    response = await client.post("/logout", data={})

    assert response.status_code == 403
    assert "CSRF" in response.text


async def test_form_with_wrong_token_is_rejected(session, client, real_csrf):
    await client.get("/login")

    response = await client.post("/logout", data={"csrf_token": "not-the-token"})

    assert response.status_code == 403


async def test_form_with_valid_token_passes(session, client, real_csrf):
    await client.get("/login")
    token = client.cookies.get(CSRF_COOKIE)

    response = await client.post(
        "/logout", data={"csrf_token": token}, follow_redirects=False
    )

    assert response.status_code == 303
