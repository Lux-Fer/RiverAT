"""V0.2.2 知识控制台：查看、筛选、人工审核和 TTL 清理。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_user
from app.db.session import get_session
from app.models import KnowledgeItem, User
from app.services.knowledge_base import (
    console_counts,
    console_items,
    console_kinds,
    console_products,
    expire_knowledge,
    retrieval_metrics,
    set_knowledge_status,
)
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["knowledge-pages"])


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    *,
    q: str = "",
    scope: str = "",
    status: str = "",
    kind: str = "",
    product: str = "",
) -> HTMLResponse:
    product_id = None
    if product:
        try:
            product_id = UUID(product)
        except ValueError:
            product = ""
    items = await console_items(
        session,
        user_id=user.id,
        query=q,
        scope=scope,
        status=status,
        kind=kind,
        product_id=product_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="knowledge.html",
        context={
            "items": items,
            "counts": await console_counts(session, user_id=user.id),
            "metrics": await retrieval_metrics(session, days=30),
            "products": await console_products(session),
            "kinds": await console_kinds(session, user_id=user.id),
            "q": q,
            "scope": scope,
            "status": status,
            "kind": kind,
            "product": product,
            "saved": request.query_params.get("saved") == "1",
            "user": user,
        },
    )


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query()] = "",
    scope: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    kind: Annotated[str, Query()] = "",
    product: Annotated[str, Query()] = "",
) -> HTMLResponse:
    return await _render(
        request,
        session,
        user,
        q=q,
        scope=scope,
        status=status,
        kind=kind,
        product=product,
    )


@router.post(
    "/knowledge/{item_id}/status",
    dependencies=[Depends(require_csrf)],
)
async def review_knowledge(
    item_id: UUID,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[str, Form()],
) -> RedirectResponse:
    item = await session.get(KnowledgeItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="知识不存在")
    if item.scope == "user" and item.owner_id != user.id:
        raise HTTPException(status_code=404, detail="知识不存在")
    try:
        await set_knowledge_status(session, item, status, actor=user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return RedirectResponse("/knowledge?saved=1", status_code=303)


@router.post("/knowledge/expire", dependencies=[Depends(require_csrf)])
async def expire_knowledge_action(
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    await expire_knowledge(session, actor=user)
    await session.commit()
    return RedirectResponse("/knowledge?saved=1", status_code=303)
