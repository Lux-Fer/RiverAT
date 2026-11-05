"""审计页（D138）：台账列名、动作中文、详情展开与筛选。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import AuditLog


async def _log(session, username: str = "admin", action: str = "task.approve") -> None:
    session.add(
        AuditLog(
            username=username,
            action=action,
            target_type="task",
            target_id="abcd1234-0000-0000-0000-000000000000",
            detail={"title": "登录冒烟", "steps": 2},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def test_audit_page_shows_ledger(session, client):
    await _log(session)

    page = await client.get("/audit")

    assert page.status_code == 200
    text = page.text
    assert "审计日志" in text
    assert "确认任务" in text
    assert "admin" in text
    assert "任务 · abcd1234" in text
    assert "title=登录冒烟" in text
    assert "时间" in text and "操作人" in text and "动作" in text
    assert "导出 CSV" in text


async def test_audit_filter_shows_clear_and_empty(session, client):
    page = await client.get("/audit?username=ghost")

    assert page.status_code == 200
    assert 'value="ghost"' in page.text
    assert "清除" in page.text
    assert "没有匹配的审计记录" in page.text
    assert "0 条匹配" in page.text
