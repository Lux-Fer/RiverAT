"""界面耗时格式：小于 1 秒统一显示 `<1s`，避免亚秒任务显示 00:00。"""

from __future__ import annotations

from datetime import datetime


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 1:
        return "<1s"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def duration_between(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return ""
    return format_duration((end - start).total_seconds())
