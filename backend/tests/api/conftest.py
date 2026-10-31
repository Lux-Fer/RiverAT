"""API 测试共用：把 app 接到测试会话上，并默认以一个假登录用户运行。

登录本身由 tests/api/test_auth.py 专门测 —— 它会移除这里的 require_user 覆盖。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.api.deps import require_user
from app.db.session import get_session
from app.main import create_app

STUB_USER = SimpleNamespace(
    id=uuid.uuid4(),
    username="tester",
    display_name="测试员",
    role="admin",
)


@pytest.fixture
def app(session):
    application = create_app()

    async def _override():
        yield session

    application.dependency_overrides[get_session] = _override
    application.dependency_overrides[require_user] = lambda: STUB_USER
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def login_as(app):
    """把当前用户换成指定角色（覆盖 require_user）。"""

    def _set(role: str, username: str = "tester") -> None:
        user = SimpleNamespace(
            id=uuid.uuid4(),
            username=username,
            display_name=username,
            role=role,
        )
        app.dependency_overrides[require_user] = lambda: user

    return _set


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
