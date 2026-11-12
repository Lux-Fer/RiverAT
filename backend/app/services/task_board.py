"""任务台账（D132）：运行中 → 将进行 → 已完成。

不按产品分组，一条任务一行；运行中的排最前，已完成的压成尾流。
状态只用文字和颜色，不用胶囊标签；行间只留必要横线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskStep, WorkProduct
from app.services.duration import duration_between
from app.services.labels import status_label, status_tone
from app.services.tasks import list_tasks
from app.services.work_products import list_products

LOCAL = ZoneInfo("Asia/Shanghai")
RUNNING = {"queued", "running", "cancelling", "paused"}
UPCOMING = {"draft"}
DONE = {"passed", "failed", "error", "skipped", "cancelled"}
RUN_ORDER = {"running": 0, "cancelling": 1, "paused": 2, "queued": 3}
DONE_PREVIEW = 30


@dataclass
class RunRow:
    task: Task
    product: WorkProduct | None
    clock: str
    day: str
    status: str
    tone: str
    elapsed: str
    waiting: bool
    step_done: int
    step_total: int
    step_marks: list[str] = field(default_factory=list)
    step_text: str = ""
    current: str = ""


@dataclass
class DraftRow:
    task: Task
    product: WorkProduct | None
    clock: str
    day: str
    step_total: int
    age: str


@dataclass
class DoneRow:
    task: Task
    product: WorkProduct | None
    clock: str
    day: str
    status: str
    tone: str
    duration: str


@dataclass
class TaskBoard:
    running: list[RunRow]
    upcoming: list[DraftRow]
    done: list[DoneRow]
    running_count: int
    upcoming_count: int
    done_count: int
    done_more: int
    updated: str


def _short(dt: datetime | None) -> str:
    return dt.astimezone(LOCAL).strftime("%H:%M") if dt else ""


def _day(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(LOCAL)
    today = datetime.now(LOCAL).date()
    if local.date() == today:
        return "今天"
    if (today - local.date()).days == 1:
        return "昨天"
    return local.strftime("%m-%d")


def _started(task: Task) -> datetime:
    return task.approved_at or task.created_at


def _ago(dt: datetime, now: datetime) -> str:
    seconds = max(0, int((now - dt.astimezone(LOCAL)).total_seconds()))
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    return f"{hours // 24} 天前"


def _marks(steps: list[TaskStep]) -> list[str]:
    marks: list[str] = []
    for step in steps:
        if step.status in {"passed", "skipped"}:
            marks.append("d")
        elif step.status in {"failed", "error"}:
            marks.append("f")
        elif step.status == "running":
            marks.append("n")
        else:
            marks.append("")
    return marks


def _current(steps: list[TaskStep], task: Task) -> str:
    if not steps:
        return "没有工具步骤"
    for step in steps:
        if step.status == "running":
            return step.tool_name
    if task.status == "queued":
        return "等待执行"
    if task.status == "paused":
        return "等待修复确认"
    if task.status == "cancelling":
        return "当前步骤结束后取消"
    return "准备中"


async def build_task_board(
    session: AsyncSession, *, now: datetime | None = None
) -> TaskBoard:
    now = (now or datetime.now(UTC)).astimezone(LOCAL)

    status_rows = await session.execute(
        select(Task.status, func.count()).group_by(Task.status)
    )
    counts = {status: count for status, count in status_rows.all()}
    tasks = await list_tasks(session, limit=500)
    products = {product.id: product for product in await list_products(session)}

    running_tasks = [task for task in tasks if task.status in RUNNING]
    running_tasks.sort(key=lambda task: (RUN_ORDER.get(task.status, 9), _started(task)))
    upcoming_tasks = [task for task in tasks if task.status in UPCOMING]
    upcoming_tasks.sort(key=lambda task: task.created_at)
    done_tasks = [
        task for task in tasks if task.status in DONE and task.finished_at is not None
    ]
    done_tasks.sort(key=lambda task: task.finished_at or task.created_at, reverse=True)

    steps_by_task: dict[UUID, list[TaskStep]] = {}
    ids = [task.id for task in running_tasks + upcoming_tasks]
    if ids:
        rows = await session.execute(
            select(TaskStep)
            .where(TaskStep.task_id.in_(ids))
            .order_by(TaskStep.task_id, TaskStep.seq)
        )
        for step in rows.scalars():
            steps_by_task.setdefault(step.task_id, []).append(step)

    running: list[RunRow] = []
    for task in running_tasks:
        steps = steps_by_task.get(task.id, [])
        marks = _marks(steps)
        started = _started(task).astimezone(LOCAL)
        waiting = task.status in ("queued", "paused")
        running.append(
            RunRow(
                task=task,
                product=products.get(task.product_id) if task.product_id else None,
                clock=_short(started),
                day=_day(started),
                status=status_label(task.status),
                tone=status_tone(task.status),
                elapsed="等待" if waiting else duration_between(started, now),
                waiting=waiting,
                step_done=sum(1 for mark in marks if mark == "d"),
                step_total=len(steps),
                step_marks=marks,
                step_text=f"{sum(1 for mark in marks if mark == 'd')} / {len(steps)} 步"
                if steps
                else "—",
                current=_current(steps, task),
            )
        )

    upcoming = [
        DraftRow(
            task=task,
            product=products.get(task.product_id) if task.product_id else None,
            clock=_short(task.created_at),
            day=_day(task.created_at),
            step_total=len(steps_by_task.get(task.id, [])),
            age=_ago(task.created_at, now),
        )
        for task in upcoming_tasks
    ]

    done = [
        DoneRow(
            task=task,
            product=products.get(task.product_id) if task.product_id else None,
            clock=_short(task.finished_at),
            day=_day(task.finished_at),
            status=status_label(task.status),
            tone=status_tone(task.status),
            duration=duration_between(_started(task), task.finished_at),
        )
        for task in done_tasks[:DONE_PREVIEW]
    ]

    done_count = sum(counts.get(status, 0) for status in DONE)
    return TaskBoard(
        running=running,
        upcoming=upcoming,
        done=done,
        running_count=sum(counts.get(status, 0) for status in RUNNING),
        upcoming_count=sum(counts.get(status, 0) for status in UPCOMING),
        done_count=done_count,
        done_more=max(0, done_count - len(done)),
        updated=now.strftime("%H:%M"),
    )
