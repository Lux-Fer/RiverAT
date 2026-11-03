"""v1.1 模型端点接口（D97，仅 admin）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.services.llm import LlmError, get_active, save_config, test_connection

router = APIRouter(prefix="/llm-config", tags=["llm"])


class LlmConfigPatch(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None


@router.get("")
async def read_config(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[object, Depends(require_admin)],
) -> dict:
    config = await get_active(session)
    if config is None:
        return {"configured": False, "has_key": False, "source": None}
    return {
        "configured": True,
        "base_url": config.base_url,
        "model": config.model,
        "has_key": bool(config.api_key),
        "source": config.source,
    }


@router.put("")
async def update_config(
    payload: LlmConfigPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict:
    try:
        await save_config(
            session,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            actor=admin,
        )
    except LlmError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return {"configured": True}


@router.post("/test")
async def test_model(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[object, Depends(require_admin)],
) -> dict:
    return await test_connection(session)
