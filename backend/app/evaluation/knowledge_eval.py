"""V0.2.3：检索评测骨架（不依赖模型/向量）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_base import search_knowledge


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    expected_item_key: str | None
    product_id: UUID | None = None
    user_id: UUID | None = None
    expect_empty: bool = False


@dataclass
class CaseResult:
    query: str
    expected_item_key: str | None
    rank: int | None
    passed: bool
    returned: list[str] = field(default_factory=list)


@dataclass
class RetrievalReport:
    total: int
    hit_at_1: float
    hit_at_3: float
    mrr: float
    details: list[CaseResult]


async def evaluate_retrieval(
    session: AsyncSession, cases: list[RetrievalCase], *, limit: int = 3
) -> RetrievalReport:
    results: list[CaseResult] = []
    for case in cases:
        items = await search_knowledge(
            session,
            case.query,
            product_id=case.product_id,
            user_id=case.user_id,
            limit=limit,
        )
        keys = [str(item.get("item_key")) for item in items]
        rank = None
        if case.expect_empty:
            passed = not items
        elif case.expected_item_key:
            try:
                rank = keys.index(case.expected_item_key) + 1
            except ValueError:
                rank = None
            passed = rank is not None
        else:
            passed = True
        results.append(
            CaseResult(
                query=case.query,
                expected_item_key=case.expected_item_key,
                rank=rank,
                passed=passed,
                returned=keys,
            )
        )

    total = len(results)
    hit1 = sum(
        1
        for result in results
        if result.passed
        and (
            result.rank == 1
            or (result.expected_item_key is None and not result.returned)
        )
    )
    hit3 = sum(
        1
        for result in results
        if result.passed
        and (
            (result.rank is not None and result.rank <= 3)
            or (result.expected_item_key is None and not result.returned)
        )
    )
    reciprocal = sum(
        (1 / result.rank if result.rank is not None else 1.0)
        for result in results
        if result.passed
    )
    return RetrievalReport(
        total=total,
        hit_at_1=round(hit1 / total, 3) if total else 0.0,
        hit_at_3=round(hit3 / total, 3) if total else 0.0,
        mrr=round(reciprocal / total, 3) if total else 0.0,
        details=results,
    )
