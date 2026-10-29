"""执行相关的 HTTP 接口（v1 最小集）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.runs import RunError, execute_plan, get_run, list_runs, list_steps

router = APIRouter(prefix="/runs", tags=["runs"])


class RunCreate(BaseModel):
    plan_id: UUID
    trigger: str = "manual"


class StepOut(BaseModel):
    node_key: str
    status: str
    exit_code: int | None = None
    duration_ms: int | None = None
    reason: str | None = None


class RunOut(BaseModel):
    id: UUID
    status: str
    trigger: str
    steps: list[StepOut] = []


class RunSummary(BaseModel):
    id: UUID
    status: str
    trigger: str


async def _to_run_out(session: AsyncSession, run) -> RunOut:
    steps = await list_steps(session, run.id)
    return RunOut(
        id=run.id,
        status=run.status,
        trigger=run.trigger,
        steps=[
            StepOut(
                node_key=step.node_key,
                status=step.status,
                exit_code=step.exit_code,
                duration_ms=step.duration_ms,
                reason=step.reason,
            )
            for step in steps
        ],
    )


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunOut:
    try:
        run = await execute_plan(session, payload.plan_id, trigger=payload.trigger)
    except RunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return await _to_run_out(session, run)


@router.get("", response_model=list[RunSummary])
async def read_runs(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RunSummary]:
    return [
        RunSummary(id=run.id, status=run.status, trigger=run.trigger)
        for run in await list_runs(session)
    ]


@router.get("/{run_id}", response_model=RunOut)
async def read_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunOut:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    return await _to_run_out(session, run)
