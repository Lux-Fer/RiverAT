"""CSRF 防护（D75）：双提交 Cookie。

* 中间件在响应里种一个**非 HttpOnly** 的 `riverat_csrf` Cookie；
* 页面上每个表单带隐藏字段 `csrf_token`（由 `_csrf_input.html` 渲染）；
* 页面 POST 路由统一挂 `require_csrf` 依赖，不一致直接 403。

JSON API 不需要这个：浏览器跨站发 JSON 会触发 CORS 预检，拿不到响应。
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

CSRF_COOKIE = "riverat_csrf"
CSRF_HEADER = "X-CSRF-Token"


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    token = request.headers.get(CSRF_HEADER)

    if not token:
        form = await request.form()
        value = form.get("csrf_token")
        token = str(value) if value is not None else None

    if not cookie or not token or not secrets.compare_digest(token, cookie):
        raise HTTPException(status_code=403, detail="CSRF 校验失败，请刷新页面后重试")


async def csrf_cookie_middleware(request: Request, call_next):
    cookie = request.cookies.get(CSRF_COOKIE)
    token = cookie or new_token()
    request.state.csrf_token = token

    response = await call_next(request)
    if cookie is None:
        response.set_cookie(
            CSRF_COOKIE,
            token,
            max_age=8 * 3600,
            httponly=False,
            samesite="lax",
        )
    return response
