"""审计日志接口（仅 admin，D82）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.services.audit import action_label, list_logs

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[object, Depends(require_admin)],
) -> list[dict]:
    return [
        {
            "id": str(entry.id),
            "at": entry.created_at.isoformat() if entry.created_at else None,
            "username": entry.username,
            "action": entry.action,
            "action_label": action_label(entry.action),
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "detail": entry.detail,
        }
        for entry in await list_logs(session)
    ]
