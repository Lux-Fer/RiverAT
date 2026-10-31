"""v1 路由汇总：登录公开，其余接口都要求登录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin, require_user
from app.api.v1.auth import router as auth_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.hosts import router as hosts_router
from app.api.v1.plans import router as plans_router
from app.api.v1.runs import router as runs_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(catalog_router, dependencies=[Depends(require_user)])
api_router.include_router(hosts_router, dependencies=[Depends(require_admin)])
api_router.include_router(plans_router, dependencies=[Depends(require_user)])
api_router.include_router(runs_router, dependencies=[Depends(require_user)])
api_router.include_router(users_router)


@api_router.get("/ping", tags=["meta"])
async def ping() -> dict[str, str]:
    return {"pong": "riverat"}
