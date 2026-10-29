"""服务端渲染的极简页面（v1 只做"看结果"）。

HTMX 等前端交互等页面真正长起来再引入；现在只依赖 Jinja2。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR
from app.db.session import get_session
from app.services.runs import get_run, list_runs, list_steps

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    runs = await list_runs(session)
    return templates.TemplateResponse(
        request=request, name="runs.html", context={"runs": runs}
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(
    run_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    steps = await list_steps(session, run.id)
    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={"run": run, "steps": steps},
    )
