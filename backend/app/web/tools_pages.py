"""v1.1 工具页面（D99）：上传、列表、审核。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.tools import (
    ToolError,
    approve_tool,
    get_tool,
    list_tools,
    register_tool,
    reject_tool,
    set_tool_status,
)
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["tool-pages"])

TOOL_RANK = {"pending": 0, "approved": 1, "disabled": 2, "rejected": 3}


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    error: str | None = None,
) -> HTMLResponse:
    tools = await list_tools(session)
    tools.sort(
        key=lambda tool: (
            TOOL_RANK.get(tool.status, 9),
            -(tool.created_at.timestamp() if tool.created_at else 0),
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="tools.html",
        context={
            "tools": tools,
            "pending_count": sum(1 for tool in tools if tool.status == "pending"),
            "approved_count": sum(1 for tool in tools if tool.status == "approved"),
            "disabled_count": sum(1 for tool in tools if tool.status == "disabled"),
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/tools", response_class=HTMLResponse)
async def tools_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render(request, session, user)


@router.post(
    "/tools",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def upload_tool_form(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File()],
) -> HTMLResponse:
    data = await file.read()
    try:
        await register_tool(session, data=data, actor=user)
    except ToolError as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/tools", status_code=303)


@router.post(
    "/tools/{tool_id}/approve",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def approve_tool_form(
    tool_id: UUID,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    decision: Annotated[str, Form()] = "approve",
) -> HTMLResponse:
    tool = await get_tool(session, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="工具不存在")

    if decision == "reject":
        await reject_tool(session, tool, actor=admin)
    else:
        await approve_tool(session, tool, actor=admin)

    await session.commit()
    return RedirectResponse("/tools", status_code=303)


@router.post(
    "/tools/{tool_id}/state",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def set_tool_state_form(
    tool_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    decision: Annotated[str, Form()] = "disable",
) -> HTMLResponse:
    tool = await get_tool(session, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="工具不存在")

    target = "approved" if decision == "enable" else "disabled"
    try:
        await set_tool_status(session, tool, target, actor=admin)
    except ToolError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return RedirectResponse("/tools", status_code=303)
