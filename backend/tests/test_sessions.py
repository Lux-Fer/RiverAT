"""会话存储：按用户吊销（D74）。"""

from __future__ import annotations

import uuid

from app.core.sessions import InMemorySessionStore


async def test_revoke_user_kills_only_that_users_sessions():
    store = InMemorySessionStore()
    alice, bob = uuid.uuid4(), uuid.uuid4()

    a1 = await store.create(alice, 60)
    a2 = await store.create(alice, 60)
    b1 = await store.create(bob, 60)

    assert await store.revoke_user(alice) == 2
    assert await store.get(a1) is None
    assert await store.get(a2) is None
    assert await store.get(b1) == bob

    await store.close()
