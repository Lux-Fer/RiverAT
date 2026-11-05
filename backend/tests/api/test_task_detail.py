"""任务详情（D133）：步骤流、草案改参数、完成后重跑。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Task, TaskStep


def _task(status: str = "running", **kwargs) -> Task:
    now = datetime.now(UTC)
    return Task(
        title="任务详情里的回归",
        request_text="回归登录与支付",
        status=status,
        created_at=now - timedelta(minutes=5),
        approved_at=now - timedelta(minutes=4) if status != "draft" else None,
        **kwargs,
    )


async def test_task_detail_shows_steps_and_cases(session, client):
    task = _task()
    session.add(task)
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_name="web-login",
            tool_version="1.2.0",
            args={"base_url": "http://target:8080"},
            status="passed",
            output={
                "cases": [
                    {"case_id": "login-001", "status": "passed", "duration_ms": 820}
                ]
            },
            exit_code=0,
            started_at=datetime.now(UTC) - timedelta(seconds=40),
            finished_at=datetime.now(UTC) - timedelta(seconds=20),
        )
    )
    await session.commit()

    page = await client.get(f"/tasks/{task.id}")

    assert page.status_code == 200
    assert "任务详情里的回归" in page.text
    assert "web-login" in page.text
    assert "用例结果" in page.text
    assert "login-001" in page.text
    assert "运行中" in page.text


async def test_draft_task_detail_allows_edit_and_approve(session, client):
    task = _task("draft")
    session.add(task)
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_name="web-login",
            tool_version="1.2.0",
            args={"base_url": "http://target:8080"},
            status="pending",
        )
    )
    await session.commit()

    page = await client.get(f"/tasks/{task.id}")

    assert page.status_code == 200
    assert "确认执行" in page.text
    assert "改参数" in page.text
    assert 'name="args"' in page.text
    assert "重跑" not in page.text


async def test_completed_task_detail_offers_rerun(session, client):
    task = _task("passed", finished_at=datetime.now(UTC))
    session.add(task)
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_name="web-login",
            tool_version="1.2.0",
            args={},
            status="passed",
            output={},
            exit_code=0,
        )
    )
    await session.commit()

    page = await client.get(f"/tasks/{task.id}")

    assert page.status_code == 200
    assert "重跑" in page.text
    assert "确认执行" not in page.text


async def test_sub_second_step_renders_less_than_one_second(session, client):
    now = datetime.now(UTC)
    task = _task("passed", finished_at=now)
    session.add(task)
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_name="web-login",
            tool_version="1.2.0",
            args={},
            status="passed",
            output={},
            exit_code=0,
            started_at=now - timedelta(milliseconds=200),
            finished_at=now,
        )
    )
    await session.commit()

    page = await client.get(f"/tasks/{task.id}")

    assert page.status_code == 200
    assert "&lt;1s" in page.text
