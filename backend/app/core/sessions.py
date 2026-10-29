"""会话存储：Redis 里存 token → user_id，cookie 只带 token（D43）。

测试用内存实现；生产用 Redis。接口一样，所以测的是同一条登录链路。
"""

from __future__ import annotations

import secrets
import time
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis


class SessionStore(Protocol):
    async def create(self, user_id: UUID, ttl_seconds: int) -> str: ...

    async def get(self, token: str) -> UUID | None: ...

    async def delete(self, token: str) -> None: ...

    async def close(self) -> None: ...


def _new_token() -> str:
    return secrets.token_urlsafe(32)


class InMemorySessionStore:
    """测试 / 单进程用；进程重启即失效。"""

    def __init__(self) -> None:
        self._sessions: dict[str, tuple[UUID, float]] = {}

    async def create(self, user_id: UUID, ttl_seconds: int) -> str:
        token = _new_token()
        self._sessions[token] = (user_id, time.monotonic() + ttl_seconds)
        return token

    async def get(self, token: str) -> UUID | None:
        entry = self._sessions.get(token)
        if entry is None:
            return None
        user_id, expires_at = entry
        if time.monotonic() > expires_at:
            self._sessions.pop(token, None)
            return None
        return user_id

    async def delete(self, token: str) -> None:
        self._sessions.pop(token, None)

    async def close(self) -> None:
        self._sessions.clear()


class RedisSessionStore:
    """生产用：会话可跨进程共享，也能强制下线。"""

    KEY_PREFIX = "riverat:session:"

    def __init__(self, url: str) -> None:
        self._redis = Redis.from_url(url, decode_responses=True)

    async def create(self, user_id: UUID, ttl_seconds: int) -> str:
        token = _new_token()
        await self._redis.setex(f"{self.KEY_PREFIX}{token}", ttl_seconds, str(user_id))
        return token

    async def get(self, token: str) -> UUID | None:
        raw = await self._redis.get(f"{self.KEY_PREFIX}{token}")
        if raw is None:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None

    async def delete(self, token: str) -> None:
        await self._redis.delete(f"{self.KEY_PREFIX}{token}")

    async def close(self) -> None:
        await self._redis.aclose()
