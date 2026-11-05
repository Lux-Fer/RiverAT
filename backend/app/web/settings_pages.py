"""v1.1 设置页：模型端点（D97）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.services.audit import action_label, list_logs
from app.services.llm import LlmError, get_active, save_config, test_connection
from app.services.users import list_users
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["settings-pages"])


@router.get("/settings", response_class=HTMLResponse)
async def settings_index(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    config = await get_active(session)
    users = await list_users(session)
    logs = await list_logs(session, limit=200)
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "config": config,
            "users": users,
            "admin_count": sum(1 for item in users if item.role == "admin"),
            "engineer_count": sum(1 for item in users if item.role == "engineer"),
            "viewer_count": sum(1 for item in users if item.role == "viewer"),
            "log_count": len(logs),
            "latest": logs[0] if logs else None,
            "action_label": action_label,
            "user": user,
        },
    )


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    *,
    error: str | None = None,
    message: str | None = None,
    tested: dict | None = None,
) -> HTMLResponse:
    config = await get_active(session)
    return templates.TemplateResponse(
        request=request,
        name="settings_llm.html",
        context={
            "config": config,
            "error": error,
            "message": message,
            "tested": tested,
            "user": user,
        },
        status_code=422 if error else 200,
    )


@router.get("/settings/llm", response_class=HTMLResponse)
async def llm_settings_page(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render(request, session, user)


@router.post(
    "/settings/llm",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def llm_settings_save(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    base_url: Annotated[str, Form()],
    model: Annotated[str, Form()],
    api_key: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        current = await get_active(session)
        key = api_key.strip() or (current.api_key if current else None)
        await save_config(
            session,
            base_url=base_url,
            model=model,
            api_key=key,
            actor=user,
        )
    except LlmError as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return await _render(request, session, user, message="已保存")


@router.post(
    "/settings/llm/test",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def llm_settings_test(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    result = await test_connection(session)
    return await _render(request, session, user, tested=result)
