"""用户管理（admin）：建账号、改角色、停用。

两个安全约束：
* 不能停用或降级自己（避免把自己锁在门外）；
* 角色只接受 viewer / engineer / admin。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_LEVEL
from app.models import User
from app.services.auth import AuthError, create_user, set_password


class UserError(ValueError):
    """用户操作不合法。"""


def _check_role(role: str) -> None:
    if role not in ROLE_LEVEL:
        raise UserError(f"未知角色: {role}")


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.username))
    return list(result.scalars().all())


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def create_user_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: str = "engineer",
    display_name: str = "",
) -> User:
    _check_role(role)
    try:
        return await create_user(
            session,
            username=username,
            password=password,
            role=role,
            display_name=display_name,
        )
    except AuthError as exc:
        raise UserError(str(exc)) from exc


async def update_user_admin(
    session: AsyncSession,
    user: User,
    *,
    actor: User,
    role: str | None = None,
    is_active: bool | None = None,
    display_name: str | None = None,
    password: str | None = None,
) -> User:
    if user.id == actor.id:
        if is_active is False:
            raise UserError("不能停用自己的账号")
        if role is not None and role != "admin":
            raise UserError("不能降级自己的管理员角色")

    if role is not None:
        _check_role(role)
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if display_name is not None:
        user.display_name = display_name
    if password:
        # 管理员重置密码（D71）；改完用户下次用新密码登录
        try:
            set_password(user, password)
        except AuthError as exc:
            raise UserError(str(exc)) from exc

    await session.flush()
    return user
