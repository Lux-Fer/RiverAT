"""v1.1 产品注册页面（D100）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.work_products import (
    ProductError,
    create_product,
    list_products,
)
from app.web.csrf import require_csrf
from app.web.templates import templates

router = APIRouter(tags=["product-pages"])


async def _render(
    request: Request,
    session: AsyncSession,
    user: User,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="work_products.html",
        context={
            "products": await list_products(session),
            "user": user,
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/", include_in_schema=False)
async def home() -> RedirectResponse:
    return RedirectResponse("/products", status_code=303)


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return await _render(request, session, user)


@router.post(
    "/products",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def create_product_form(
    request: Request,
    user: Annotated[User, Depends(require_engineer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    base_url: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    ci_provider: Annotated[str, Form()] = "",
    ci_webhook_url: Annotated[str, Form()] = "",
    ci_secret: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await create_product(
            session,
            code=code,
            name=name,
            base_url=base_url,
            description=description,
            ci_provider=ci_provider,
            ci_webhook_url=ci_webhook_url,
            ci_secret=ci_secret,
            actor=user,
        )
    except ProductError as exc:
        return await _render(request, session, user, error=str(exc))

    await session.commit()
    return RedirectResponse("/products", status_code=303)
