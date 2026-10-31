"""产品目录：产品树、版本、版本组成（D4/D5）。

约束放在服务层并给出可读错误，数据库唯一约束是最后一道保险：

* 产品编码唯一；
* 同一产品下版本号唯一；
* 版本组成：子版本必须属于声明的子产品、不能包含自己、同一子产品只能锁一个版本。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductVersion, VersionComponent


class CatalogError(ValueError):
    """目录操作不合法（重名、引用不存在、组成非法等）。"""


async def create_product(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    parent_id: UUID | None = None,
    department: str | None = None,
) -> Product:
    if parent_id is not None:
        parent = await session.get(Product, parent_id)
        if parent is None:
            raise CatalogError(f"父产品不存在: {parent_id}")

    existing = await session.scalar(select(Product).where(Product.code == code))
    if existing is not None:
        raise CatalogError(f"产品编码已存在: {code}")

    product = Product(code=code, name=name, parent_id=parent_id, department=department)
    session.add(product)
    await session.flush()
    return product


async def product_tree(session: AsyncSession) -> list[dict]:
    """返回嵌套结构：[{product, children: [...]}]，按 code 排序。"""

    products = list(
        (await session.execute(select(Product).order_by(Product.code))).scalars().all()
    )
    grouped: dict[UUID | None, list[Product]] = {}
    for product in products:
        grouped.setdefault(product.parent_id, []).append(product)

    def build(parent_id: UUID | None) -> list[dict]:
        return [
            {"product": product, "children": build(product.id)}
            for product in grouped.get(parent_id, [])
        ]

    return build(None)


async def list_versions(session: AsyncSession, product_id: UUID) -> list[ProductVersion]:
    result = await session.execute(
        select(ProductVersion)
        .where(ProductVersion.product_id == product_id)
        .order_by(ProductVersion.version)
    )
    return list(result.scalars().all())


async def all_versions_with_products(session: AsyncSession) -> list[dict]:
    """页面下拉框用：所有版本，附带所属产品。"""

    rows = (
        await session.execute(
            select(ProductVersion, Product)
            .join(Product, Product.id == ProductVersion.product_id)
            .order_by(Product.code, ProductVersion.version)
        )
    ).all()
    return [{"product": product, "version": version} for version, product in rows]


async def create_version(
    session: AsyncSession, *, product_id: UUID, version: str
) -> ProductVersion:
    product = await session.get(Product, product_id)
    if product is None:
        raise CatalogError(f"产品不存在: {product_id}")

    existing = await session.scalar(
        select(ProductVersion).where(
            ProductVersion.product_id == product_id,
            ProductVersion.version == version,
        )
    )
    if existing is not None:
        raise CatalogError(f"产品 {product.code} 已有版本 {version}")

    row = ProductVersion(product_id=product_id, version=version)
    session.add(row)
    await session.flush()
    return row


async def add_component(
    session: AsyncSession,
    *,
    parent_version_id: UUID,
    child_product_id: UUID,
    child_version_id: UUID,
) -> VersionComponent:
    parent = await session.get(ProductVersion, parent_version_id)
    if parent is None:
        raise CatalogError(f"父版本不存在: {parent_version_id}")

    child_version = await session.get(ProductVersion, child_version_id)
    if child_version is None:
        raise CatalogError(f"子版本不存在: {child_version_id}")

    if child_version.product_id != child_product_id:
        raise CatalogError("子版本不属于声明的子产品")

    if parent_version_id == child_version_id:
        raise CatalogError("版本不能包含自己")

    duplicate = await session.scalar(
        select(VersionComponent).where(
            VersionComponent.parent_version_id == parent_version_id,
            VersionComponent.child_product_id == child_product_id,
        )
    )
    if duplicate is not None:
        raise CatalogError("该子产品在这个父版本里已经锁定了一个版本")

    row = VersionComponent(
        parent_version_id=parent_version_id,
        child_product_id=child_product_id,
        child_version_id=child_version_id,
    )
    session.add(row)
    await session.flush()
    return row


async def tree_with_versions(session: AsyncSession) -> list[dict]:
    """产品树 + 每个产品下的版本，供页面直接渲染。"""

    products = list(
        (await session.execute(select(Product).order_by(Product.code))).scalars().all()
    )
    versions = list(
        (
            await session.execute(
                select(ProductVersion).order_by(ProductVersion.version)
            )
        )
        .scalars()
        .all()
    )
    versions_by_product: dict[UUID, list[ProductVersion]] = {}
    for row in versions:
        versions_by_product.setdefault(row.product_id, []).append(row)

    grouped: dict[UUID | None, list[Product]] = {}
    for product in products:
        grouped.setdefault(product.parent_id, []).append(product)

    def build(parent_id: UUID | None) -> list[dict]:
        return [
            {
                "product": product,
                "versions": versions_by_product.get(product.id, []),
                "children": build(product.id),
            }
            for product in grouped.get(parent_id, [])
        ]

    return build(None)


async def version_detail(session: AsyncSession, version_id: UUID) -> dict | None:
    version = await session.get(ProductVersion, version_id)
    if version is None:
        return None

    product = await session.get(Product, version.product_id)
    rows = (
        await session.execute(
            select(VersionComponent, Product, ProductVersion)
            .join(Product, Product.id == VersionComponent.child_product_id)
            .join(
                ProductVersion, ProductVersion.id == VersionComponent.child_version_id
            )
            .where(VersionComponent.parent_version_id == version_id)
            .order_by(Product.code)
        )
    ).all()

    return {
        "version": version,
        "product": product,
        "components": [
            {"product": child_product, "version": child_version}
            for _row, child_product, child_version in rows
        ],
    }
