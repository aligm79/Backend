"""Password hashing (Argon2id) and JWT issue/verify.

Argon2id PHC params match the .NET PasswordHasher (m=65536, t=3, p=4, 16-byte salt,
32-byte hash) so existing hashes verify unchanged. JWT uses one HS256 key with three
audiences (`dmp/admins`, `dmp/users`, `dmp/verification`) — identical to JwtService.
Subjects are GUIDs formatted without hyphens (`.hex`), matching `Guid.ToString("N")`.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import get_settings

# Same params as the .NET PasswordHasher.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

USER_AUDIENCE = "dmp/users"
ADMIN_AUDIENCE = "dmp/admins"
VERIFICATION_AUDIENCE = "dmp/verification"


# ── Password hashing ────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return an Argon2id PHC string. argon2-cffi produces the exact `$argon2id$v=19$m=…` form."""
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time verify against an Argon2id PHC string. False on empty/garbage."""
    if not stored or not stored.startswith("$argon2"):
        return False
    try:
        return _hasher.verify(stored, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ── JWT ─────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _write_token(
    subject_id: str,
    audience: str,
    not_before: datetime,
    expires: datetime,
    extra_claims: dict[str, str],
) -> str:
    settings = get_settings()
    # PyJWT reads iss/aud/iat/nbf/exp from the payload (no encode() kwargs for these).
    claims: dict[str, Any] = {
        "sub": subject_id,
        "jti": uuid.uuid4().hex,
        "iat": int(not_before.timestamp()),
        "nbf": int(not_before.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": audience,
    }
    claims.update(extra_claims)
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")
    return token  # PyJWT >=2 returns str


def issue_pair(
    subject_id: str, audience: str, extra_claims: dict[str, str]
) -> tuple[str, str, datetime]:
    """Issue a fresh (access, refresh, refresh_expires_at) triple."""
    settings = get_settings()
    now = _now()
    access_expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    refresh_expires = now + timedelta(days=settings.refresh_token_expire_days)

    access = _write_token(subject_id, audience, now, access_expires, extra_claims)
    refresh_claims = dict(extra_claims)
    refresh_claims["typ"] = "refresh"
    refresh = _write_token(subject_id, audience, now, refresh_expires, refresh_claims)
    return access, refresh, refresh_expires


def issue_verification(
    identifier: str, extra_claims: dict[str, str]
) -> tuple[str, datetime]:
    """Short-lived token for in-progress OTP/email flows."""
    settings = get_settings()
    now = _now()
    expires = now + timedelta(minutes=max(1, settings.otp_ttl_minutes + 2))
    claims = dict(extra_claims)
    claims["identifier"] = identifier
    return _write_token(identifier, VERIFICATION_AUDIENCE, now, expires, claims), expires


def decode_token(token: str, audience: str) -> dict[str, Any]:
    """Decode + validate a JWT for the given audience. Raises AppException on failure."""
    from .envelope import AppException

    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=["HS256"],
            audience=audience,
            issuer=settings.jwt_issuer,
            leeway=0,  # ClockSkew = Zero
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppException.unauthorized("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AppException.unauthorized("Invalid token") from exc


# ── OTP code helpers ────────────────────────────────────────────────────────────


def hash_code(code: str) -> str:
    """SHA-256 hex of the OTP code (uppercase hex, matching Convert.ToHexString)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest().upper()


def fixed_equals(a: str, b: str) -> bool:
    """Constant-time string comparison (CryptographicOperations.FixedTimeEquals parity)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def new_uuid_hex() -> str:
    """GUID without hyphens, matching `Guid.ToString("N")` used for JWT `sub`."""
    return uuid.uuid4().hex
