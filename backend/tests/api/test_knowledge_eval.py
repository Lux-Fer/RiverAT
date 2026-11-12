"""V0.2.3 检索评测：hit@1 / hit@3 / MRR。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.evaluation.knowledge_eval import RetrievalCase, evaluate_retrieval
from app.models import KnowledgeItem, WorkProduct
from app.services.knowledge_base import record_event, record_retrieval, retrieval_metrics


async def _item(session, key: str, title: str, body: str, **kwargs) -> KnowledgeItem:
    values = {
        "item_key": key,
        "kind": "failure_pattern",
        "title": title,
        "body": body,
        "scope": "global",
        "status": "approved",
    }
    values.update(kwargs)
    item = KnowledgeItem(**values)
    session.add(item)
    await session.flush()
    return item


async def test_eval_hit_and_empty(session):
    await _item(
        session,
        "eval-login",
        "登录 connection refused",
        "登录地址不可达时先检查目标服务",
    )
    await _item(
        session,
        "eval-expired",
        "登录 connection refused 旧经验",
        "已经过期的经验",
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )
    await session.commit()

    report = await evaluate_retrieval(
        session,
        [
            RetrievalCase(
                query="登录 connection refused",
                expected_item_key="eval-login",
            ),
            RetrievalCase(
                query="完全无关的支付回调",
                expected_item_key=None,
                expect_empty=True,
            ),
        ],
    )

    assert report.total == 2
    assert report.hit_at_1 == 1.0
    assert report.hit_at_3 == 1.0
    assert report.mrr == 1.0
    assert report.details[0].returned[0] == "eval-login"
    assert "eval-expired" not in report.details[0].returned


async def test_eval_respects_product_scope(session):
    product_a = WorkProduct(code="EVAL-A", name="评测 A", status="active")
    product_b = WorkProduct(code="EVAL-B", name="评测 B", status="active")
    session.add_all([product_a, product_b])
    await session.flush()
    await _item(
        session,
        "eval-a",
        "产品 A 登录失败",
        "connection refused",
        product_id=product_a.id,
        scope="product",
    )
    await _item(
        session,
        "eval-b",
        "产品 B 登录失败",
        "connection refused",
        product_id=product_b.id,
        scope="product",
    )
    await session.commit()

    report = await evaluate_retrieval(
        session,
        [
            RetrievalCase(
                query="登录失败 connection refused",
                expected_item_key="eval-a",
                product_id=product_a.id,
            )
        ],
    )

    assert report.hit_at_1 == 1.0
    assert report.details[0].returned == ["eval-a"]


async def test_retrieval_metrics_include_empty(session):
    user_id = uuid.uuid4()
    await record_retrieval(
        session,
        consumer="plan",
        task_id=None,
        product_id=None,
        items=[],
    )
    await record_retrieval(
        session,
        consumer="plan",
        task_id=None,
        product_id=None,
        items=[{"id": uuid.uuid4(), "kind": "failure_pattern", "score": 0.4}],
    )
    await record_event(
        session,
        event_key=f"metrics-test:{uuid.uuid4()}",
        kind="knowledge.feedback",
        task_id=None,
        actor_id=user_id,
        payload={"helpful": True},
    )
    await session.commit()

    metrics = await retrieval_metrics(session, days=30)

    assert metrics["retrievals"] == 2
    assert metrics["empty"] == 1
    assert metrics["empty_rate"] == 0.5
    assert metrics["avg_items"] == 0.5
