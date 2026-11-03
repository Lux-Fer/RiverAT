"""领导页数据（D29）：用 SQL 聚合出五个数字，不做缓存。

口径都写在返回字段旁边，页面直接展示，避免"数字对不上"的争论。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, Product, ProductVersion, Run, RunStep
from app.services.releases import upcoming


async def _daily_trend(session: AsyncSession, *, days: int = 14) -> list[dict]:
    """最近 N 天每天的成功/失败次数（按 finished_at 的 UTC 日期归组）。"""

    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    since = datetime(start.year, start.month, start.day, tzinfo=UTC)

    rows = (
        await session.execute(
            select(func.date(Run.finished_at).label("day"), Run.status, func.count())
            .where(Run.finished_at.is_not(None), Run.finished_at >= since)
            .group_by("day", Run.status)
        )
    ).all()

    counts: dict[str, dict[str, int]] = {}
    for day, status, count in rows:
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        counts.setdefault(key, {})[status] = count

    trend: list[dict] = []
    for offset in range(days):
        key = (start + timedelta(days=offset)).isoformat()
        bucket = counts.get(key, {})
        trend.append(
            {
                "date": key,
                "passed": bucket.get("passed", 0),
                "failed": bucket.get("failed", 0),
                "error": bucket.get("error", 0),
            }
        )
    return trend


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

    # 让"1"能展开看到是谁（D78）
    risk_detail = (
        await session.execute(
            select(Product.code, Product.name, ProductVersion.version)
            .join(ProductVersion, ProductVersion.product_id == Product.id)
            .where(ProductVersion.id.not_in(select(passed_versions.c.product_version_id)))
            .order_by(Product.code, ProductVersion.version)
            .limit(8)
        )
    ).all()

    trend = await _daily_trend(session)

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
        "risk_versions_detail": [
            {"product_code": code, "product_name": name, "version": version}
            for code, name, version in risk_detail
        ],
        "trend": trend,
        "trend_total": sum(d["passed"] + d["failed"] + d["error"] for d in trend),
        "trend_bad": sum(d["failed"] + d["error"] for d in trend),
        "upcoming": await upcoming(session),
        "duration": {
            "p50": round(_percentile(durations, 0.5), 1) if durations else None,
            "p90": round(_percentile(durations, 0.9), 1) if durations else None,
            "samples": len(durations),
        },
    }
