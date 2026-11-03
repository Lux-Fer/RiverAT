"""测试机注册与连接构造（D22）。

凭据只以密文入库；构造 transport 时再解密，且只在内存里停留。
v1 只支持密码认证，SSH key 认证留到需要时再加。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import CryptoError, decrypt, encrypt
from app.models import Host, User
from app.services.audit import record
from app.transport.base import TransportError
from app.transport.ssh import SshTransport


class HostError(ValueError):
    """测试机配置或探测失败。"""


async def create_host(
    session: AsyncSession,
    *,
    name: str,
    hostname: str,
    username: str,
    password: str,
    port: int = 22,
    auth_type: str = "password",
    os_name: str = "linux",
    actor: User | None = None,
) -> Host:
    if auth_type != "password":
        raise HostError("v1 只支持密码认证（SSH key 后续再加）")
    if not password:
        raise HostError("密码不能为空")

    existing = await session.scalar(select(Host).where(Host.name == name))
    if existing is not None:
        raise HostError(f"测试机名称已存在: {name}")

    host = Host(
        name=name,
        hostname=hostname,
        port=port,
        username=username,
        auth_type=auth_type,
        secret_encrypted=encrypt(password),
        os=os_name,
    )
    session.add(host)
    await session.flush()
    await record(
        session,
        actor=actor,
        action="host.create",
        target_type="host",
        target_id=host.id,
        detail={"hostname": hostname, "username": username},
    )
    return host


async def list_hosts(session: AsyncSession) -> list[Host]:
    result = await session.execute(select(Host).order_by(Host.name))
    return list(result.scalars().all())


async def get_host(session: AsyncSession, host_id: UUID) -> Host | None:
    return await session.get(Host, host_id)


def build_transport(host: Host) -> SshTransport:
    try:
        password = decrypt(host.secret_encrypted)
    except CryptoError as exc:
        raise HostError(str(exc)) from exc
    return SshTransport(
        host=host.hostname,
        username=host.username,
        port=host.port,
        password=password,
    )


async def probe_host(session: AsyncSession, host: Host) -> dict[str, str]:
    transport = build_transport(host)
    try:
        info = await asyncio.to_thread(transport.probe)
    except TransportError as exc:
        host.status = "offline"
        await session.flush()
        raise HostError(f"探测失败: {exc}") from exc
    finally:
        transport.close()

    host.status = "online"
    host.last_seen_at = datetime.now(UTC)
    await session.flush()
    return {"os": info.os, "arch": info.arch, "hostname": info.hostname}
