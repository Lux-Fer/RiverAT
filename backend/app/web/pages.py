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

from app.api.deps import COOKIE_NAME, get_session_store, require_engineer, require_user
from app.core.config import BASE_DIR, get_settings
from app.core.sessions import SessionStore
from app.db.session import get_session
from app.models import User
from app.services.auth import AuthError
from app.services.auth import login as auth_login
from app.services.catalog import (
    CatalogError,
    add_component,
    all_versions_with_products,
    create_product,
    create_version,
    list_versions,
    tree_with_versions,
    version_detail,
)
from app.services.knowledge import similar_to_run
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
        context={
            "detail": detail,
            "user": user,
            "versions": await all_versions_with_products(session),
            "error": None,
        },
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
    similar = (
        await similar_to_run(session, run.id)
        if run.status in ("failed", "error")
        else []
    )
    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={"run": run, "steps": steps, "user": user, "similar": similar},
    )


# -- 表单操作：建产品 / 版本 / 版本组成 ---------------------------------


@router.post("/products")
async def create_product_form(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    parent_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await create_product(
            session,
            code=code.strip(),
            name=name.strip(),
            parent_id=UUID(parent_id) if parent_id else None,
        )
    except (CatalogError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="products.html",
            context={
                "tree": await tree_with_versions(session),
                "user": user,
                "error": str(exc),
            },
            status_code=422,
        )

    await session.commit()
    return RedirectResponse("/products", status_code=303)


@router.post("/products/{product_id}/versions")
async def create_version_form(
    product_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    version: Annotated[str, Form()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    try:
        await create_version(session, product_id=product_id, version=version.strip())
    except CatalogError as exc:
        return templates.TemplateResponse(
            request=request,
            name="products.html",
            context={
                "tree": await tree_with_versions(session),
                "user": user,
                "error": str(exc),
            },
            status_code=422,
        )

    await session.commit()
    return RedirectResponse("/products", status_code=303)


@router.post("/versions/{version_id}/components")
async def add_component_form(
    version_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    child_version_id: Annotated[str, Form()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    from app.models import ProductVersion

    child = await session.get(ProductVersion, UUID(child_version_id))
    try:
        if child is None:
            raise CatalogError("子版本不存在")
        await add_component(
            session,
            parent_version_id=version_id,
            child_product_id=child.product_id,
            child_version_id=child.id,
        )
    except CatalogError as exc:
        detail = await version_detail(session, version_id)
        return templates.TemplateResponse(
            request=request,
            name="version_detail.html",
            context={
                "detail": detail,
                "user": user,
                "versions": await all_versions_with_products(session),
                "error": str(exc),
            },
            status_code=422,
        )

    await session.commit()
    return RedirectResponse(f"/versions/{version_id}", status_code=303)


@router.get("/products/{product_id}", response_class=HTMLResponse)
async def product_versions_page(
    product_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    from app.models import Product

    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    versions = await list_versions(session, product_id)
    return templates.TemplateResponse(
        request=request,
        name="product_detail.html",
        context={"product": product, "versions": versions, "user": user},
    )
