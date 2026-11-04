"""v1.1 助手页面（M3）：对话 + 任务草案展示。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer
from app.db.session import get_session
from app.models import User
from app.services.llm import LlmError
from app.services.tasks import (
    TaskError,
    latest_draft,
    list_messages,
    list_tasks,
    propose_task,
    steps_for,
)
from app.services.tools import available_tools
from app.services.work_products import list_products
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["assistant-pages"])


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    *,
    error: str | None = None,
) -> HTMLResponse:
    draft = await latest_draft(session)
    products = await list_products(session)
    tools = await available_tools(session)
    return templates.TemplateResponse(
        request=request,
        name="assistant.html",
        context={
            "messages": await list_messages(session, limit=14),
            "draft": draft,
            "steps": await steps_for(session, draft.id) if draft else [],
            "products": products,
            "tools_count": len(tools),
            "recent": [
                task
                for task in await list_tasks(session, limit=6)
                if task.status != "draft"
            ],
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/assistant", response_class=HTMLResponse)
async def assistant_page(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render(request, session, user)


@router.post(
    "/assistant/messages",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def assistant_submit(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    text: Annotated[str, Form()],
    product_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await propose_task(
            session,
            text=text,
            product_id=UUID(product_id) if product_id else None,
            actor=user,
        )
    except (TaskError, LlmError) as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/assistant", status_code=303)
