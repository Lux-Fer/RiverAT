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

from app.models import Plan, ProductVersion


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

    # 依赖存在性与成环在这里统一校验（import 放函数内，避免循环依赖）
    from app.services.runs import RunError, order_nodes

    try:
        order_nodes(nodes)
    except RunError as exc:
        raise PlanError(str(exc)) from exc

    return data


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

    plan = Plan(
        product_version_id=product_version_id,
        name=name,
        definition=parse_definition(definition),
    )
    session.add(plan)
    await session.flush()
    return plan


async def list_plans(session: AsyncSession, limit: int = 50) -> list[Plan]:
    result = await session.execute(
        select(Plan).order_by(Plan.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
