"""领导页接口（只读，viewer 及以上）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_user
from app.db.session import get_session
from app.services.dashboard import summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> dict:
    return await summary(session)
