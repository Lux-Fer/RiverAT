"""计划相关接口：创建（JSON / YAML）与列表。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.plans import PlanError, create_plan, list_plans

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanCreate(BaseModel):
    product_version_id: UUID
    name: str
    # 对象（JSON）或字符串（YAML）都接受
    definition: dict | str


class PlanOut(BaseModel):
    id: UUID
    product_version_id: UUID
    name: str
    revision: int
    definition: dict


def _to_out(plan) -> PlanOut:
    return PlanOut(
        id=plan.id,
        product_version_id=plan.product_version_id,
        name=plan.name,
        revision=plan.revision,
        definition=plan.definition,
    )


@router.post("", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create(
    payload: PlanCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanOut:
    try:
        plan = await create_plan(
            session,
            product_version_id=payload.product_version_id,
            name=payload.name,
            definition=payload.definition,
        )
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return _to_out(plan)


@router.get("", response_model=list[PlanOut])
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PlanOut]:
    return [_to_out(plan) for plan in await list_plans(session)]
