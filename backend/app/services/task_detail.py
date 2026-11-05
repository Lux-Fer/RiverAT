"""任务详情（D133）：一条任务的步骤流、用例结果与操作。

步骤按时间顺序排成一条竖线；运行中的步骤用实心节点，等待中的步骤是空心节点。
参数默认收起，草案阶段可展开修改；stderr 也只在需要时展开。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskStep, WorkProduct
from app.services.labels import status_label, status_tone
from app.services.work_products import get_product

LOCAL = ZoneInfo("Asia/Shanghai")
RUNNING = {"queued", "running", "cancelling"}
DONE = {"passed", "failed", "error", "skipped", "cancelled"}
STEP_ORDER = ["passed", "failed", "error", "skipped", "running", "pending", "cancelled"]


@dataclass
class StepRow:
    step: TaskStep
    tone: str
    status: str
    duration: str
    args: str
    arg_count: int
    stderr: str
    case_count: int


@dataclass
class CaseRow:
    case_id: str
    status: str
    tone: str
    duration: str
    reason: str
    source: str


@dataclass
class TaskDetail:
    task: Task
    product: WorkProduct | None
    status: str
    tone: str
    created: str
    started: str
    finished: str
    clock: str
    step_text: str
    summary: str
    steps: list[StepRow] = field(default_factory=list)
    cases: list[CaseRow] = field(default_factory=list)
    case_summary: str = ""
    active: bool = False
    is_terminal: bool = False


def _stamp(dt: datetime | None) -> str:
    return dt.astimezone(LOCAL).strftime("%m-%d %H:%M") if dt else ""


def _dur(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return ""
    total = max(0, int((end - start).total_seconds()))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _args(step: TaskStep) -> str:
    return json.dumps(step.args or {}, ensure_ascii=False, separators=(", ", ": "))


def _duration_ms(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    return f"{int(value)} ms"


async def build_task_detail(
    session: AsyncSession,
    task: Task,
    steps: list[TaskStep],
    *,
    now: datetime | None = None,
) -> TaskDetail:
    now = (now or datetime.now(UTC)).astimezone(LOCAL)
    product = await get_product(session, task.product_id) if task.product_id else None

    step_rows: list[StepRow] = []
    cases: list[CaseRow] = []
    for step in steps:
        end = step.finished_at
        if step.status == "running" and step.started_at:
            end = now
        output = step.output or {}
        raw_cases = output.get("cases") or []
        step_rows.append(
            StepRow(
                step=step,
                tone=status_tone(step.status),
                status=status_label(step.status),
                duration=_dur(step.started_at, end),
                args=_args(step),
                arg_count=len(step.args or {}),
                stderr=str(output.get("stderr") or ""),
                case_count=len(raw_cases),
            )
        )
        for case in raw_cases:
            cases.append(
                CaseRow(
                    case_id=str(case.get("case_id") or "—"),
                    status=status_label(case.get("status")),
                    tone=status_tone(case.get("status")),
                    duration=_duration_ms(case.get("duration_ms")),
                    reason=str(case.get("reason") or ""),
                    source=f"{step.seq:02d} {step.tool_name}",
                )
            )

    counts: dict[str, int] = {}
    for step in steps:
        counts[step.status] = counts.get(step.status, 0) + 1
    summary = " · ".join(
        f"{counts[status]} {status_label(status)}"
        for status in STEP_ORDER
        if counts.get(status)
    )
    completed = sum(counts.get(status, 0) for status in ("passed", "skipped"))

    passed = sum(1 for case in cases if case.status == status_label("passed"))
    failed = sum(1 for case in cases if case.status in {status_label("failed"), status_label("error")})
    if failed:
        case_summary = f"{passed} 通过 · {failed} 失败"
    elif cases:
        case_summary = f"{passed} 通过"
    else:
        case_summary = ""

    if task.status == "queued":
        clock = "等待"
    elif task.finished_at:
        clock = _dur(task.approved_at, task.finished_at)
    elif task.approved_at:
        clock = _dur(task.approved_at, now)
    else:
        clock = ""

    return TaskDetail(
        task=task,
        product=product,
        status=status_label(task.status),
        tone=status_tone(task.status),
        created=_stamp(task.created_at),
        started=_stamp(task.approved_at),
        finished=_stamp(task.finished_at),
        clock=clock,
        step_text=f"{completed} / {len(steps)} 步" if steps else "没有工具步骤",
        summary=summary,
        steps=step_rows,
        cases=cases,
        case_summary=case_summary,
        active=task.status in RUNNING,
        is_terminal=task.status in DONE,
    )
