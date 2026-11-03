"""v1.1 模型端点（D97）：OpenAI 兼容协议。

配置优先级：数据库里的 active 行 → `.env` 里的 `RIVERAT_LLM_*`。
没有可用配置时抛 ``LlmError``，调用方负责降级（手动建任务）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.models import LlmConfig, User


class LlmError(RuntimeError):
    """模型端点不可用 / 返回异常。"""


@dataclass(frozen=True, slots=True)
class LlmSettings:
    base_url: str
    model: str
    api_key: str
    source: str  # "database" | "env"


async def get_active(session: AsyncSession) -> LlmSettings | None:
    row = await session.scalar(
        select(LlmConfig).where(LlmConfig.is_active.is_(True)).limit(1)
    )
    if row is not None:
        return LlmSettings(
            base_url=row.base_url.rstrip("/"),
            model=row.model,
            api_key=decrypt(row.api_key_enc) if row.api_key_enc else "",
            source="database",
        )

    settings = get_settings()
    if settings.riverat_llm_base_url and settings.riverat_llm_model:
        return LlmSettings(
            base_url=settings.riverat_llm_base_url.rstrip("/"),
            model=settings.riverat_llm_model,
            api_key=settings.riverat_llm_api_key,
            source="env",
        )
    return None


async def save_config(
    session: AsyncSession,
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    actor: User | None,
) -> LlmConfig:
    base_url = base_url.strip().rstrip("/")
    model = model.strip()
    if not base_url.startswith(("http://", "https://")):
        raise LlmError("base_url 必须以 http:// 或 https:// 开头")
    if not model:
        raise LlmError("model 不能为空")

    for existing in (
        await session.execute(select(LlmConfig).where(LlmConfig.is_active.is_(True)))
    ).scalars():
        existing.is_active = False

    row = LlmConfig(
        base_url=base_url,
        model=model,
        api_key_enc=encrypt(api_key) if api_key else "",
        is_active=True,
        updated_by=actor.id if actor else None,
    )
    session.add(row)
    await session.flush()
    return row


async def chat(
    session: AsyncSession,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> dict:
    """调用一次 /chat/completions，返回 assistant message。"""

    config = await get_active(session)
    if config is None:
        raise LlmError("还没有配置模型端点")

    payload: dict = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{config.base_url}/chat/completions", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        raise LlmError(f"连接模型失败: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        body = response.text[:300]
        raise LlmError(f"模型返回 {response.status_code}: {body}")

    try:
        data = response.json()
        return data["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LlmError("模型返回格式不符合 OpenAI 兼容协议") from exc


async def test_connection(session: AsyncSession) -> dict:
    config = await get_active(session)
    if config is None:
        return {"ok": False, "error": "还没有配置模型端点"}

    started = time.monotonic()
    try:
        message = await chat(
            session,
            [{"role": "user", "content": "只回复：ok"}],
            max_tokens=8,
            timeout=20.0,
        )
    except LlmError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "model": config.model,
            "base_url": config.base_url,
            "source": config.source,
        }

    return {
        "ok": True,
        "model": config.model,
        "base_url": config.base_url,
        "source": config.source,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "reply": (message.get("content") or "").strip()[:50],
    }
