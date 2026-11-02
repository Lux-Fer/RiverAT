"""计划相关的页面操作：列表、创建、详情、触发执行。"""

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
from app.services.catalog import all_versions_with_products
from app.services.hosts import get_host, list_hosts
from app.services.plans import (
    PlanConflict,
    PlanError,
    create_plan,
    list_plans,
    update_plan,
)
from app.services.runs import RunError, create_run
from app.worker.dispatch import RunDispatcher, get_dispatcher

router = APIRouter(tags=["plan-pages"])
from app.web.templates import templates


async def _render_list(
    request: Request,
    session: AsyncSession,
    user: User,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="plans.html",
        context={
            "plans": await list_plans(session),
            "versions": await all_versions_with_products(session),
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/plans", response_class=HTMLResponse)
async def plans_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render_list(request, session, user)


@router.post("/plans")
async def create_plan_form(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    name: Annotated[str, Form()],
    product_version_id: Annotated[str, Form()],
    definition: Annotated[str, Form()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    try:
        plan = await create_plan(
            session,
            product_version_id=UUID(product_version_id),
            name=name,
            definition=definition,
        )
    except (PlanError, ValueError) as exc:
        return await _render_list(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse(f"/plans/{plan.id}", status_code=303)


@router.get("/plans/{plan_id}", response_class=HTMLResponse)
async def plan_detail_page(
    plan_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render_detail(request, session, plan_id, user)


async def _render_detail(
    request: Request,
    session: AsyncSession,
    plan_id: UUID,
    user: User,
    error: str | None = None,
    status_code: int = 422,
) -> HTMLResponse:
    from app.models import Plan

    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")

    return templates.TemplateResponse(
        request=request,
        name="plan_detail.html",
        context={
            "plan": plan,
            "definition_text": json.dumps(
                plan.definition, ensure_ascii=False, indent=2
            ),
            "snapshot_count": len((plan.snapshot or {}).get("nodes", [])),
            "hosts": await list_hosts(session),
            "user": user,
            "error": error,
        },
        status_code=status_code if error else 200,
    )


@router.post("/plans/{plan_id}/edit")
async def edit_plan_form(
    plan_id: UUID,
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str, Form()] = "",
    definition: Annotated[str, Form()] = "",
    expected_revision: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await update_plan(
            session,
            plan_id,
            name=name or None,
            definition=definition or None,
            expected_revision=int(expected_revision) if expected_revision else None,
        )
    except PlanConflict as exc:
        return await _render_detail(
            request, session, plan_id, user, error=str(exc), status_code=409
        )
    except PlanError as exc:
        return await _render_detail(request, session, plan_id, user, error=str(exc))

    await session.commit()
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


@router.post("/plans/{plan_id}/run")
async def run_plan_form(
    plan_id: UUID,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    dispatcher: Annotated[RunDispatcher, Depends(get_dispatcher)],
    host_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    host = None
    if host_id:
        host = await get_host(session, UUID(host_id))
        if host is None:
            raise HTTPException(status_code=404, detail="测试机不存在")

    try:
        run = await create_run(session, plan_id, host=host)
    except RunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    await dispatcher.dispatch(run.id, session)
    return RedirectResponse(f"/runs/{run.id}", status_code=303)
