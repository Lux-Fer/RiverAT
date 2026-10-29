"""登录 / 登出 / 当前用户。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import COOKIE_NAME, get_session_store, require_user
from app.core.config import get_settings
from app.core.sessions import SessionStore
from app.db.session import get_session
from app.models import User
from app.services.auth import AuthError, login

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: str


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )


@router.post("/login", response_model=UserOut)
async def login_endpoint(
    payload: LoginIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> UserOut:
    settings = get_settings()
    try:
        user, token = await login(
            session,
            store,
            username=payload.username,
            password=payload.password,
            ttl_seconds=settings.session_ttl_seconds,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return _to_out(user)


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(require_user)]) -> UserOut:
    return _to_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await store.delete(token)
    response.delete_cookie(COOKIE_NAME, path="/")
