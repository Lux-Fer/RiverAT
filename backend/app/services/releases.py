"""发布单（D72）：把"待发版本"和它的测试质量放在一起。

质量口径：**发布单创建之后**该版本的所有执行 —— 即"为这次发布做的验证"。
draft 阶段之前的历史执行不计入，避免拿旧结果充数。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductVersion, Release, Run

RELEASE_STATUSES = ("planned", "released", "cancelled")


class ReleaseError(ValueError):
    """发布单参数不合法。"""


async def create_release(
    session: AsyncSession,
    *,
    product_version_id: UUID,
    target_date: date,
    name: str = "",
    note: str = "",
) -> Release:
    version = await session.get(ProductVersion, product_version_id)
    if version is None:
        raise ReleaseError(f"产品版本不存在: {product_version_id}")

    release = Release(
        product_version_id=product_version_id,
        target_date=target_date,
        name=name.strip(),
        note=note.strip(),
    )
    session.add(release)
    await session.flush()
    return release


async def update_release(
    session: AsyncSession,
    release: Release,
    *,
    status: str | None = None,
    target_date: date | None = None,
    name: str | None = None,
    note: str | None = None,
) -> Release:
    if status is not None:
        if status not in RELEASE_STATUSES:
            raise ReleaseError(f"未知发布状态: {status}")
        release.status = status
        release.released_at = datetime.now(UTC) if status == "released" else None
    if target_date is not None:
        release.target_date = target_date
    if name is not None:
        release.name = name.strip()
    if note is not None:
        release.note = note.strip()

    await session.flush()
    return release


async def get_release(session: AsyncSession, release_id: UUID) -> Release | None:
    return await session.get(Release, release_id)


async def list_releases(session: AsyncSession, limit: int = 50) -> list[Release]:
    rows = await session.execute(
        select(Release).order_by(Release.target_date.desc()).limit(limit)
    )
    return list(rows.scalars().all())


async def quality(session: AsyncSession, release: Release) -> dict:
    """这次发布之后该版本执行的质量。"""

    stmt = select(Run.status, func.count()).where(
        Run.product_version_id == release.product_version_id
    )
    if release.created_at is not None:
        stmt = stmt.where(Run.created_at >= release.created_at)
    counts = dict((await session.execute(stmt.group_by(Run.status))).all())

    last_status = await session.scalar(
        select(Run.status)
        .where(Run.product_version_id == release.product_version_id)
        .order_by(Run.created_at.desc())
        .limit(1)
    )

    return {
        "runs": sum(counts.values()),
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "error": counts.get("error", 0),
        "in_flight": counts.get("queued", 0) + counts.get("running", 0),
        "last_status": last_status,
    }


async def decorate(session: AsyncSession, release: Release) -> dict:
    version = await session.get(ProductVersion, release.product_version_id)
    product = await session.get(Product, version.product_id) if version else None

    return {
        "id": str(release.id),
        "name": release.name,
        "status": release.status,
        "target_date": release.target_date.isoformat(),
        "product_code": product.code if product else None,
        "product_name": product.name if product else None,
        "version": version.version if version else None,
        "quality": await quality(session, release),
    }


async def upcoming(session: AsyncSession, *, days: int = 7) -> list[dict]:
    """今天起 N 天内计划发布的版本（按日期升序）。"""

    today = datetime.now(UTC).date()
    horizon = today + timedelta(days=days)
    rows = await session.execute(
        select(Release)
        .where(
            Release.status == "planned",
            Release.target_date >= today,
            Release.target_date <= horizon,
        )
        .order_by(Release.target_date.asc())
        .limit(10)
    )
    return [await decorate(session, release) for release in rows.scalars().all()]


async def decorated_list(session: AsyncSession) -> list[dict]:
    return [await decorate(session, release) for release in await list_releases(session)]
