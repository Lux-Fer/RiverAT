"""v1.1 任务页面（M4）：工作流三列 + 任务详情。"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.tasks import (
    TaskError,
    approve_task,
    cancel_task,
    get_task,
    list_tasks,
    steps_for,
    update_step_args,
)
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
    tasks = await list_tasks(session)
    return templates.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "draft": [task for task in tasks if task.status == "draft"],
            "active": [
                task for task in tasks if task.status in ("queued", "running")
            ],
            "done": [
                task
                for task in tasks
                if task.status in ("passed", "failed", "error", "skipped", "cancelled")
            ],
            "user": user,
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
    return templates.TemplateResponse(
        request=request,
        name="task_detail.html",
        context={
            "task": task,
            "steps": steps,
            "cases": [
                {"step": step, **case}
                for step in steps
                for case in (step.output or {}).get("cases", [])
            ],
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
