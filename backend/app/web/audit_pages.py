"""审计日志页面（仅 admin，D82）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.services.audit import action_label, list_logs
from app.web.templates import templates

router = APIRouter(tags=["audit-pages"])


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    logs = await list_logs(session)
    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "logs": logs,
            "action_label": action_label,
            "user": user,
        },
    )
