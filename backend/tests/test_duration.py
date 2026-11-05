"""耗时格式：亚秒任务不再显示 00:00。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.duration import duration_between, format_duration


def test_format_duration_sub_second():
    assert format_duration(0) == "<1s"
    assert format_duration(0.42) == "<1s"


def test_format_duration_seconds_and_hours():
    assert format_duration(1) == "00:01"
    assert format_duration(59.9) == "00:59"
    assert format_duration(60) == "01:00"
    assert format_duration(3661) == "1:01:01"


def test_duration_between():
    now = datetime.now(UTC)
    assert duration_between(now - timedelta(milliseconds=200), now) == "<1s"
    assert duration_between(now - timedelta(seconds=2), now) == "00:02"
    assert duration_between(None, now) == ""
