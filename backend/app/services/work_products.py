"""v1.1 被测产品（D100）：注册地址与 CI 配置占位。"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.models import User, WorkProduct

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PRODUCT_STATUSES = {"active", "archived"}


class ProductError(ValueError):
    """产品注册参数不合法。"""


def _validate_fields(*, name: str, base_url: str) -> None:
    if not name:
        raise ProductError("产品名称不能为空")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ProductError("产品地址必须以 http:// 或 https:// 开头")


async def create_product(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    base_url: str = "",
    description: str = "",
    ci_provider: str = "",
    ci_webhook_url: str = "",
    ci_secret: str = "",
    actor: User | None = None,
) -> WorkProduct:
    code = code.strip()
    name = name.strip()
    if not CODE_RE.match(code):
        raise ProductError("产品编码只能包含字母、数字、点、下划线、连字符（最长 64）")
    _validate_fields(name=name, base_url=base_url)

    existing = await session.scalar(
        select(WorkProduct).where(WorkProduct.code == code)
    )
    if existing is not None:
        raise ProductError(f"产品编码已存在: {code}")

    row = WorkProduct(
        code=code,
        name=name,
        base_url=base_url.strip(),
        description=description.strip(),
        ci_provider=ci_provider.strip(),
        ci_webhook_url=ci_webhook_url.strip(),
        ci_secret_enc=encrypt(ci_secret) if ci_secret else "",
        status="active",
        created_by=actor.id if actor else None,
    )
    session.add(row)
    await session.flush()
    return row


async def update_product(
    session: AsyncSession,
    product: WorkProduct,
    *,
    name: str | None = None,
    base_url: str | None = None,
    description: str | None = None,
    ci_provider: str | None = None,
    ci_webhook_url: str | None = None,
    ci_secret: str | None = None,
    actor: User | None = None,
) -> WorkProduct:
    next_name = name.strip() if name is not None else product.name
    next_url = base_url.strip() if base_url is not None else product.base_url
    _validate_fields(name=next_name, base_url=next_url)

    product.name = next_name
    product.base_url = next_url
    if description is not None:
        product.description = description.strip()
    if ci_provider is not None:
        product.ci_provider = ci_provider.strip()
    if ci_webhook_url is not None:
        product.ci_webhook_url = ci_webhook_url.strip()
    if ci_secret:
        product.ci_secret_enc = encrypt(ci_secret)
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="product.update",
        target_type="product",
        target_id=str(product.id),
        detail={
            "code": product.code,
            "fields": [
                key
                for key, value in {
                    "name": name,
                    "base_url": base_url,
                    "description": description,
                    "ci_provider": ci_provider,
                    "ci_webhook_url": ci_webhook_url,
                    "ci_secret": ci_secret,
                }.items()
                if value is not None and value != ""
            ],
        },
    )
    return product


async def set_product_status(
    session: AsyncSession,
    product: WorkProduct,
    status: str,
    *,
    actor: User | None = None,
) -> WorkProduct:
    if status not in PRODUCT_STATUSES:
        raise ProductError(f"产品状态不合法：{status}")
    product.status = status
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="product.archive" if status == "archived" else "product.restore",
        target_type="product",
        target_id=str(product.id),
        detail={"code": product.code, "status": status},
    )
    return product


async def list_products(
    session: AsyncSession, *, include_archived: bool = False
) -> list[WorkProduct]:
    stmt = select(WorkProduct).order_by(WorkProduct.code)
    if not include_archived:
        stmt = stmt.where(WorkProduct.status == "active")
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def get_product(session: AsyncSession, product_id: UUID) -> WorkProduct | None:
    return await session.get(WorkProduct, product_id)
