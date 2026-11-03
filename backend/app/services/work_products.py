"""v1.1 被测产品（D100）：注册地址与 CI 配置占位。"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.models import User, WorkProduct

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ProductError(ValueError):
    """产品注册参数不合法。"""


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
    if not name:
        raise ProductError("产品名称不能为空")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ProductError("产品地址必须以 http:// 或 https:// 开头")

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
        created_by=actor.id if actor else None,
    )
    session.add(row)
    await session.flush()
    return row


async def list_products(session: AsyncSession) -> list[WorkProduct]:
    rows = await session.execute(select(WorkProduct).order_by(WorkProduct.code))
    return list(rows.scalars().all())


async def get_product(session: AsyncSession, product_id: UUID) -> WorkProduct | None:
    return await session.get(WorkProduct, product_id)
