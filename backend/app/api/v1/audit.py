"""审计日志接口（仅 admin，D82/D85）。"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.services.audit import action_label, list_logs

router = APIRouter(prefix="/audit", tags=["audit"])


def _to_dict(entry) -> dict:
    return {
        "id": str(entry.id),
        "at": entry.created_at.isoformat() if entry.created_at else None,
        "username": entry.username,
        "action": entry.action,
        "action_label": action_label(entry.action),
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "detail": entry.detail,
    }


@router.get("")
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[object, Depends(require_admin)],
    username: str | None = None,
    action: str | None = None,
) -> list[dict]:
    logs = await list_logs(session, username=username or None, action=action or None)
    return [_to_dict(entry) for entry in logs]


@router.get("/export.csv")
async def export_csv(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[object, Depends(require_admin)],
    username: str | None = None,
    action: str | None = None,
) -> Response:
    """导出当前筛选结果为 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""

    logs = await list_logs(
        session, username=username or None, action=action or None, limit=5000
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "操作人", "动作", "对象类型", "对象ID", "详情"])
    for entry in logs:
        writer.writerow(
            [
                entry.created_at.isoformat() if entry.created_at else "",
                entry.username,
                action_label(entry.action),
                entry.target_type,
                entry.target_id or "",
                entry.detail,
            ]
        )

    payload = buffer.getvalue().encode("utf-8-sig")
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="riverat-audit.csv"'},
    )
