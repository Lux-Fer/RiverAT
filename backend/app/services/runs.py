"""把一条计划跑起来并落库（v1：同步执行，跑完才返回）。

编排语义（D13/D15）：
* 顺序执行 ``plan.definition["nodes"]``，每个节点一个 ``run_step``；
* 节点失败**不中断**后续节点（失败是信息，不是中止理由）；
* run 的终态取所有节点的最坏值：error > failed > blocked > passed。
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Host, Plan, Run, RunStep
from app.runner.executor import StepOutcome, run_step
from app.services.hosts import HostError, build_transport
from app.services.plans import PlanError, expand_nodes
from app.transport.base import Transport, TransportError
from app.transport.local import LocalTransport

_MAX_EVIDENCE_CHARS = 16_384
_STATUS_SEVERITY = {"error": 4, "failed": 3, "blocked": 2, "skipped": 1, "passed": 0}


class RunError(RuntimeError):
    """请求无法执行（计划不存在、节点配置非法等）。"""


def aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "error"
    return max(statuses, key=lambda s: _STATUS_SEVERITY.get(s, 4))


async def create_run(
    session: AsyncSession,
    plan_id: UUID,
    *,
    trigger: str = "manual",
    host: Host | None = None,
) -> Run:
    """只建执行记录（queued），真正执行交给 worker 或 dispatcher。"""

    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise RunError(f"计划不存在: {plan_id}")

    run = Run(
        plan_id=plan.id,
        host_id=host.id if host is not None else None,
        product_version_id=plan.product_version_id,
        trigger=trigger,
        status="queued",
        plan_sha256=plan.snapshot_sha256 or None,
        plan_revision=plan.revision,
    )
    session.add(run)
    await session.flush()
    return run


async def _resolve_nodes(session: AsyncSession, plan: Plan) -> list[dict]:
    snapshot_nodes = (plan.snapshot or {}).get("nodes")
    if snapshot_nodes:
        # 计划创建时冻结的展开结果；子计划之后怎么改都不影响这次执行（D59）
        return order_nodes([dict(node) for node in snapshot_nodes])

    definition = plan.definition or {}
    try:
        expanded = await expand_nodes(
            session, definition, parent_version_id=plan.product_version_id
        )
    except PlanError as exc:
        raise RunError(str(exc)) from exc
    return order_nodes(expanded)


async def execute_run(session: AsyncSession, run: Run) -> Run:
    """执行一条已存在的 run（worker / 页面同步执行共用）。"""

    plan = await session.get(Plan, run.plan_id)
    if plan is None:
        raise RunError(f"计划不存在: {run.plan_id}")

    nodes = await _resolve_nodes(session, plan)
    host = await session.get(Host, run.host_id) if run.host_id else None

    run.status = "running"
    run.started_at = datetime.now(UTC)

    if host is None:
        transport: Transport = LocalTransport()
        workdir = tempfile.mkdtemp(prefix="riverat-run-")
        remote_workdir: str | None = None
    else:
        try:
            transport = build_transport(host)
        except HostError as exc:
            raise RunError(str(exc)) from exc
        workdir = f"/tmp/riverat-runs/{run.id}"
        remote_workdir = workdir

    statuses: list[str] = []
    state_by_key: dict[str, str] = {}

    try:
        for node in order_nodes(nodes):
            key = str(node["key"])
            deps = [str(d) for d in (node.get("depends_on") or [])]
            blocked_by = [d for d in deps if state_by_key.get(d) != "passed"]
            if blocked_by:
                state_by_key[key] = "blocked"
                statuses.append("blocked")
                session.add(
                    RunStep(
                        run_id=run.id,
                        node_key=key,
                        status="blocked",
                        reason=f"依赖未通过: {', '.join(blocked_by)}",
                        evidence={},
                        started_at=datetime.now(UTC),
                        finished_at=datetime.now(UTC),
                    )
                )
                await session.flush()
                continue

            started = datetime.now(UTC)
            outcome = await asyncio.to_thread(
                run_step,
                transport,
                _resolve_bundle(str(node["plugin"])),
                workdir=workdir,
                step={"step_id": key, "args": node.get("args") or {}},
                timeout=node.get("timeout"),
            )
            finished = datetime.now(UTC)
            state_by_key[key] = outcome.status.value
            statuses.append(outcome.status.value)
            session.add(_to_run_step(run.id, key, outcome, started, finished))
            await session.flush()
    finally:
        if remote_workdir is not None:
            try:
                transport.exec(["sh", "-c", f"rm -rf {remote_workdir}"], timeout=30)
            except TransportError:
                pass
        transport.close()
        run.finished_at = datetime.now(UTC)
        run.status = aggregate_status(statuses)
        await session.flush()
        if run.status in ("failed", "error"):
            # 失败执行入知识库，供后续相似失败检索（D25）
            from app.services.knowledge import index_run

            await index_run(session, run)

    return run


async def execute_plan(
    session: AsyncSession,
    plan_id: UUID,
    *,
    trigger: str = "manual",
    host: Host | None = None,
) -> Run:
    """同步执行（页面/测试用）：建记录 + 立刻跑完。"""

    run = await create_run(session, plan_id, trigger=trigger, host=host)
    return await execute_run(session, run)


async def execute_run_by_id(run_id: UUID) -> None:
    """worker 用：自己开会话、跑完提交。"""

    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status not in ("queued", "running"):
            return
        await execute_run(session, run)
        await session.commit()


def order_nodes(nodes: list[dict]) -> list[dict]:
    """按 depends_on 做稳定拓扑排序；依赖不存在或成环都报错。"""

    by_key: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict) or "key" not in node or "plugin" not in node:
            raise RunError(f"节点配置非法: {node!r}")
        key = str(node["key"])
        if key in by_key:
            raise RunError(f"节点 key 重复: {key}")
        by_key[key] = node

    indegree = {key: 0 for key in by_key}
    children: dict[str, list[str]] = {key: [] for key in by_key}
    for key, node in by_key.items():
        for dep in node.get("depends_on") or []:
            dep = str(dep)
            if dep not in by_key:
                raise RunError(f"节点 {key} 依赖不存在的节点: {dep}")
            indegree[key] += 1
            children[dep].append(key)

    queue = [key for key in by_key if indegree[key] == 0]
    ordered: list[dict] = []
    while queue:
        key = queue.pop(0)
        ordered.append(by_key[key])
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(nodes):
        raise RunError("节点依赖成环")
    return ordered


def _resolve_bundle(plugin: str) -> Path:
    path = Path(plugin)
    if path.is_absolute():
        return path
    return get_settings().bundle_root / path


def _to_run_step(
    run_id: UUID,
    node_key: str,
    outcome: StepOutcome,
    started: datetime,
    finished: datetime,
) -> RunStep:
    return RunStep(
        run_id=run_id,
        node_key=node_key,
        status=outcome.status.value,
        exit_code=outcome.exit_code,
        duration_ms=outcome.duration_ms,
        reason=outcome.reason or None,
        evidence={
            "stdout": outcome.stdout.decode("utf-8", "replace")[-_MAX_EVIDENCE_CHARS:],
            "stderr": outcome.stderr.decode("utf-8", "replace")[-_MAX_EVIDENCE_CHARS:],
            "artifacts": sorted(outcome.artifacts),
            "bundle_sha256": outcome.bundle_sha256,
            "truncated": outcome.truncated,
        },
        started_at=started,
        finished_at=finished,
    )


async def list_runs(
    session: AsyncSession, *, status: str | None = None, limit: int = 50
) -> list[Run]:
    stmt = select(Run).order_by(Run.created_at.desc())
    if status == "finished":
        stmt = stmt.where(Run.status.in_(("passed", "failed", "error")))
    elif status == "bad":
        stmt = stmt.where(Run.status.in_(("failed", "error")))
    elif status:
        stmt = stmt.where(Run.status == status)
    result = await session.execute(stmt.limit(limit))
    return list(result.scalars().all())


async def get_run(session: AsyncSession, run_id: UUID) -> Run | None:
    return await session.get(Run, run_id)


async def list_steps(session: AsyncSession, run_id: UUID) -> list[RunStep]:
    result = await session.execute(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.node_key)
    )
    return list(result.scalars().all())


__all__ = [
    "RunError",
    "TransportError",
    "aggregate_status",
    "execute_plan",
    "get_run",
    "list_runs",
    "list_steps",
]
