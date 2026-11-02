"""账号与会话（v1：本地账号 + Redis/内存会话）。"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import SessionStore
from app.models import User

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 6


class AuthError(ValueError):
    """登录失败 / 账号冲突。"""


def check_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def set_password(user: User, password: str) -> None:
    check_password_policy(password)
    user.password_hash = hash_password(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: str = "engineer",
    display_name: str = "",
) -> User:
    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise AuthError(f"用户名已存在: {username}")

    check_password_policy(password)
    user = User(
        username=username,
        display_name=display_name or username,
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate(
    session: AsyncSession, *, username: str, password: str
) -> User | None:
    user = await session.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not user.password_hash:
        return None
    if not verify_password(user.password_hash, password):
        return None
    return user


async def login(
    session: AsyncSession,
    store: SessionStore,
    *,
    username: str,
    password: str,
    ttl_seconds: int,
) -> tuple[User, str]:
    user = await authenticate(session, username=username, password=password)
    if user is None:
        raise AuthError("用户名或密码错误")
    token = await store.create(user.id, ttl_seconds)
    return user, token


async def ensure_bootstrap_admin(
    session: AsyncSession, *, username: str, password: str
) -> None:
    """库里一个用户都没有时，用环境变量里的密码建第一个管理员。"""

    if not password:
        return
    users = await session.scalar(select(func.count()).select_from(User))
    if users:
        return
    await create_user(
        session, username=username, password=password, role="admin"
    )
    await session.commit()
