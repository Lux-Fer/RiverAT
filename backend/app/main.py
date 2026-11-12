"""FastAPI 入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import get_settings, validate_production_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.services.auth import ensure_bootstrap_admin
from app.web.assistant_pages import router as assistant_pages_router
from app.web.audit_pages import router as audit_pages_router
from app.web.auth_pages import router as auth_pages_router
from app.web.csrf import csrf_cookie_middleware
from app.web.products_pages import router as products_pages_router
from app.web.settings_pages import router as settings_pages_router
from app.web.tasks_pages import router as tasks_pages_router
from app.web.templates import STATIC_DIR, templates
from app.web.tools_pages import router as tools_pages_router
from app.web.users_pages import router as users_pages_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _bootstrap_admin()
    await _setup_dispatcher(app)
    yield
    store = getattr(app.state, "session_store", None)
    if store is not None:
        await store.close()
    pool = getattr(app.state, "arq_pool", None)
    if pool is not None:
        await pool.aclose()
    await dispose_engine()


async def _setup_dispatcher(app: FastAPI) -> None:
    """有 Redis 就投递到 arq 队列；没有就退回就地执行。"""

    from arq import create_pool
    from arq.connections import RedisSettings

    from app.worker.dispatch import ArqDispatcher
    from app.worker.task_dispatch import ArqTaskDispatcher

    settings = get_settings()
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception:  # noqa: BLE001 - 队列不可用时不能挡住服务启动
        return

    app.state.arq_pool = pool
    app.state.dispatcher = ArqDispatcher(pool)
    app.state.task_dispatcher = ArqTaskDispatcher(pool)


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
    validate_production_settings(settings)
    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def readout_middleware(request, call_next):
        """页面顶部的平台读数条（模型/任务/待审工具），HTML 请求才取。"""

        request.state.readout = None
        wants_html = not request.url.path.startswith(("/static/", "/api/"))
        if request.method == "GET" and wants_html and request.url.path != "/login":
            from app.db.session import get_sessionmaker
            from app.services.readout import get_readout

            try:
                async with get_sessionmaker()() as session:
                    request.state.readout = await get_readout(session)
            except Exception:  # noqa: BLE001 - 读数失败不能挡住页面
                request.state.readout = None
        return await call_next(request)

    app.middleware("http")(csrf_cookie_middleware)

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
        # 页面无权限 → 一个能看懂的 403 页面
        if exc.status_code == 403 and not request.url.path.startswith("/api"):
            return templates.TemplateResponse(
                request=request,
                name="forbidden.html",
                context={"detail": exc.detail},
                status_code=403,
            )
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    app.include_router(api_router, prefix="/api/v1")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth_pages_router)
    app.include_router(assistant_pages_router)
    app.include_router(tasks_pages_router)
    app.include_router(products_pages_router)
    app.include_router(tools_pages_router)
    app.include_router(settings_pages_router)
    app.include_router(users_pages_router)
    app.include_router(audit_pages_router)
    return app


app = create_app()
