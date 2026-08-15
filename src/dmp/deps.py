"""Authentication dependencies.

Three security schemes share one HS256 key but validate different audiences, mirroring
the .NET `AdminToken`/`UserToken`/`VerificationToken` JWT bearer schemes. Each reads its
own header (`X-Admin-Token` / `X-User-Token`) and falls back to `Authorization: Bearer`.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, Header
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from . import security
from .db import get_session
from .domain.models import Admin, User
from .envelope import AppException

# Declared so OpenAPI shows the API-key security definitions (parity with Swagger).
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)
user_token_header = APIKeyHeader(name="X-User-Token", auto_error=False)


def _bearer_fallback(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def current_admin_id(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Validate an admin JWT and return the admin's UUID hex (`sub`)."""
    token = x_admin_token or _bearer_fallback(authorization)
    if not token:
        raise AppException.unauthorized()
    claims = security.decode_token(token, security.ADMIN_AUDIENCE)
    sub = claims.get("sub")
    if not sub:
        raise AppException.unauthorized()
    return sub


async def current_admin(
    admin_id: str = Depends(current_admin_id),
    session: AsyncSession = Depends(get_session),
) -> Admin:
    from sqlalchemy import select

    admin = (await session.execute(select(Admin).where(Admin.id == admin_id))).scalar_one_or_none()
    if not admin or not admin.is_active:
        raise AppException.forbidden("Admin account is disabled")
    return admin


def is_super_admin(admin: Admin) -> bool:
    from .domain.enums import AdminRole

    return admin.role == AdminRole.SuperAdmin


async def current_user_id(
    x_user_token: str | None = Header(default=None, alias="X-User-Token"),
    authorization: str | None = Header(default=None),
) -> str:
    """Validate a user JWT and return the user's UUID hex (`sub`)."""
    token = x_user_token or _bearer_fallback(authorization)
    if not token:
        raise AppException.unauthorized()
    claims = security.decode_token(token, security.USER_AUDIENCE)
    sub = claims.get("sub")
    if not sub:
        raise AppException.unauthorized()
    return sub


async def current_user(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> User:
    from sqlalchemy import select

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise AppException.not_found("User not found")
    return user


def parse_uuid(value: str) -> uuid.UUID:
    """Parse a UUID, raising AppException.bad_request on failure."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise AppException.bad_request("Invalid id format") from exc
