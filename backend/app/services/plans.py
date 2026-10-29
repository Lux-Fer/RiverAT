"""计划的创建与结构校验。

计划是声明式的（D8）：平台只校验结构（字段齐备、依赖存在、无环），
不解释节点语义。``definition`` 接受 JSON 对象或 YAML 文本 —— 后者方便
用户把计划直接放进 Git。
"""

from __future__ import annotations

from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, Product, ProductVersion, VersionComponent


class PlanError(ValueError):
    """计划内容或引用不合法。"""


def parse_definition(raw: object) -> dict:
    data = yaml.safe_load(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise PlanError("definition 必须是对象或 YAML 映射")

    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise PlanError("definition.nodes 必须是数组")

    for node in nodes:
        if not isinstance(node, dict) or "key" not in node or "plugin" not in node:
            raise PlanError(f"节点缺少 key/plugin: {node!r}")

    return data


async def expand_nodes(
    session: AsyncSession,
    definition: dict,
    *,
    parent_version_id: UUID,
) -> list[dict]:
    """把 ``includes`` 展开成扁平的节点列表（D57 计划继承）。

    规则：
    * 被引用的计划必须属于**当前版本已锁定的子版本**（否则组合就没意义）；
    * 被引用计划的节点 key 加前缀，依赖一起改写，避免同名冲突；
    * 父计划自己的节点可以直接用 ``a.login`` 这样的前缀 key 跨引用。
    """

    nodes = [dict(node) for node in (definition.get("nodes") or [])]
    includes = definition.get("includes") or []
    if not isinstance(includes, list):
        raise PlanError("includes 必须是数组")

    locked = set(
        (
            await session.execute(
                select(VersionComponent.child_version_id).where(
                    VersionComponent.parent_version_id == parent_version_id
                )
            )
        )
        .scalars()
        .all()
    )

    prefixes: set[str] = set()
    for include in includes:
        if not isinstance(include, dict) or "plan_id" not in include:
            raise PlanError(f"include 缺少 plan_id: {include!r}")
        try:
            child_plan_id = UUID(str(include["plan_id"]))
        except ValueError as exc:
            raise PlanError(f"plan_id 不合法: {include['plan_id']}") from exc

        child_plan = await session.get(Plan, child_plan_id)
        if child_plan is None:
            raise PlanError(f"被引用的计划不存在: {child_plan_id}")
        if child_plan.product_version_id not in locked:
            raise PlanError("只能引用当前版本已锁定的子版本的子计划")

        prefix = str(
            include.get("prefix")
            or await _product_code(session, child_plan.product_version_id)
        ).lower()
        if prefix in prefixes:
            raise PlanError(f"include 前缀重复: {prefix}")
        prefixes.add(prefix)

        for node in child_plan.definition.get("nodes") or []:
            copy = dict(node)
            copy["key"] = f"{prefix}.{node['key']}"
            copy["depends_on"] = [
                f"{prefix}.{dep}" for dep in node.get("depends_on") or []
            ]
            nodes.append(copy)

    return nodes


async def _product_code(session: AsyncSession, version_id: UUID) -> str:
    version = await session.get(ProductVersion, version_id)
    product = await session.get(Product, version.product_id) if version else None
    if product is not None:
        return product.code
    return version_id.hex[:8]


async def create_plan(
    session: AsyncSession,
    *,
    product_version_id: UUID,
    name: str,
    definition: object,
) -> Plan:
    version = await session.get(ProductVersion, product_version_id)
    if version is None:
        raise PlanError(f"产品版本不存在: {product_version_id}")

    definition_data = parse_definition(definition)
    expanded = await expand_nodes(
        session, definition_data, parent_version_id=product_version_id
    )

    # 展开后再校验整体 DAG：跨计划的依赖、重名、成环都在创建时暴露
    from app.services.runs import RunError, order_nodes

    try:
        order_nodes(expanded)
    except RunError as exc:
        raise PlanError(str(exc)) from exc

    plan = Plan(
        product_version_id=product_version_id,
        name=name,
        definition=definition_data,
    )
    session.add(plan)
    await session.flush()
    return plan


async def list_plans(session: AsyncSession, limit: int = 50) -> list[Plan]:
    result = await session.execute(
        select(Plan).order_by(Plan.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
