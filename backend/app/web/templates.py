"""前端资源的唯一入口：模板目录与静态目录。

前端代码放在仓库根的 ``frontend/``（模板 + 静态资源），后端只负责引用 ——
按 D68，后端目录里不再放任何 HTML/CSS。
"""

from __future__ import annotations

import html
import re

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.core.config import BASE_DIR
from app.services.labels import status_label

FRONTEND_DIR = BASE_DIR.parent / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# 模板里直接用 {{ status_label("passed") }} → 通过（D76）
templates.env.globals["status_label"] = status_label


def soft_markdown(text: str) -> Markup:
    """模型回复的极简渲染：粗体、行内代码、换行；代码围栏按普通文本处理。"""

    escaped = html.escape(text or "")
    escaped = re.sub(r"```[a-zA-Z]*\n?", "", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    return Markup(escaped.replace("\n", "<br>"))


templates.env.filters["soft_markdown"] = soft_markdown
