"""项目支流总览（D121/D122）。

一个产品一条支流；按"运行中 > 将运行 > 无运行"排序。
时间轴取当前小时前 2 小时起、共 6 小时；事件按时间映射成百分比。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, WorkProduct
from app.services.duration import format_duration
from app.services.tasks import list_tasks
from app.services.work_products import list_products

LOCAL = ZoneInfo("Asia/Shanghai")
RUNNING = {"queued", "running", "cancelling"}
UPCOMING = {"draft"}
DONE = {"passed", "failed", "error", "skipped"}
SPAN_HOURS = 6


@dataclass
class Dot:
    pct: float
    kind: str  # pass | fail | run | draft | sched
    label: str = ""
    above: bool = False


@dataclass
class Lane:
    product: WorkProduct
    group: str  # running | upcoming | idle
    running: list[Task] = field(default_factory=list)
    upcoming: list[Task] = field(default_factory=list)
    last_done: Task | None = None
    dots: list[Dot] = field(default_factory=list)
    elapsed: str = ""
    next_text: str = "—"
    title: str = ""
    meta: str = ""
    last_text: str = ""
    href: str = ""


@dataclass
class Overview:
    lanes: list[Lane]
    ticks: list[str]
    now_pct: float
    updated: str
    running_total: int
    upcoming_total: int


def _short(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(LOCAL).strftime("%H:%M")


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


def _pct(moment: datetime, start: datetime, end: datetime) -> float:
    span = (end - start).total_seconds() or 1
    value = (moment - start).total_seconds() / span * 100
    return round(min(98.0, max(2.0, value)), 2)


def _started(task: Task) -> datetime:
    return task.approved_at or task.created_at


def _scheduled(task: Task) -> datetime | None:
    return getattr(task, "scheduled_at", None)


async def build_overview(session: AsyncSession, *, now: datetime | None = None) -> Overview:
    now = (now or datetime.now(UTC)).astimezone(LOCAL)
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    end = start + timedelta(hours=SPAN_HOURS)
    now_pct = _pct(now, start, end)

    products = await list_products(session)
    tasks = await list_tasks(session, limit=500)

    by_product: dict[str, list[Task]] = {}
    for task in tasks:
        if task.product_id is not None:
            by_product.setdefault(str(task.product_id), []).append(task)

    lanes: list[Lane] = []
    for product in products:
        group_tasks = by_product.get(str(product.id), [])
        running = [t for t in group_tasks if t.status in RUNNING]
        upcoming = [t for t in group_tasks if t.status in UPCOMING]
        done = sorted(
            (t for t in group_tasks if t.status in DONE and t.finished_at),
            key=lambda t: t.finished_at or datetime.min.replace(tzinfo=UTC),
        )

        group = "running" if running else ("upcoming" if upcoming else "idle")
        lane = Lane(
            product=product,
            group=group,
            running=running,
            upcoming=upcoming,
            last_done=done[-1] if done else None,
            href=f"/products/{product.id}",
        )

        for task in done[-6:]:
            moment = task.finished_at or now
            if start <= moment <= end:
                lane.dots.append(
                    Dot(
                        pct=_pct(moment, start, end),
                        kind="pass" if task.status == "passed" else "fail",
                    )
                )

        if running:
            first = min(running, key=_started)
            lane.title = first.title
            elapsed = (now - _started(first).astimezone(LOCAL)).total_seconds()
            lane.elapsed = format_duration(elapsed)
            lane.meta = f"{len(running)} 运行 · {len(upcoming)} 将进行"
            lane.dots.append(
                Dot(pct=now_pct, kind="run", label=f"{lane.elapsed} {first.title[:14]}")
            )
        elif upcoming:
            first = min(upcoming, key=lambda t: _scheduled(t) or t.created_at)
            lane.title = first.title
            when = _scheduled(first) or first.created_at
            lane.meta = f"待确认 · {_short(when)}"
            lane.dots.append(
                Dot(pct=_pct(when, start, end) if start <= when <= end else now_pct,
                    kind="draft", label=f"待确认 {first.title[:12]}")
            )
        else:
            lane.title = "静水"
            lane.meta = "没有运行中或将进行的任务"

        if upcoming:
            first = min(upcoming, key=lambda t: _scheduled(t) or t.created_at)
            lane.next_text = f"{_short(_scheduled(first) or first.created_at)} {first.title[:12]}"
        else:
            lane.next_text = "—"

        if lane.last_done is not None:
            lane.last_text = (
                f"{_day(lane.last_done.finished_at)} {_short(lane.last_done.finished_at)}"
                f" · {lane.last_done.title[:14]} · {lane.last_done.status}"
            )
        else:
            lane.last_text = "未执行"

        lanes.append(lane)

    def _rank(lane: Lane) -> tuple[int, float]:
        if lane.group == "running":
            return (0, min(_started(t).timestamp() for t in lane.running))
        if lane.group == "upcoming":
            return (1, min((_scheduled(t) or t.created_at).timestamp() for t in lane.upcoming))
        last = lane.last_done.finished_at.timestamp() if lane.last_done else 0
        return (2, -last)

    lanes.sort(key=_rank)

    ticks = [(start + timedelta(hours=i)).strftime("%H:%M") for i in range(SPAN_HOURS)]
    running_total = sum(len(l.running) for l in lanes)
    upcoming_total = sum(len(l.upcoming) for l in lanes)
    return Overview(
        lanes=lanes,
        ticks=ticks,
        now_pct=now_pct,
        updated=now.strftime("%H:%M"),
        running_total=running_total,
        upcoming_total=upcoming_total,
    )
