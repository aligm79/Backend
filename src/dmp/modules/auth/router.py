"""Auth API routers (admin, client). Path-for-path parity with AdminAuthController /
ClientAuthController. The auth endpoints (login/register/otp) carry the strict
per-IP rate-limit policy via the `@limiter.limit` decorator.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...deps import current_admin, current_user_id
from ...domain.enums import AdminRole
from ...domain.models import Admin
from ...envelope import ok
from . import service
from .dto import (
    AdminCreateRequest,
    AdminLoginRequest,
    AdminUpdateRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    UpdateUserRequest,
    UserLoginRequest,
    UserRegisterRequest,
)

router_admin = APIRouter(prefix="/api/v1/admin/auth", tags=["auth (admin)"])
router_client = APIRouter(prefix="/api/v1/client/auth", tags=["auth (client)"])


# ── Admin ───────────────────────────────────────────────────────────────────────


@router_admin.post("/login")
async def admin_login(req: AdminLoginRequest, session: AsyncSession = Depends(get_session)):
    # Strict per-IP auth limit (10/min) is enforced globally by the auth limiter
    # middleware on these paths; see main.py.
    token = await service.admin_login(session, req)
    return ok(token.model_dump(exclude_none=True))


@router_admin.get("/me")
async def admin_me(admin: Admin = Depends(current_admin)):
    from ...domain.enums import admin_role_to_jwt_string

    return ok({"id": admin.id, "username": admin.username, "role": admin_role_to_jwt_string(admin.role)})


@router_admin.post("/admins")
async def create_admin(
    req: AdminCreateRequest,
    admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    actor_is_super = admin.role == AdminRole.SuperAdmin
    result = await service.admin_create(session, req, admin.id, actor_is_super)
    return ok(result.model_dump(exclude_none=True))


@router_admin.get("/admins")
async def list_admins(
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    admins = await service.admin_list(session)
    return ok([a.model_dump(exclude_none=True) for a in admins])


@router_admin.put("/admins/{id}")
async def update_admin(
    id: str,
    req: AdminUpdateRequest,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await service.admin_update(session, id, req)
    return ok(result.model_dump(exclude_none=True))


# ── Client ──────────────────────────────────────────────────────────────────────


@router_client.post("/register")
async def register(req: UserRegisterRequest, session: AsyncSession = Depends(get_session)):
    token = await service.user_register(session, req)
    return ok(token.model_dump(exclude_none=True))


@router_client.post("/login")
async def login(req: UserLoginRequest, session: AsyncSession = Depends(get_session)):
    token = await service.user_login(session, req)
    return ok(token.model_dump(exclude_none=True))


@router_client.post("/otp/send")
async def otp_send(req: OtpSendRequest, session: AsyncSession = Depends(get_session)):
    result = await service.send_otp(session, req)
    return ok(result.model_dump(exclude_none=True))


@router_client.post("/otp/verify")
async def otp_verify(req: OtpVerifyRequest, session: AsyncSession = Depends(get_session)):
    token = await service.verify_otp(session, req)
    return ok(token.model_dump(exclude_none=True))


@router_client.get("/me")
async def me(user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_session)):
    result = await service.user_me(session, user_id)
    return ok(result.model_dump(exclude_none=True))


@router_client.put("/me")
async def update_me(
    req: UpdateUserRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await service.update_profile(session, user_id, req)
    return ok(result.model_dump(exclude_none=True))
