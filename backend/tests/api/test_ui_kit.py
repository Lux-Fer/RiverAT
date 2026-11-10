"""UI 资产页：静态交付，不依赖登录。"""

from __future__ import annotations


async def test_ui_kit_is_served(client):
    response = await client.get("/static/ui-kit.html")

    assert response.status_code == 200
    assert "UI ASSETS" in response.text
    assert 'id="i-settings"' in response.text
    assert 'class="ui-scroll"' in response.text
    assert 'aria-haspopup="listbox"' in response.text
    assert 'class="ui-select-menu"' in response.text
    assert 'aria-selected="true"' in response.text
    assert "V0.1.1" in response.text
