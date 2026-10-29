"""数据模型的最小验收：产品树、版本锁死、计划与执行落库。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Plan,
    Product,
    ProductVersion,
    Run,
    RunStep,
    VersionComponent,
)


async def _product(session, code: str, name: str) -> Product:
    product = Product(code=code, name=name)
    session.add(product)
    await session.flush()
    return product


async def _version(session, product: Product, version: str) -> ProductVersion:
    row = ProductVersion(product_id=product.id, version=version)
    session.add(row)
    await session.flush()
    return row


async def test_product_tree_and_locked_components(session):
    bundle = await _product(session, "C", "组合产品")
    part_a = await _product(session, "A", "部件 A")
    part_b = await _product(session, "B", "部件 B")
    bundle.parent_id = None

    c1 = await _version(session, bundle, "1.0.0")
    a1 = await _version(session, part_a, "2.1.0")
    b1 = await _version(session, part_b, "3.4.0")

    session.add_all(
        [
            VersionComponent(
                parent_version_id=c1.id,
                child_product_id=part_a.id,
                child_version_id=a1.id,
            ),
            VersionComponent(
                parent_version_id=c1.id,
                child_product_id=part_b.id,
                child_version_id=b1.id,
            ),
        ]
    )
    await session.commit()

    components = (
        await session.execute(
            select(VersionComponent).where(VersionComponent.parent_version_id == c1.id)
        )
    ).scalars().all()
    assert {c.child_version_id for c in components} == {a1.id, b1.id}


async def test_same_child_product_cannot_appear_twice(session):
    bundle = await _product(session, "C2", "组合产品")
    part = await _product(session, "A2", "部件")
    c1 = await _version(session, bundle, "1.0.0")
    a1 = await _version(session, part, "1.0.0")
    a2 = await _version(session, part, "1.1.0")

    session.add_all(
        [
            VersionComponent(
                parent_version_id=c1.id,
                child_product_id=part.id,
                child_version_id=a1.id,
            ),
            VersionComponent(
                parent_version_id=c1.id,
                child_product_id=part.id,
                child_version_id=a2.id,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_plan_run_and_steps_roundtrip(session):
    product = await _product(session, "P", "被测产品")
    version = await _version(session, product, "0.9.0")

    plan = Plan(
        product_version_id=version.id,
        name="冒烟",
        definition={"nodes": [{"key": "login", "plugin": "fake-login"}]},
    )
    session.add(plan)
    await session.flush()

    run = Run(plan_id=plan.id, product_version_id=version.id, trigger="manual")
    session.add(run)
    await session.flush()

    session.add_all(
        [
            RunStep(run_id=run.id, node_key="login", status="passed", exit_code=0),
            RunStep(
                run_id=run.id,
                node_key="logout",
                status="failed",
                exit_code=7,
                reason="exit code 7",
            ),
        ]
    )
    await session.commit()

    stored = (
        await session.execute(select(RunStep).where(RunStep.run_id == run.id))
    ).scalars().all()
    assert {s.status for s in stored} == {"passed", "failed"}

    stored_plan = await session.get(Plan, plan.id)
    assert stored_plan is not None
    assert stored_plan.definition["nodes"][0]["key"] == "login"
