"""HTTP 依赖：会话存储与当前用户。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.sessions import RedisSessionStore, SessionStore
from app.db.session import get_session
from app.models import User

COOKIE_NAME = "riverat_session"

# 角色等级：admin > engineer > viewer（D62）
ROLE_LEVEL = {"viewer": 1, "engineer": 2, "admin": 3}


def role_at_least(user: User, minimum: str) -> bool:
    return ROLE_LEVEL.get(user.role, 0) >= ROLE_LEVEL.get(minimum, 99)


def get_session_store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "session_store", None)
    if store is None:
        store = RedisSessionStore(get_settings().redis_url)
        request.app.state.session_store = store
    return store


async def current_user_id(
    request: Request,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> UUID | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return await store.get(token)


async def require_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录"
        )

    user_id = await store.get(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="会话已失效，请重新登录"
        )

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用"
        )
    return user


async def require_engineer(
    user: Annotated[User, Depends(require_user)],
) -> User:
    if not role_at_least(user, "engineer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要 engineer 及以上角色",
        )
    return user


async def require_admin(
    user: Annotated[User, Depends(require_user)],
) -> User:
    if not role_at_least(user, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    return user


async def optional_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = await store.get(token)
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user if user and user.is_active else None
