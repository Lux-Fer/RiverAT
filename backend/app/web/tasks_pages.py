"""v1.1 任务页面（M4）：工作流三列 + 任务详情。"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.task_board import build_task_board
from app.services.task_detail import build_task_detail
from app.services.tasks import (
    TaskError,
    approve_task,
    cancel_task,
    create_manual_task,
    get_task,
    recover_task,
    rerun_task,
    stale_tasks,
    steps_for,
    update_step_args,
)
from app.services.tools import available_tools
from app.services.work_products import list_products
from app.web.csrf import require_csrf
from app.web.templates import templates
from app.worker.task_dispatch import get_task_dispatcher

router = APIRouter(tags=["task-pages"])


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    board = await build_task_board(session)
    return templates.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "board": board,
            "user": user,
            "stale": await stale_tasks(session) if user.role == "admin" else [],
        },
    )


async def _render_detail(
    request: Request,
    session: AsyncSession,
    user: User,
    task,
    *,
    error: str | None = None,
) -> HTMLResponse:
    steps = await steps_for(session, task.id)
    view = await build_task_detail(session, task, steps)
    return templates.TemplateResponse(
        request=request,
        name="task_detail.html",
        context={
            "task": task,
            "view": view,
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/tasks/new", response_class=HTMLResponse)
async def manual_task_page(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="manual_task.html",
        context={
            "products": await list_products(session),
            "tools": await available_tools(session),
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail_page(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return await _render_detail(request, session, user, task)


@router.post(
    "/tasks/{task_id}/steps/{step_id}/args",
    dependencies=[Depends(require_csrf)],
)
async def update_step_args_form(
    task_id: UUID,
    step_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    args: Annotated[str, Form()],
) -> HTMLResponse:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return await _render_detail(
            request, session, user, task, error=f"参数不是合法 JSON：{exc.msg}"
        )

    try:
        await update_step_args(session, task, step_id, payload, actor=user)
    except TaskError as exc:
        return await _render_detail(request, session, user, task, error=str(exc))

    await session.commit()
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)

@router.post(
    "/tasks/{task_id}/approve",
    dependencies=[Depends(require_csrf)],
)
async def approve_task_form(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        await approve_task(session, task, actor=user)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    await get_task_dispatcher(request).dispatch(task.id, session)
    await session.commit()
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@router.post(
    "/tasks/{task_id}/cancel",
    dependencies=[Depends(require_csrf)],
)
async def cancel_task_form(
    task_id: UUID,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        await cancel_task(session, task, actor=user)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)

@router.post(
    "/tasks/{task_id}/rerun",
    dependencies=[Depends(require_csrf)],
)
async def rerun_task_form(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        new_task = await rerun_task(session, task, actor=user)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return RedirectResponse(f"/tasks/{new_task.id}", status_code=303)

@router.post(
    "/tasks/manual",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def manual_task_submit(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    tool_id: Annotated[UUID, Form()],
    args: Annotated[str, Form()] = "{}",
    product_id: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return await _manual_error(request, session, user, f"参数不是合法 JSON：{exc.msg}")

    try:
        task = await create_manual_task(
            session,
            tool_id=tool_id,
            args=payload,
            product_id=UUID(product_id) if product_id else None,
            title=title,
            actor=user,
        )
    except TaskError as exc:
        return await _manual_error(request, session, user, str(exc))

    await session.commit()
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


async def _manual_error(request: Request, session: AsyncSession, user: User, error: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="manual_task.html",
        context={
            "products": await list_products(session),
            "tools": await available_tools(session),
            "user": user,
            "error": error,
        },
        status_code=422,
    )

@router.post(
    "/tasks/{task_id}/recover",
    dependencies=[Depends(require_csrf)],
)
async def recover_task_form(
    task_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        await recover_task(session, task, actor=admin)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return RedirectResponse("/tasks", status_code=303)
