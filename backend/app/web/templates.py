"""前端资源的唯一入口：模板目录与静态目录。

前端代码放在仓库根的 ``frontend/``（模板 + 静态资源），后端只负责引用 ——
按 D68，后端目录里不再放任何 HTML/CSS。
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.core.config import BASE_DIR, get_settings
from app.services.labels import (
    status_label,
    status_tone,
    tool_risk_label,
    tool_status_label,
    tool_status_tone,
)

FRONTEND_DIR = BASE_DIR.parent / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# 模板里直接用 {{ status_label("passed") }} → 通过（D76）
templates.env.globals["status_label"] = status_label
templates.env.globals["status_tone"] = status_tone
templates.env.globals["tool_status_label"] = tool_status_label
templates.env.globals["tool_status_tone"] = tool_status_tone
templates.env.globals["tool_risk_label"] = tool_risk_label


def soft_markdown(text: str) -> Markup:
    """模型回复的极简渲染：粗体、行内代码、换行；三反引号渲染为代码块。"""

    escaped = html.escape(text or "")
    parts = re.split(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", escaped, flags=re.DOTALL)
    rendered: list[str] = []
    for index, part in enumerate(parts):
        if index % 2:
            rendered.append(f"<pre><code>{part.rstrip()}</code></pre>")
            continue
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", part)
        rendered.append(part.replace("\n", "<br>"))
    return Markup("".join(rendered))


templates.env.filters["soft_markdown"] = soft_markdown


def localtime(value: datetime | None) -> str:
    """按 display_timezone 输出本地时间（D81 的时区口径）。"""

    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(get_settings().display_timezone)).strftime(
        "%m-%d %H:%M"
    )


templates.env.filters["localtime"] = localtime