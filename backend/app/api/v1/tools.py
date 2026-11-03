"""v1.1 工具接口（D99）：上传、列表、审核。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_engineer, require_user
from app.db.session import get_session
from app.models import User
from app.services.tools import (
    MAX_BUNDLE_BYTES,
    ToolError,
    approve_tool,
    get_tool,
    list_tools,
    register_tool,
    reject_tool,
)

router = APIRouter(prefix="/tools", tags=["tools"])


def _to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "version": row.version,
        "description": row.description,
        "status": row.status,
        "sha256": row.bundle_sha256,
        "input_schema": (row.manifest or {}).get("input_schema"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
    }


@router.get("")
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
    status_filter: str | None = None,
) -> list[dict]:
    return [
        _to_dict(row)
        for row in await list_tools(session, status=status_filter or None)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    file: Annotated[UploadFile, File()],
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_engineer)],
) -> dict:
    data = await file.read()
    if len(data) > MAX_BUNDLE_BYTES:
        raise HTTPException(status_code=413, detail="工具包超过 50 MiB")

    try:
        tool = await register_tool(session, data=data, actor=user)
    except ToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return _to_dict(tool)


async def _load(session: AsyncSession, tool_id: UUID):
    tool = await get_tool(session, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    return tool


@router.post("/{tool_id}/approve")
async def approve(
    tool_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict:
    tool = await _load(session, tool_id)
    await approve_tool(session, tool, actor=admin)
    await session.commit()
    return _to_dict(tool)


@router.post("/{tool_id}/reject")
async def reject(
    tool_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict:
    tool = await _load(session, tool_id)
    await reject_tool(session, tool, actor=admin)
    await session.commit()
    return _to_dict(tool)
