"""声明式基类。

所有表都挂在 ``Base.metadata`` 上，Alembic 的 autogenerate 以它为准。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
