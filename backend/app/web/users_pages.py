"""用户管理页面（仅 admin）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.services.users import (
    UserError,
    create_user_admin,
    get_user,
    list_users,
    update_user_admin,
)

router = APIRouter(tags=["user-pages"])
from app.web.templates import templates


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={"users": await list_users(session), "user": user, "error": error},
        status_code=422 if error else 200,
    )


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render(request, session, user)


@router.post("/users")
async def create_user_form(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()] = "engineer",
    display_name: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await create_user_admin(
            session,
            username=username.strip(),
            password=password,
            role=role,
            display_name=display_name.strip(),
        )
    except UserError as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}")
async def update_user_form(
    user_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    role: Annotated[str, Form()],
    is_active: Annotated[str, Form()] = "true",
    display_name: Annotated[str, Form()] = "",
) -> HTMLResponse:
    target = await get_user(session, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        await update_user_admin(
            session,
            target,
            actor=user,
            role=role,
            is_active=is_active.lower() == "true",
            display_name=display_name or None,
        )
    except UserError as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/users", status_code=303)
