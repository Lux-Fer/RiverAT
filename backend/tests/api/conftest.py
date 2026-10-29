"""API 测试共用：把 app 接到测试会话上。"""

from __future__ import annotations

import httpx
import pytest

from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def app(session):
    application = create_app()

    async def _override():
        yield session

    application.dependency_overrides[get_session] = _override
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
