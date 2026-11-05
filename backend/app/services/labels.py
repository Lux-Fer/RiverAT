"""面向界面的中文标签（D76）：状态枚举不再裸奔英文。"""

from __future__ import annotations

STATUS_LABELS = {
    "passed": "通过",
    "failed": "失败",
    "error": "异常",
    "blocked": "阻塞",
    "skipped": "跳过",
    "queued": "排队中",
    "running": "运行中",
    "draft": "待确认",
    "cancelling": "取消中",
    "cancelled": "已取消",
    "pending": "等待",
}


STATUS_TONES = {
    "passed": "p",
    "failed": "f",
    "error": "f",
    "blocked": "f",
    "skipped": "i",
    "cancelled": "i",
    "pending": "i",
    "queued": "i",
    "running": "run",
    "draft": "w",
    "cancelling": "w",
}


def status_label(value: str | None) -> str:
    if value is None:
        return "—"
    return STATUS_LABELS.get(value, value)


def status_tone(value: str | None) -> str:
    return STATUS_TONES.get(value or "", "i")
