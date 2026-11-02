"""发布单接口（D72）。"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer, require_user
from app.db.session import get_session
from app.services.releases import (
    ReleaseError,
    create_release,
    decorate,
    decorated_list,
    get_release,
    update_release,
)

router = APIRouter(prefix="/releases", tags=["releases"])


class ReleaseCreate(BaseModel):
    product_version_id: UUID
    target_date: date
    name: str = ""
    note: str = ""


class ReleasePatch(BaseModel):
    status: str | None = None
    target_date: date | None = None
    name: str | None = None
    note: str | None = None


async def _one(session: AsyncSession, release_id: UUID) -> dict:
    release = await get_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="发布单不存在")
    return await decorate(session, release)


@router.get("")
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> list[dict]:
    return await decorated_list(session)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    payload: ReleaseCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _engineer: Annotated[object, Depends(require_engineer)],
) -> dict:
    try:
        release = await create_release(
            session,
            product_version_id=payload.product_version_id,
            target_date=payload.target_date,
            name=payload.name,
            note=payload.note,
        )
    except ReleaseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return await _one(session, release.id)


@router.patch("/{release_id}")
async def patch(
    release_id: UUID,
    payload: ReleasePatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    _engineer: Annotated[object, Depends(require_engineer)],
) -> dict:
    release = await get_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="发布单不存在")

    try:
        await update_release(
            session,
            release,
            status=payload.status,
            target_date=payload.target_date,
            name=payload.name,
            note=payload.note,
        )
    except ReleaseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return await _one(session, release.id)
