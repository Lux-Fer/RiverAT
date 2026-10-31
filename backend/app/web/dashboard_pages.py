"""领导页（只读）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_user
from app.core.config import BASE_DIR
from app.db.session import get_session
from app.models import User
from app.services.dashboard import summary

router = APIRouter(tags=["dashboard-pages"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"data": await summary(session), "user": user},
    )
