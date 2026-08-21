"""FastAPI application factory + composition root.

Wires:
  - lifespan: optional Alembic auto-migrate, then the idempotent seeder
  - exception handlers → the `{ code, meta }` envelope
  - CORS (from BACKEND_CORS_ORIGINS)
  - per-IP rate limiting: global token bucket + a strict fixed-window for auth paths
  - OpenAPI split into admin/client docs at /docs (Swagger), parity with the .NET stack
  - static files serving for bundled university sample photos (/university-covers, /university-logos)
  - all module routers (auth, billing, catalog, applications)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import get_session_factory
from .envelope import (
    AppException,
    app_exception_handler,
    error,
    unhandled_exception_handler,
    validation_exception_handler,
)
from .modules.applications.router import router_admin as apps_admin
from .modules.applications.router import router_client as apps_client
from .modules.auth.router import router_admin as auth_admin
from .modules.auth.router import router_client as auth_client
from .modules.billing.router import router_admin as billing_admin
from .modules.billing.router import router_client as billing_client
from .modules.billing.router import router_public as billing_public
from .modules.catalog.router import router_admin as catalog_admin
from .modules.catalog.router import router_client as catalog_client
from .modules.catalog.router import router_public as catalog_public
from .modules.profile.router import router as profile_router
from .seed.seeder import seed_all

log = logging.getLogger("dmp")
logging.basicConfig(level=logging.INFO)

AUTH_PATHS = {
    "/api/v1/admin/auth/login",
    "/api/v1/client/auth/register",
    "/api/v1/client/auth/login",
    "/api/v1/client/auth/otp/send",
    "/api/v1/client/auth/otp/verify",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Validate the JWT key length (parity with the .NET startup guard).
    if len(settings.jwt_secret_key.encode("utf-8")) < 32:
        raise RuntimeError(
            "jwt_secret_key must be at least 32 UTF-8 bytes (set JWT_SECRET_KEY)."
        )

    if settings.database_auto_migrate:
        await _run_migrations()

    async with get_session_factory()() as session:
        await seed_all(session)

    log.info("[STARTUP] env=%s docs=%s", settings.environment, settings.docs_enabled)
    yield


async def _run_migrations() -> None:
    """Apply Alembic migrations to head (gated by DATABASE__AUTO_MIGRATE=true)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent.parent / "alembic.ini"))
    # Point Alembic at the repo-relative migrations/ directory.
    cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parent.parent.parent / "migrations")
    )
    import asyncio

    await asyncio.to_thread(command.upgrade, cfg, "head")


# ── Simple in-memory rate limiter ──────────────────────────────────────────────
# Two policies mirroring RateLimitingSetup.cs:
#   - global: per-IP token bucket, 100 tokens, +20/sec
#   - auth:   per-IP fixed window, 10 req/min on AUTH_PATHS
# In-memory is fine for a single-process deployment; for multi-process, swap in Redis.


class _TokenBucket:
    __slots__ = ("tokens", "last", "_capacity", "_refill")

    def __init__(self, capacity: float, refill_per_sec: float):
        self.tokens = capacity
        self.last = time.monotonic()
        self._capacity = capacity
        self._refill = refill_per_sec

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self._capacity, self.tokens + (now - self.last) * self._refill)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class _FixedWindow:
    __slots__ = ("count", "window_start", "_limit", "_window")

    def __init__(self, limit: int, window_sec: float):
        self.count = 0
        self.window_start = time.monotonic()
        self._limit = limit
        self._window = window_sec

    def take(self) -> bool:
        now = time.monotonic()
        if now - self.window_start >= self._window:
            self.window_start = now
            self.count = 0
        if self.count < self._limit:
            self.count += 1
            return True
        return False


_global_buckets: dict[str, _TokenBucket] = defaultdict(lambda: _TokenBucket(100, 20.0))
_auth_windows: dict[str, _FixedWindow] = defaultdict(lambda: _FixedWindow(10, 60.0))


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    ip = _client_ip(request)
    if path in AUTH_PATHS:
        if not _auth_windows[ip].take():
            return JSONResponse(
                status_code=429,
                content=error(
                    "RATE_LIMITED",
                    {"message": "Too many requests. Please slow down.", "retryAfterSeconds": 60},
                ),
            )
    else:
        if not _global_buckets[ip].take():
            return JSONResponse(
                status_code=429,
                content=error(
                    "RATE_LIMITED",
                    {"message": "Too many requests. Please slow down.", "retryAfterSeconds": 1},
                ),
            )
    return await call_next(request)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Data Marketplace API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── Exception handlers → { code, meta } envelope ────────────────────────────
    app.add_exception_handler(AppException, app_exception_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ── Rate limiting (custom middleware) ───────────────────────────────────────
    app.middleware("http")(rate_limit_middleware)

    # ── CORS ───────────────────────────────────────────────────────────────────
    origins = settings.cors_origins
    allow_any = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_any else origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ────────────────────────────────────────────────────────────────
    app.include_router(auth_admin)
    app.include_router(auth_client)
    app.include_router(billing_admin)
    app.include_router(billing_client)
    app.include_router(billing_public)
    app.include_router(catalog_admin)
    app.include_router(catalog_client)
    app.include_router(catalog_public)
    app.include_router(apps_client)
    app.include_router(apps_admin)
    app.include_router(profile_router)

    # ── Static files: bundled university sample photos ─────────────────────────
    # The frontend ships its own copies; these mount the backend-side assets used
    # when the API is browsed standalone. Best-effort — skip if dir absent.
    public_dir = Path(__file__).resolve().parent.parent.parent / "public"
    if public_dir.is_dir():
        app.mount("/university-covers", StaticFiles(directory=public_dir / "university-covers"), name="covers")
        app.mount("/university-logos", StaticFiles(directory=public_dir / "university-logos"), name="logos")

    # ── Swagger docs at /docs (only when DOCS_ENABLED) ──────────────────────────
    if settings.docs_enabled:
        from fastapi.openapi.docs import get_swagger_ui_html
        from fastapi.openapi.utils import get_openapi

        def _openapi(admin: bool):
            spec = get_openapi(
                title=app.title,
                version=app.version,
                routes=app.routes,
            )
            # Split by tag namespace: admin = admin/* routes; client = the rest.
            is_admin_path = lambda r_path: r_path.startswith("/api/v1/admin")  # noqa: E731
            keep = []
            for r in spec["paths"]:
                if admin == is_admin_path(r):
                    keep.append(r)
            spec["paths"] = {k: spec["paths"][k] for k in keep}
            return spec

        @app.get("/docs", include_in_schema=False)
        async def swagger_ui():
            return get_swagger_ui_html(
                openapi_url="/openapi.json",
                title="Data Marketplace API",
                swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
                swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
            )

    return app


app = create_app()
