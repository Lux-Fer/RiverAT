"""v1.1 任务接口（M4）：确认、取消、列表、详情。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
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
)
from app.worker.task_dispatch import get_task_dispatcher

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _summary(task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "product_id": str(task.product_id) if task.product_id else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def _detail(task, steps) -> dict:
    return {
        **_summary(task),
        "request_text": task.request_text,
        "reply": (task.draft or {}).get("reply", ""),
        "errors": (task.draft or {}).get("errors", []),
        "steps": [
            {
                "seq": step.seq,
                "tool": step.tool_name,
                "version": step.tool_version,
                "args": step.args,
                "status": step.status,
                "exit_code": step.exit_code,
                "output": step.output,
                "error": step.error,
            }
            for step in steps
        ],
    }


@router.get("")
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> list[dict]:
    return [_summary(task) for task in await list_tasks(session)]


@router.get("/{task_id}")
async def read(
    task_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> dict:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _detail(task, await steps_for(session, task.id))


@router.post("/{task_id}/approve")
async def approve(
    task_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_engineer)],
) -> dict:
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
    return _detail(task, await steps_for(session, task.id))


@router.post("/{task_id}/cancel")
async def cancel(
    task_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_engineer)],
) -> dict:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        await cancel_task(session, task)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return _summary(task)
