"""发布单页面：列表 + 新建 + 标记已发布。"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.catalog import all_versions_with_products
from app.services.releases import (
    ReleaseError,
    create_release,
    decorate,
    decorated_list,
    get_release,
    runs_for_release,
    update_release,
)
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["release-pages"])


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="releases.html",
        context={
            "releases": await decorated_list(session),
            "versions": await all_versions_with_products(session),
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/releases", response_class=HTMLResponse)
async def releases_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render(request, session, user)


@router.get("/releases/{release_id}", response_class=HTMLResponse)
async def release_detail_page(
    release_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    release = await get_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="发布单不存在")

    return templates.TemplateResponse(
        request=request,
        name="release_detail.html",
        context={
            "release": await decorate(session, release),
            "runs": await runs_for_release(session, release),
            "user": user,
        },
    )


@router.post("/releases", dependencies=[Depends(require_csrf)])
async def create_release_form(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    product_version_id: Annotated[str, Form()],
    target_date: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await create_release(
            session,
            product_version_id=UUID(product_version_id),
            target_date=date.fromisoformat(target_date),
            name=name,
            note=note,
        )
    except (ReleaseError, ValueError) as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/releases", status_code=303)


@router.post("/releases/{release_id}/status", dependencies=[Depends(require_csrf)])
async def update_release_form(
    release_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[str, Form()],
) -> HTMLResponse:
    release = await get_release(session, release_id)
    if release is None:
        return await _render(request, session, user, error="发布单不存在")

    try:
        await update_release(session, release, status=status)
    except ReleaseError as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/releases", status_code=303)
