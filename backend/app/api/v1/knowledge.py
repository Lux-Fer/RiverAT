"""失败归因：相似历史失败（D25 v1）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_user
from app.db.session import get_session
from app.services.knowledge import similar_to_run
from app.services.runs import get_run

router = APIRouter(prefix="/runs", tags=["knowledge"])


@router.get("/{run_id}/similar")
async def similar(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(require_user)],
) -> dict:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")

    items = await similar_to_run(session, run_id)
    return {
        "run_id": str(run_id),
        "count": len(items),
        "items": [
            {
                "run_id": str(item["run_id"]),
                "title": item["title"],
                "score": round(float(item["score"]), 3),
                "excerpt": item["content"][:400],
            }
            for item in items
        ],
    }
