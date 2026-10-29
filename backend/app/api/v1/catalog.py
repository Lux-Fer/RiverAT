"""产品目录接口：产品树、版本、版本组成。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.catalog import (
    CatalogError,
    add_component,
    create_product,
    create_version,
    list_versions,
    product_tree,
    version_detail,
)

router = APIRouter(tags=["catalog"])


class ProductCreate(BaseModel):
    code: str
    name: str
    parent_id: UUID | None = None
    department: str | None = None


class ProductOut(BaseModel):
    id: UUID
    code: str
    name: str
    parent_id: UUID | None = None


class ProductNode(BaseModel):
    id: UUID
    code: str
    name: str
    children: list[ProductNode] = []


class VersionCreate(BaseModel):
    version: str


class VersionOut(BaseModel):
    id: UUID
    product_id: UUID
    version: str
    state: str


class ComponentCreate(BaseModel):
    child_product_id: UUID
    child_version_id: UUID


class ComponentOut(BaseModel):
    product_id: UUID
    product_code: str
    version_id: UUID
    version: str


class VersionDetailOut(BaseModel):
    id: UUID
    product_id: UUID
    product_code: str
    version: str
    components: list[ComponentOut]


def _version_out(row) -> VersionOut:
    return VersionOut(
        id=row.id, product_id=row.product_id, version=row.version, state=row.state
    )


def _to_nodes(nodes: list[dict]) -> list[ProductNode]:
    return [
        ProductNode(
            id=node["product"].id,
            code=node["product"].code,
            name=node["product"].name,
            children=_to_nodes(node["children"]),
        )
        for node in nodes
    ]


@router.post(
    "/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED
)
async def create_product_endpoint(
    payload: ProductCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductOut:
    try:
        product = await create_product(
            session,
            code=payload.code,
            name=payload.name,
            parent_id=payload.parent_id,
            department=payload.department,
        )
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return ProductOut(
        id=product.id,
        code=product.code,
        name=product.name,
        parent_id=product.parent_id,
    )


@router.get("/products", response_model=list[ProductNode])
async def list_products(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProductNode]:
    return _to_nodes(await product_tree(session))


@router.post(
    "/products/{product_id}/versions",
    response_model=VersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_version_endpoint(
    product_id: UUID,
    payload: VersionCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VersionOut:
    try:
        row = await create_version(
            session, product_id=product_id, version=payload.version
        )
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _version_out(row)


@router.get("/products/{product_id}/versions", response_model=list[VersionOut])
async def list_versions_endpoint(
    product_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VersionOut]:
    return [_version_out(row) for row in await list_versions(session, product_id)]


@router.post(
    "/versions/{version_id}/components",
    response_model=ComponentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_component_endpoint(
    version_id: UUID,
    payload: ComponentCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ComponentOut:
    try:
        await add_component(
            session,
            parent_version_id=version_id,
            child_product_id=payload.child_product_id,
            child_version_id=payload.child_version_id,
        )
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()

    detail = await version_detail(session, version_id)
    assert detail is not None
    component = detail["components"][-1]
    return ComponentOut(
        product_id=component["product"].id,
        product_code=component["product"].code,
        version_id=component["version"].id,
        version=component["version"].version,
    )


@router.get("/versions/{version_id}", response_model=VersionDetailOut)
async def version_detail_endpoint(
    version_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VersionDetailOut:
    detail = await version_detail(session, version_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return VersionDetailOut(
        id=detail["version"].id,
        product_id=detail["product"].id,
        product_code=detail["product"].code,
        version=detail["version"].version,
        components=[
            ComponentOut(
                product_id=item["product"].id,
                product_code=item["product"].code,
                version_id=item["version"].id,
                version=item["version"].version,
            )
            for item in detail["components"]
        ],
    )
