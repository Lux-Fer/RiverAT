"""v1.1 被测产品接口（D100）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.work_products import (
    ProductError,
    create_product,
    get_product,
    list_products,
)

router = APIRouter(prefix="/work-products", tags=["work-products"])


class ProductCreate(BaseModel):
    code: str
    name: str
    base_url: str = ""
    description: str = ""
    ci_provider: str = ""
    ci_webhook_url: str = ""
    ci_secret: str = ""


def _to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "base_url": row.base_url,
        "description": row.description,
        "ci_provider": row.ci_provider,
        "ci_webhook_url": row.ci_webhook_url,
        "has_ci_secret": bool(row.ci_secret_enc),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> list[dict]:
    return [_to_dict(row) for row in await list_products(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    payload: ProductCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_engineer)],
) -> dict:
    try:
        row = await create_product(
            session,
            code=payload.code,
            name=payload.name,
            base_url=payload.base_url,
            description=payload.description,
            ci_provider=payload.ci_provider,
            ci_webhook_url=payload.ci_webhook_url,
            ci_secret=payload.ci_secret,
            actor=user,
        )
    except ProductError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return _to_dict(row)


@router.get("/{product_id}")
async def read(
    product_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> dict:
    row = await get_product(session, product_id)
    if row is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return _to_dict(row)
