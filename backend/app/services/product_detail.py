"""项目详情：一条项目的抽象流（D123/D124）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, WorkProduct
from app.services.duration import duration_between, format_duration
from app.services.tasks import list_tasks, steps_for
from app.services.work_products import get_product

LOCAL = ZoneInfo("Asia/Shanghai")
RUNNING = {"queued", "running", "cancelling"}
UPCOMING = {"draft"}
DONE = {"passed", "failed", "error", "skipped"}
HISTORY_LIMIT = 18


@dataclass
class StepMark:
    done: bool
    current: bool
    failed: bool


@dataclass
class Entry:
    task: Task
    when: str = ""
    day: str = ""
    elapsed: str = ""
    steps: list[StepMark] = field(default_factory=list)
    step_text: str = ""


@dataclass
class Detail:
    product: WorkProduct
    running: list[Entry]
    upcoming: list[Entry]
    history: list[Entry]
    running_count: int
    upcoming_count: int
    done_today: int
    pass_rate: str
    avg: str
    now_label: str


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


async def build_detail(
    session: AsyncSession, product_id: UUID, *, now: datetime | None = None
) -> Detail | None:
    product = await get_product(session, product_id)
    if product is None:
        return None
    now = (now or datetime.now(UTC)).astimezone(LOCAL)

    tasks = [t for t in await list_tasks(session, limit=500) if t.product_id == product_id]
    running_tasks = sorted(
        (t for t in tasks if t.status in RUNNING), key=_started
    )
    upcoming_tasks = sorted(
        (t for t in tasks if t.status in UPCOMING), key=lambda t: t.created_at
    )
    done_tasks = sorted(
        (t for t in tasks if t.status in DONE and t.finished_at),
        key=lambda t: t.finished_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )

    running: list[Entry] = []
    for task in running_tasks:
        steps = await steps_for(session, task.id)
        marks = [
            StepMark(
                done=step.status in DONE and step.status != "failed",
                current=step.status == "running",
                failed=step.status in {"failed", "error"},
            )
            for step in steps
        ]
        running.append(
            Entry(
                task=task,
                when=_short(_started(task)),
                day=_day(_started(task)),
                elapsed=duration_between(_started(task), now),
                steps=marks,
                step_text=f"{sum(1 for m in marks if m.done)} / {len(marks)} 步"
                if marks
                else "准备中",
            )
        )

    upcoming = [
        Entry(task=task, when=_short(task.created_at), day=_day(task.created_at))
        for task in upcoming_tasks
    ]
    history = [
        Entry(
            task=task,
            when=_short(task.finished_at),
            day=_day(task.finished_at),
            elapsed=duration_between(_started(task), task.finished_at),
        )
        for task in done_tasks[:HISTORY_LIMIT]
    ]

    today = now.date()
    done_today = [t for t in done_tasks if t.finished_at and t.finished_at.astimezone(LOCAL).date() == today]
    passed = sum(1 for t in done_today if t.status == "passed")
    rate = f"{passed / len(done_today) * 100:.1f}" if done_today else "—"
    durations = [
        int((t.finished_at - _started(t)).total_seconds())
        for t in done_today
        if t.finished_at and _started(t) and t.finished_at > _started(t)
    ]
    avg = format_duration(sum(durations) // len(durations)) if durations else "—"

    return Detail(
        product=product,
        running=running,
        upcoming=upcoming,
        history=history,
        running_count=len(running),
        upcoming_count=len(upcoming),
        done_today=len(done_today),
        pass_rate=rate,
        avg=avg,
        now_label=now.strftime("%H:%M"),
    )
