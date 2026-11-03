"""用户管理接口（仅 admin）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_store, require_admin
from app.core.sessions import SessionStore
from app.db.session import get_session
from app.models import User
from app.services.users import (
    UserError,
    create_user_admin,
    get_user,
    list_users,
    update_user_admin,
)

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "engineer"
    display_name: str = ""


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    display_name: str | None = None
    # 管理员重置密码（D71）；不填就不动
    password: str | None = None


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get("", response_model=list[UserOut])
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[UserOut]:
    return [_to_out(user) for user in await list_users(session)]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> UserOut:
    try:
        user = await create_user_admin(
            session,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            display_name=payload.display_name,
            actor=admin,
        )
    except UserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _to_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def patch(
    user_id: UUID,
    payload: UserPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> UserOut:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        await update_user_admin(
            session,
            user,
            actor=admin,
            role=payload.role,
            is_active=payload.is_active,
            display_name=payload.display_name,
            password=payload.password,
        )
    except UserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    if payload.password:
        # 改密码即下线：把该用户所有已登录会话踢掉（D74）
        await store.revoke_user(user.id)
    return _to_out(user)
