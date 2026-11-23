"""v1.1 助手接口（M3）：对话 → 任务草案，不执行。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer
from app.db.session import get_session
from app.models import User
from app.services.llm import LlmError
from app.services.tasks import TaskError, propose_task, steps_for
from app.worker.task_dispatch import get_task_dispatcher

router = APIRouter(prefix="/assistant", tags=["assistant"])


class DraftRequest(BaseModel):
    text: str
    product_id: UUID | None = None


@router.post("/messages", status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: DraftRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_engineer)],
) -> dict:
    try:
        task = await propose_task(
            session,
            text=payload.text,
            product_id=payload.product_id,
            actor=user,
        )
    except TaskError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await session.commit()
    if task.status == "queued":
        await get_task_dispatcher(request).dispatch(task.id, session)
        await session.commit()
    steps = await steps_for(session, task.id)
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "reply": task.draft.get("reply", ""),
        "errors": task.draft.get("errors", []),
        "steps": [
            {
                "seq": step.seq,
                "tool": step.tool_name,
                "version": step.tool_version,
                "args": step.args,
                "status": step.status,
            }
            for step in steps
        ],
    }
