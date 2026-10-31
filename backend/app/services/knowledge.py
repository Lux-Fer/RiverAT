"""失败归因知识库（D25/D26 v1）。

v1 只吃"平台自己的执行历史"：每次失败/异常执行写一条 ``knowledge_source``，
正文切成 ``knowledge_chunk``；检索用 PostgreSQL 的 pg_trgm 相似度（中文按字符
三元组切分），不依赖 embedding 模型，离线可用。接 Jira/文档时只需新增 source 类型。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeChunk, KnowledgeDoc, KnowledgeSource, Run, RunStep

_MAX_SIGNATURE_CHARS = 4000


def _failure_signature(run: Run, steps: list[RunStep]) -> str:
    """把一次失败执行压成"可比较的文本"，用于相似度检索。"""

    lines = [f"执行失败 trigger={run.trigger} 状态={run.status}"]
    for step in steps:
        if step.status not in ("failed", "error"):
            continue
        evidence = step.evidence or {}
        lines.append(
            f"节点 {step.node_key}: {step.status} exit={step.exit_code} "
            f"reason={step.reason or ''}"
        )
        stderr = (evidence.get("stderr") or "").strip()
        stdout = (evidence.get("stdout") or "").strip()
        if stderr:
            lines.append(f"stderr: {stderr[-800:]}")
        if stdout:
            lines.append(f"stdout: {stdout[-400:]}")
    return "\n".join(lines)[:_MAX_SIGNATURE_CHARS]


async def index_run(session: AsyncSession, run: Run) -> None:
    """失败执行入知识库；已入过的跳过（幂等）。"""

    if run.status not in ("failed", "error"):
        return

    existing = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.kind == "run", KnowledgeSource.ref_id == run.id
        )
    )
    if existing is not None:
        return

    steps = list(
        (
            await session.execute(select(RunStep).where(RunStep.run_id == run.id))
        )
        .scalars()
        .all()
    )
    content = _failure_signature(run, steps)
    if not content:
        return

    source = KnowledgeSource(kind="run", ref_id=run.id)
    session.add(source)
    await session.flush()

    doc = KnowledgeDoc(
        source_id=source.id, title=f"失败执行 {run.id}", content=content
    )
    session.add(doc)
    await session.flush()
    session.add(KnowledgeChunk(doc_id=doc.id, content=content))
    await session.flush()


async def signature_for_run(session: AsyncSession, run_id: UUID) -> str:
    run = await session.get(Run, run_id)
    if run is None:
        return ""
    steps = list(
        (
            await session.execute(select(RunStep).where(RunStep.run_id == run_id))
        )
        .scalars()
        .all()
    )
    return _failure_signature(run, steps)


_SIMILAR_SQL = text(
    """
    SELECT c.id AS chunk_id,
           d.title AS title,
           c.content AS content,
           s.ref_id AS run_id,
           similarity(c.content, :q) AS score
    FROM knowledge_chunk c
    JOIN knowledge_doc d ON d.id = c.doc_id
    JOIN knowledge_source s ON s.id = d.source_id
    WHERE similarity(c.content, :q) > 0.05
    ORDER BY score DESC
    LIMIT :limit
    """
)


async def similar_failures(
    session: AsyncSession,
    query: str,
    *,
    exclude_run_id: UUID | None = None,
    limit: int = 5,
) -> list[dict]:
    if not query.strip():
        return []

    rows = (
        (await session.execute(_SIMILAR_SQL, {"q": query, "limit": limit + 1}))
        .mappings()
        .all()
    )
    items = [dict(row) for row in rows]
    if exclude_run_id is not None:
        items = [item for item in items if item["run_id"] != exclude_run_id]
    return items[:limit]


async def similar_to_run(
    session: AsyncSession, run_id: UUID, *, limit: int = 5
) -> list[dict]:
    signature = await signature_for_run(session, run_id)
    return await similar_failures(
        session, signature, exclude_run_id=run_id, limit=limit
    )
