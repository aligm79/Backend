"""Application configuration.

Reads the same flat environment variables the .NET backend used (JWT_SECRET_KEY,
ADMIN_USERNAME, ZARINPAL__MERCHANT_ID, DATABASE_URL, …) so the existing `.env` and
compose env keep working unchanged. The double-underscore (`__`) nested keys
(ZARINPAL__*, DATABASE__AUTO_MIGRATE) are resolved explicitly in model_post_init —
they coexist with the flat keys (DATABASE_URL, etc.) the .NET EnvConfigBridge used.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env(*keys: str) -> str | None:
    """First non-empty value among the given env keys (case-insensitive scan)."""
    for k in keys:
        v = os.environ.get(k)
        if v is not None and v.strip() != "":
            return v
    # Case-insensitive fallback (env var casing varies across shells/OSes).
    lower = {k.lower(): v for k, v in os.environ.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v is not None and v.strip() != "":
            return v
    return None


def _env_bool(*keys: str, default: bool = False) -> bool:
    v = _env(*keys)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _resolve_database_url() -> str:
    """Resolve the async Postgres DSN.

    Priority mirrors the .NET PostgresConnectionGuard + EnvConfigBridge:
      1. DATABASE_URL / POSTGRES_URL (an async-capable or sync postgres URL)
      2. ConnectionStrings__Postgres (Npgsql format) — converted to a DSN
      3. POSTGRES_HOST + POSTGRES_DB + POSTGRES_USER + POSTGRES_PASSWORD parts
      4. a localhost default (matches appsettings.json)
    """
    explicit = _env("DATABASE_URL", "POSTGRES_URL")
    if explicit:
        return _to_async_dsn(explicit)

    npgsql = _env("ConnectionStrings__Postgres", "ConnectionStrings:Postgres")
    if npgsql:
        return _npgsql_to_dsn(npgsql)

    host = _env("POSTGRES_HOST", "DB_HOST")
    if host:
        db = _env("POSTGRES_DB", "POSTGRES_DATABASE", "DB_NAME") or "dmp_dev"
        user = _env("POSTGRES_USER", "DB_USER", "DB_USERNAME") or "postgres"
        password = _env("POSTGRES_PASSWORD", "DB_PASSWORD") or ""
        port = _env("POSTGRES_PORT", "DB_PORT") or "5432"
        auth = user if not password else f"{user}:{password}"
        return f"postgresql+asyncpg://{auth}@{host}:{port}/{db}"

    return "postgresql+asyncpg://postgres:postgres@localhost:5432/dmp_dev"


def _to_async_dsn(url: str) -> str:
    """Normalise a `postgresql://...` URL to the asyncpg driver form."""
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]
    if u.startswith("postgresql+asyncpg://"):
        return u
    if u.startswith("postgresql://"):
        return "postgresql+asyncpg://" + u[len("postgresql://"):]
    return u


def _npgsql_to_dsn(cs: str) -> str:
    """Convert an Npgsql `Host=…;Port=…;Database=…;Username=…;Password=…` string to a DSN."""
    parts: dict[str, str] = {}
    for seg in cs.split(";"):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, v = seg.split("=", 1)
        parts[k.strip().lower()] = v.strip()
    host = parts.get("host", "localhost")
    port = parts.get("port", "5432")
    db = parts.get("database", "dmp_dev")
    user = parts.get("username", parts.get("user id", "postgres"))
    password = parts.get("password", "")
    auth = user if not password else f"{user}:{password}"
    return f"postgresql+asyncpg://{auth}@{host}:{port}/{db}"


class Settings(BaseSettings):
    """All runtime settings. Env var names match the .NET backend's flat keys."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str = ""  # resolved in model_post_init if empty
    database_auto_migrate: bool = False

    # ── Auth ───────────────────────────────────────────────────────────────────
    jwt_secret_key: str = ""
    jwt_issuer: str = "Dmp"
    access_token_expire_minutes: int = 60 * 24
    refresh_token_expire_days: int = 30

    auto_create_default_admin: bool = True
    admin_username: str = "admin"
    admin_password: str = "@Admin1234"

    otp_code_length: int = 6
    otp_ttl_minutes: int = 3
    otp_max_attempts: int = 5

    password_min_length: int = 8

    # ── Redis (optional — cache / rate-limit store / queues when enabled) ─────
    redis_url: str = ""  # e.g. redis://localhost:6379/0

    # ── Kavenegar SMS (optional — OTP delivery via api.kavenegar.com) ─────────
    kavenegar_api_key: str = ""
    kavenegar_sender: str = ""  # dedicated sender line, optional
    kavenegar_otp_template: str = ""  # approved template name, e.g. abroadpath-otp

    # ── Zarinpal (env: ZARINPAL__MERCHANT_ID / __MODE / __CALLBACK_URL) ─────────
    zarinpal_merchant_id: str = "00000000-0000-0000-0000-000000000000"
    zarinpal_mode: str = "sandbox"
    zarinpal_callback_url: str = "http://localhost:5173/payment-result"

    # ── CORS ───────────────────────────────────────────────────────────────────
    backend_cors_origins: str = '["http://localhost:5173","http://localhost:3000"]'

    # ── Docs / logging / uploads ────────────────────────────────────────────────
    docs_enabled: bool = True
    log_dir: str = "logs"
    uploads_dir: str = "uploads"

    # ── Hosting ─────────────────────────────────────────────────────────────────
    backend_port: int = 8000
    environment: str = "Production"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.database_url:
            object.__setattr__(self, "database_url", _resolve_database_url())
        else:
            # Always normalise to the asyncpg driver form, even when DATABASE_URL is
            # a sync `postgresql://...` string (as used by the .NET stack / DATABASE_URL).
            object.__setattr__(self, "database_url", _to_async_dsn(self.database_url))

        # The .NET stack bridges a handful of env keys explicitly; mirror that here
        # so the same .env works for both backends.
        if not self.jwt_secret_key:
            v = _env("JWT_SECRET_KEY", "Auth__JwtSecretKey", "Auth:JwtSecretKey")
            if v:
                object.__setattr__(self, "jwt_secret_key", v)

        admin_user = _env("ADMIN_USERNAME", "Auth__AdminUsername")
        if admin_user:
            object.__setattr__(self, "admin_username", admin_user)
        admin_pass = _env("ADMIN_PASSWORD", "Auth__AdminPassword")
        if admin_pass:
            object.__setattr__(self, "admin_password", admin_pass)
        acda = _env("AUTO_CREATE_DEFAULT_ADMIN", "Auth__AutoCreateDefaultAdmin")
        if acda is not None:
            object.__setattr__(self, "auto_create_default_admin", _env_bool_value(acda))

        # Nested `__` keys for Zarinpal (ZARINPAL__MERCHANT_ID etc.).
        zm = _env("ZARINPAL__MERCHANT_ID", "Zarinpal__MerchantId", "Zarinpal:MerchantId")
        if zm:
            object.__setattr__(self, "zarinpal_merchant_id", zm)
        zmode = _env("ZARINPAL__MODE", "Zarinpal__Mode", "Zarinpal:Mode")
        if zmode:
            object.__setattr__(self, "zarinpal_mode", zmode)
        zcb = _env("ZARINPAL__CALLBACK_URL", "Zarinpal__CallbackUrl", "Zarinpal:CallbackUrl")
        if zcb:
            object.__setattr__(self, "zarinpal_callback_url", zcb)

        # Nested DATABASE__AUTO_MIGRATE.
        dam = _env("DATABASE__AUTO_MIGRATE", "Database__AutoMigrate")
        if dam is not None:
            object.__setattr__(self, "database_auto_migrate", _env_bool_value(dam))

        docs = _env("DOCS_ENABLED", "Docs__Enabled")
        if docs is not None:
            object.__setattr__(self, "docs_enabled", _env_bool_value(docs))

    # ── Derived helpers ─────────────────────────────────────────────────────────
    @property
    def cors_origins(self) -> list[str]:
        raw = self.backend_cors_origins.strip()
        if not raw:
            return ["http://localhost:5173", "http://localhost:3000"]
        if raw.startswith("["):
            import json

            try:
                return [o.strip() for o in json.loads(raw) if o.strip()]
            except Exception:
                return [o.strip() for o in raw.strip("[]").split(",") if o.strip()]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def zarinpal_is_sandbox(self) -> bool:
        return self.zarinpal_mode.lower() == "sandbox"


def _env_bool_value(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@lru_cache
def get_settings() -> Settings:
    return Settings()
