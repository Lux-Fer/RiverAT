"""v1.1 任务页面（M4）：工作流三列 + 任务详情。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_user
from app.db.session import get_session
from app.models import User
from app.services.tasks import get_task, list_tasks, steps_for
from app.web.templates import templates

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
        },
    )
