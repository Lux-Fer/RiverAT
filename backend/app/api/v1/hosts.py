"""测试机接口：注册、列表、在线探测。响应里永远不出现凭据。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_session
from app.models import User
from app.services.hosts import (
    HostError,
    create_host,
    get_host,
    list_hosts,
    probe_host,
)

router = APIRouter(prefix="/hosts", tags=["hosts"])


class HostCreate(BaseModel):
    name: str
    hostname: str
    username: str
    password: str
    port: int = 22
    auth_type: str = "password"
    os_name: str = "linux"


class HostOut(BaseModel):
    id: UUID
    name: str
    hostname: str
    port: int
    username: str
    auth_type: str
    os: str
    status: str
    last_seen_at: datetime | None = None


class ProbeOut(BaseModel):
    os: str
    arch: str
    hostname: str


def _to_out(host) -> HostOut:
    return HostOut(
        id=host.id,
        name=host.name,
        hostname=host.hostname,
        port=host.port,
        username=host.username,
        auth_type=host.auth_type,
        os=host.os,
        status=host.status,
        last_seen_at=host.last_seen_at,
    )


@router.post("", response_model=HostOut, status_code=status.HTTP_201_CREATED)
async def create(
    payload: HostCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> HostOut:
    try:
        host = await create_host(
            session,
            name=payload.name,
            hostname=payload.hostname,
            username=payload.username,
            password=payload.password,
            port=payload.port,
            auth_type=payload.auth_type,
            actor=admin,
            os_name=payload.os_name,
        )
    except HostError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _to_out(host)


@router.get("", response_model=list[HostOut])
async def index(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HostOut]:
    return [_to_out(host) for host in await list_hosts(session)]


@router.post("/{host_id}/probe", response_model=ProbeOut)
async def probe(
    host_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProbeOut:
    host = await get_host(session, host_id)
    if host is None:
        raise HTTPException(status_code=404, detail="测试机不存在")
    try:
        info = await probe_host(session, host)
    except HostError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return ProbeOut(**info)
