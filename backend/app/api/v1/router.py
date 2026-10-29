"""v1 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.catalog import router as catalog_router
from app.api.v1.plans import router as plans_router
from app.api.v1.runs import router as runs_router

api_router = APIRouter()
api_router.include_router(catalog_router)
api_router.include_router(plans_router)
api_router.include_router(runs_router)


@api_router.get("/ping", tags=["meta"])
async def ping() -> dict[str, str]:
    return {"pong": "riverat"}
