"""FastAPI 入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.services.auth import ensure_bootstrap_admin
from app.web.pages import router as pages_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _bootstrap_admin()
    yield
    store = getattr(app.state, "session_store", None)
    if store is not None:
        await store.close()
    await dispose_engine()


async def _bootstrap_admin() -> None:
    """库里没有用户且配置了 ADMIN_PASSWORD 时，建第一个管理员。"""

    settings = get_settings()
    if not settings.admin_password:
        return
    try:
        async with get_sessionmaker()() as session:
            await ensure_bootstrap_admin(
                session,
                username=settings.admin_username,
                password=settings.admin_password,
            )
    except Exception:  # noqa: BLE001 - 启动时数据库不可用不应挡住进程
        return


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse | RedirectResponse:
        # 页面未登录 → 跳登录页；接口保持 JSON 401
        if exc.status_code == 401 and not request.url.path.startswith("/api"):
            return RedirectResponse(
                f"/login?next={request.url.path}", status_code=303
            )
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(pages_router)
    return app


app = create_app()
