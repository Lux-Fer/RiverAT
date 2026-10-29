"""服务端渲染的极简页面。

登录页公开；其余页面都要求登录（未登录会被 main 的 401 处理器跳到 /login）。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import COOKIE_NAME, get_session_store, require_user
from app.core.config import BASE_DIR, get_settings
from app.core.sessions import SessionStore
from app.db.session import get_session
from app.models import User
from app.services.auth import AuthError
from app.services.auth import login as auth_login
from app.services.catalog import tree_with_versions, version_detail
from app.services.runs import get_run, list_runs, list_steps

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": None}
    )


@router.post("/login", response_class=HTMLResponse)
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

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
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


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    tree = await tree_with_versions(session)
    return templates.TemplateResponse(
        request=request, name="products.html", context={"tree": tree, "user": user}
    )


@router.get("/versions/{version_id}", response_class=HTMLResponse)
async def version_page(
    version_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    detail = await version_detail(session, version_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return templates.TemplateResponse(
        request=request,
        name="version_detail.html",
        context={"detail": detail, "user": user},
    )


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    runs = await list_runs(session)
    return templates.TemplateResponse(
        request=request, name="runs.html", context={"runs": runs, "user": user}
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(
    run_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    steps = await list_steps(session, run.id)
    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={"run": run, "steps": steps, "user": user},
    )
