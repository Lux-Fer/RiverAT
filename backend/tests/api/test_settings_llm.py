"""模型设置页（D136）：配置可见、Key 不回显、留空保留原 Key。"""

from __future__ import annotations

from app.services.llm import get_active


async def test_settings_page_saves_and_hides_key(session, client):
    saved = await client.post(
        "/settings/llm",
        data={
            "base_url": "http://10.0.0.9:8000/v1",
            "model": "test-model",
            "api_key": "sk-secret-value",
        },
    )

    assert saved.status_code == 200
    assert "已保存" in saved.text
    assert "sk-secret-value" not in saved.text
    assert "Key 已保存" in saved.text
    assert "test-model" in saved.text
    assert "http://10.0.0.9:8000/v1" in saved.text


async def test_blank_key_keeps_existing_key(session, client):
    await client.post(
        "/settings/llm",
        data={
            "base_url": "http://10.0.0.9:8000/v1",
            "model": "first-model",
            "api_key": "sk-keep-me",
        },
    )

    changed = await client.post(
        "/settings/llm",
        data={
            "base_url": "http://10.0.0.9:8000/v1",
            "model": "second-model",
            "api_key": "",
        },
    )

    assert changed.status_code == 200
    assert "Key 已保存" in changed.text
    config = await get_active(session)
    assert config is not None
    assert config.model == "second-model"
    assert config.api_key == "sk-keep-me"


async def test_engineer_cannot_open_model_settings(session, client, login_as):
    login_as("engineer")

    response = await client.get("/settings/llm")

    assert response.status_code == 403
