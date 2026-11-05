"""设置总览（D144）：一个导航入口，模型/用户/审计分区。"""

from __future__ import annotations

from app.models import User


async def test_settings_hub_links_sections(session, client):
    session.add(User(username="alice", role="admin"))
    await session.commit()

    page = await client.get("/settings")

    assert page.status_code == 200
    text = page.text
    assert "设置" in text
    assert "模型" in text and "用户" in text and "审计" in text
    assert 'href="/settings/llm"' in text
    assert 'href="/users"' in text
    assert 'href="/audit"' in text
    assert 'aria-label="设置"' in text
    assert 'class="site-status"' in text
    assert 'class="readout"' not in text
    assert "仅管理员可见" in text
    assert "模型设置" not in text


async def test_engineer_has_no_settings_icon(session, client, login_as):
    login_as("engineer")

    page = await client.get("/products")

    assert page.status_code == 200
    assert 'aria-label="设置"' not in page.text


async def test_settings_hub_requires_admin(session, client, login_as):
    login_as("engineer")

    response = await client.get("/settings")

    assert response.status_code == 403
