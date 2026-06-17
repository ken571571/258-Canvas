"""FastAPI 应用实例 + 中间件"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from . import config


# ——— 鉴权中间件 ———
class AuthMiddleware(BaseHTTPMiddleware):
    """简单的 API Key / Bearer Token 鉴权。

    公开路径（无需鉴权）：
      - GET  /           首页
      - GET  /static/*   静态资源
      - GET  /assets/*   素材文件
      - WS   /ws         WebSocket
      - GET  /health     健康检查
    """

    PUBLIC_PREFIXES = ("/static/", "/assets/", "/ws")
    PUBLIC_EXACT = {"/", "/health"}

    LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}

    def _is_local_request(self, request: Request) -> bool:
        client_host = request.client.host if request.client else ""
        return client_host in self.LOCAL_CLIENTS

    async def dispatch(self, request: Request, call_next):
        # 公开路径跳过鉴权
        path = request.url.path
        if path in self.PUBLIC_EXACT or any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return await call_next(request)

        # 未配置 API Key：仅允许本机访问，避免 0.0.0.0 监听时局域网裸奔。
        if not config.runtime.app_api_key:
            if self._is_local_request(request):
                return await call_next(request)
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "未配置 APP_API_KEY，非本机访问已被拒绝"},
            )

        # 验证 API Key
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = request.headers.get("X-API-Key", "")

        if token != config.runtime.app_api_key:
            raise HTTPException(status_code=401, detail="未授权：请提供有效的 API Key")

        return await call_next(request)


# ——— 安全头中间件 ———
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """添加安全相关的 HTTP 响应头。"""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # 首页通过同源 iframe 组织多个工作页，不能使用 DENY。
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # 开发阶段禁用 HTML 缓存，确保始终加载最新代码
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        # 如果未来上 HTTPS，取消下面这行的注释：
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ——— 速率限制中间件 ———
class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单的内存速率限制（按 IP）。

    只对 API 路由限流，静态资源和公开路径跳过。
    """

    PUBLIC_PREFIXES = ("/static/", "/assets/", "/input/", "/output/", "/ws")
    PUBLIC_EXACT = {"/", "/health", "/favicon.ico"}

    def __init__(self, app, requests_per_window: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._clients: dict = {}

    async def dispatch(self, request: Request, call_next):
        if not config.runtime.rate_limit_enabled:
            return await call_next(request)

        # 静态资源和公开路径不参与限流计数
        path = request.url.path
        if path in self.PUBLIC_EXACT or any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return await call_next(request)

        import time
        from fastapi.responses import JSONResponse

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        entry = self._clients.get(client_ip)

        if entry is None or now - entry["window_start"] > self.window_seconds:
            entry = {"window_start": now, "count": 1}
            self._clients[client_ip] = entry
        else:
            entry["count"] += 1

        if entry["count"] > self.requests_per_window:
            # 返回 JSONResponse 而非 raise HTTPException，
            # 避免 BaseHTTPMiddleware 内 ExceptionGroup 包装导致 500
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(self.window_seconds)},
            )

        # 清理过期条目（每 500 个请求清理一次）
        if len(self._clients) > 1000:
            self._clients = {
                ip: e for ip, e in self._clients.items()
                if now - e["window_start"] <= self.window_seconds
            }

        return await call_next(request)


# ——— 创建应用 ———
app = FastAPI(title="无限画布", version=config.APP_VERSION)

# 全局异常处理：确保所有未捕获异常都返回 JSON（而非 Starlette 默认的 HTML）
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    detail = f"{type(exc).__name__}: {exc}"
    # 开发环境打印完整堆栈便于排查
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": detail})

# 添加中间件（顺序很重要：最后添加的先执行）
# 1. 安全头
app.add_middleware(SecurityHeadersMiddleware)

# 2. 速率限制（可选）
if config.runtime.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=config.runtime.rate_limit_requests,
        window_seconds=config.runtime.rate_limit_window,
    )

# 3. 鉴权
app.add_middleware(AuthMiddleware)

# 4. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS if config.CORS_ORIGINS else [],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# 挂载静态目录
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=config.ASSETS_DIR), name="assets")
app.mount("/input", StaticFiles(directory=config.INPUT_DIR), name="input")
app.mount("/output", StaticFiles(directory=config.OUTPUT_DIR), name="output")
