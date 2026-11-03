"""v1.1 登录 / 退出页面（旧页面已下线，只保留认证入口）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import COOKIE_NAME, get_session_store
from app.core.config import get_settings
from app.core.sessions import SessionStore
from app.db.session import get_session
from app.services.auth import AuthError
from app.services.auth import login as auth_login
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["auth-pages"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": None}
    )


@router.post("/login", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> HTMLResponse:
    settings = get_settings()
    try:
        _, token = await auth_login(
            session,
            store,
            username=username,
            password=password,
            ttl_seconds=settings.session_ttl_seconds,
        )
    except AuthError:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "用户名或密码错误", "username": username},
            status_code=401,
        )

    response = RedirectResponse("/products", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout_submit(
    request: Request,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> RedirectResponse:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await store.delete(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
