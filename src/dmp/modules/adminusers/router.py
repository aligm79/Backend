"""Admin user management: paginated list/search, edit, suspend, password reset."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_session
from ...deps import current_admin
from ...domain.enums import UserStatus
from ...domain.models import Admin, User
from ...envelope import AppException, ok
from ...security import hash_password
from .dto import AdminUserResponse, AdminUserUpdateRequest

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin users"])


def _to_response(u: User) -> dict:
    return AdminUserResponse(
        id=u.id,
        username=u.username,
        email=u.email,
        phoneNumber=u.phone_number,
        firstName=u.first_name,
        lastName=u.last_name,
        status=u.status.value if hasattr(u.status, "value") else str(u.status),
        emailVerified=u.email_verified,
        phoneVerified=u.phone_number_verified,
        preferredLanguage=u.preferred_language,
        createdAt=u.created_at,
    ).model_dump(exclude_none=True)


def _parse_status(value: str) -> UserStatus:
    v = (value or "").strip().lower().replace("_", "")
    for s in UserStatus:
        if s.value.lower() == v:
            return s
    raise AppException.validation(f"Invalid status: {value}")


@router.get("")
async def list_users(
    search: str | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    p = max(1, page)
    lim = max(1, min(100, limit))

    stmt = select(User)
    if search and search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(like),
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(User.status == _parse_status(status))

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(stmt.order_by(User.created_at.desc()).offset((p - 1) * lim).limit(lim))
    ).scalars().all()

    items = [_to_response(u) for u in rows]
    return ok({"items": items, "meta": {"total": total, "page": p, "limit": lim, "total_page": math.ceil(total / lim)}})


@router.get("/{id}")
async def get_user(
    id: str,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    u = (await session.execute(select(User).where(User.id == id))).scalar_one_or_none()
    if u is None:
        raise AppException.not_found("User not found")
    return ok(_to_response(u))


@router.put("/{id}")
async def update_user(
    id: str,
    req: AdminUserUpdateRequest,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    u = (await session.execute(select(User).where(User.id == id))).scalar_one_or_none()
    if u is None:
        raise AppException.not_found("User not found")

    if req.firstName is not None:
        u.first_name = req.firstName
    if req.lastName is not None:
        u.last_name = req.lastName
    if req.status is not None:
        u.status = _parse_status(req.status)
    if req.password is not None:
        settings = get_settings()
        if len(req.password) < settings.password_min_length:
            raise AppException.validation(
                f"Password must be at least {settings.password_min_length} characters"
            )
        u.password_hash = hash_password(req.password)

    await session.commit()
    await session.refresh(u)
    return ok(_to_response(u))


@router.delete("/{id}")
async def delete_user(
    id: str,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    """Hard-delete a user and their dependent rows (payments, subscriptions,
    applications cascade). Use suspend for reversible action."""
    from sqlalchemy import delete as sa_delete

    from ...deps import parse_uuid
    from ...domain.models import Application, Payment, Subscription

    parse_uuid(id)  # 400 on malformed ids
    u = (await session.execute(select(User).where(User.id == id))).scalar_one_or_none()
    if u is None:
        raise AppException.not_found("User not found")

    await session.execute(sa_delete(Payment).where(Payment.user_id == id))
    await session.execute(sa_delete(Subscription).where(Subscription.user_id == id))
    await session.execute(sa_delete(Application).where(Application.user_id == id))
    await session.delete(u)
    await session.commit()
    return ok()
