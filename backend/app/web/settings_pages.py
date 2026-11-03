"""v1.1 设置页：模型端点（D97）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.services.llm import LlmError, get_active, save_config, test_connection
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["settings-pages"])


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
        await save_config(
            session,
            base_url=base_url,
            model=model,
            api_key=api_key or None,
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
