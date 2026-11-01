"""前端资源的唯一入口：模板目录与静态目录。

前端代码放在仓库根的 ``frontend/``（模板 + 静态资源），后端只负责引用 ——
按 D68，后端目录里不再放任何 HTML/CSS。
"""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR

FRONTEND_DIR = BASE_DIR.parent / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
