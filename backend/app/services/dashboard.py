"""领导页数据（D29）：用 SQL 聚合出五个数字，不做缓存。

口径都写在返回字段旁边，页面直接展示，避免"数字对不上"的争论。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, ProductVersion, Run, RunStep


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def summary(session: AsyncSession) -> dict:
    statuses = dict(
        (
            await session.execute(select(Run.status, func.count()).group_by(Run.status))
        ).all()
    )

    passed = statuses.get("passed", 0)
    failed = statuses.get("failed", 0)
    error = statuses.get("error", 0)
    blocked = statuses.get("blocked", 0)
    in_flight = statuses.get("queued", 0) + statuses.get("running", 0)
    finished = passed + failed + error

    durations_rows = (
        await session.execute(
            select(Run.finished_at - Run.started_at).where(
                Run.started_at.is_not(None), Run.finished_at.is_not(None)
            )
        )
    ).scalars().all()
    durations = [row.total_seconds() for row in durations_rows if row is not None]

    # 完整性：已结束的 run 里，落库的 run_step 数量 >= 计划快照节点数
    node_count = func.coalesce(func.jsonb_array_length(Plan.snapshot["nodes"]), 0)
    coverage_rows = (
        await session.execute(
            select(node_count, func.count(RunStep.id))
            .select_from(Run)
            .join(Plan, Plan.id == Run.plan_id)
            .outerjoin(RunStep, RunStep.run_id == Run.id)
            .where(Run.status.in_(("passed", "failed", "error")))
            .group_by(Run.id, node_count)
        )
    ).all()
    complete = sum(1 for planned, actual in coverage_rows if actual >= planned)

    # 风险敞口：从未成功执行过的产品版本数
    passed_versions = (
        select(Run.product_version_id)
        .where(Run.status == "passed")
        .distinct()
        .subquery()
    )
    risk_rows = (
        await session.execute(
            select(func.count())
            .select_from(ProductVersion)
            .where(ProductVersion.id.not_in(select(passed_versions.c.product_version_id)))
        )
    ).scalar_one()

    return {
        "total_runs": sum(statuses.values()),
        "by_status": statuses,
        "release": {
            "green": passed,
            "red": failed + error,
            "yellow": blocked,
            "in_flight": in_flight,
        },
        "pass_rate": round(passed / finished, 3) if finished else None,
        "coverage": {
            "complete": complete,
            "finished": len(coverage_rows),
            "ratio": round(complete / len(coverage_rows), 3) if coverage_rows else None,
        },
        "risk_versions": risk_rows,
        "duration": {
            "p50": round(_percentile(durations, 0.5), 1) if durations else None,
            "p90": round(_percentile(durations, 0.9), 1) if durations else None,
            "samples": len(durations),
        },
    }
