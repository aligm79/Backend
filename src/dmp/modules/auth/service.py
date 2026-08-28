"""Admin + user authentication. Direct port of AdminAuthService.cs / UserAuthService.cs.

Supports email/password AND phone/email OTP (two-step: send → verify). Passwords are
Argon2id PHC; OTP codes are SHA-256 hashed, logged in dev. JWT subjects are GUIDs
without hyphens.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import security
from ...config import get_settings
from ...db import utcnow
from ...domain.enums import AdminRole, UserStatus
from ...domain.models import Admin, Otp, User
from ...envelope import AppException
from ...security import (
    ADMIN_AUDIENCE,
    USER_AUDIENCE,
    fixed_equals,
    hash_code,
    hash_password,
    new_uuid_hex,
    verify_password,
)
from .dto import (
    AdminCreateRequest,
    AdminLoginRequest,
    AdminResponse,
    AdminUpdateRequest,
    OtpSendRequest,
    OtpSendResult,
    OtpVerifyRequest,
    TokenResponse,
    UpdateUserRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

log = logging.getLogger("dmp.auth")


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    return v.lower() if "@" in v else v


def _normalize(email: str | None, phone: str | None) -> tuple[str | None, str | None]:
    return _normalize_identifier(email), _normalize_identifier(phone)


def _admin_role_response(role: AdminRole | str) -> str:
    # "SuperAdmin" / "Admin" — matches the stored enum name (loaded rows may be str).
    return role.value if hasattr(role, "value") else str(role)


# ── Admin auth ──────────────────────────────────────────────────────────────────


async def admin_login(session: AsyncSession, req: AdminLoginRequest) -> TokenResponse:
    admin = (
        await session.execute(select(Admin).where(Admin.username == req.username))
    ).scalar_one_or_none()
    if admin is None:
        raise AppException.unauthorized("Invalid credentials")
    if not admin.is_active:
        raise AppException.forbidden("Admin account is disabled")
    if not verify_password(req.password, admin.password_hash):
        raise AppException.unauthorized("Invalid credentials")
    return _issue_admin(admin)


def _issue_admin(admin: Admin) -> TokenResponse:
    from ...domain.enums import admin_role_to_jwt_string

    claims = {"username": admin.username, "role": admin_role_to_jwt_string(admin.role)}
    access, refresh, refresh_exp = security.issue_pair(admin.id, ADMIN_AUDIENCE, claims)
    return TokenResponse(
        id=admin.id, accessToken=access, refreshToken=refresh, refreshTokenExpiresAt=refresh_exp, accountType="admin"
    )


async def admin_create(
    session: AsyncSession, req: AdminCreateRequest, actor_id: str, actor_is_super: bool
) -> AdminResponse:
    from ...domain.enums import admin_role_from_jwt_string

    if not actor_is_super:
        raise AppException.forbidden("Only super admins can create admins")
    role = admin_role_from_jwt_string(req.role)
    if role == AdminRole.SuperAdmin:
        raise AppException.bad_request("Cannot create another super admin")

    exists = (
        await session.execute(select(Admin.id).where(Admin.username == req.username))
    ).first()
    if exists:
        raise AppException.conflict(f"Username '{req.username}' is already taken")

    admin = Admin(
        id=new_uuid_hex(),
        username=req.username,
        password_hash=hash_password(req.password),
        first_name=req.firstName or "",
        last_name=req.lastName or "",
        role=role,
        is_active=True,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return _admin_to_response(admin)


async def admin_list(session: AsyncSession) -> list[AdminResponse]:
    rows = (
        await session.execute(select(Admin).order_by(Admin.created_at))
    ).scalars().all()
    return [_admin_to_response(a) for a in rows]


async def admin_update(session: AsyncSession, id_: str, req: AdminUpdateRequest) -> AdminResponse:
    admin = (
        await session.execute(select(Admin).where(Admin.id == id_))
    ).scalar_one_or_none()
    if admin is None:
        raise AppException.not_found("Admin not found")
    if req.firstName is not None:
        admin.first_name = req.firstName
    if req.lastName is not None:
        admin.last_name = req.lastName
    if req.isActive is not None:
        if req.isActive is False and admin.role == AdminRole.SuperAdmin:
            raise AppException.bad_request("Cannot disable a super admin")
        admin.is_active = req.isActive
    await session.commit()
    await session.refresh(admin)
    return _admin_to_response(admin)


def _admin_to_response(a: Admin) -> AdminResponse:
    return AdminResponse(
        id=a.id,
        username=a.username,
        firstName=a.first_name,
        lastName=a.last_name,
        role=_admin_role_response(a.role),
        isActive=a.is_active,
        createdAt=a.created_at,
    )


# ── User (client) auth ──────────────────────────────────────────────────────────


def _normalize_username(value: str | None) -> str | None:
    """Usernames are stored lowercase (like emails) for case-insensitive lookup."""
    if value is None:
        return None
    v = value.strip().lower()
    return v or None


async def user_register(session: AsyncSession, req: UserRegisterRequest) -> TokenResponse:
    _validate_password(req.password)
    email, phone = _normalize(req.email, req.phoneNumber)
    username = _normalize_username(req.username)
    if username is None and email is None and phone is None:
        raise AppException.bad_request("Username, email, or phone number is required")
    await _ensure_unique(session, username, email, phone)

    user = User(
        id=new_uuid_hex(),
        username=username,
        email=email,
        phone_number=phone,
        password_hash=hash_password(req.password),
        first_name=req.firstName or username,
        last_name=req.lastName,
        email_verified=False,
        phone_number_verified=False,
    )
    session.add(user)
    await session.commit()
    return _issue_user(user)


async def user_login(session: AsyncSession, req: UserLoginRequest) -> TokenResponse:
    # The identifier may be a username or an email; explicit email/phone fields
    # keep older clients working.
    identifier = _normalize_identifier(req.identifier)
    username: str | None = None
    email, phone = _normalize(req.email, req.phoneNumber)
    if identifier is not None:
        if "@" in identifier:
            email = identifier
        else:
            username = identifier

    user: User | None = None
    if username is not None:
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
    if user is None:
        user = await _find_by_identifier(session, email, phone)

    if user is not None:
        if user.status == UserStatus.Suspended:
            raise AppException.forbidden("Account suspended")
        if user.password_hash and verify_password(req.password, user.password_hash):
            return _issue_user(user)

    # Admin-credential fallback: logging in with a staff username + password
    # provisions/updates a linked app user, so admins can use the dashboard too.
    admin_user = await _try_admin_login_link(session, username or email, req.password)
    if admin_user is not None:
        return _issue_user(admin_user)

    raise AppException.unauthorized("Invalid credentials")


async def _try_admin_login_link(
    session: AsyncSession, identifier: str | None, password: str
) -> User | None:
    """If the credentials match an admin account, get-or-create a linked user row
    (username = the admin's username, password kept in sync with the admin's)."""
    if not identifier or "@" in identifier:
        return None
    admin = (
        await session.execute(select(Admin).where(Admin.username == identifier))
    ).scalar_one_or_none()
    if admin is None or not admin.is_active:
        return None
    if not verify_password(password, admin.password_hash):
        return None

    linked_email = f"{admin.username}@admin.local"
    user = (
        await session.execute(select(User).where(User.username == admin.username))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            id=new_uuid_hex(),
            username=admin.username.lower(),
            email=linked_email,
            password_hash=admin.password_hash,  # synced from the admin on each login
            first_name=admin.first_name or admin.username,
            last_name=admin.last_name,
            email_verified=True,
        )
        session.add(user)
    else:
        # Keep the linked user's password in sync with the admin's.
        user.password_hash = admin.password_hash
    await session.commit()
    return user


async def send_otp(session: AsyncSession, req: OtpSendRequest) -> OtpSendResult:
    settings = get_settings()
    identifier = _normalize_identifier(req.identifier)
    if not identifier:
        raise AppException.bad_request("Identifier is required")
    from ...domain.enums import otp_purpose_from_string

    purpose = otp_purpose_from_string(req.purpose)
    now = utcnow()

    # Don't issue a new code while a valid unconsumed one exists.
    existing = (
        await session.execute(
            select(Otp)
            .where(Otp.identifier == identifier, Otp.consumed_at.is_(None), Otp.expires_at > now)
            .order_by(Otp.expires_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return OtpSendResult(identifier=identifier, alreadyPending=True, expiresAt=existing.expires_at)

    code = secrets.randbelow(10 ** settings.otp_code_length)
    code = str(code).zfill(settings.otp_code_length)

    otp = Otp(
        id=new_uuid_hex(),
        identifier=identifier,
        code_hash=hash_code(code),
        purpose=purpose,
        attempts=0,
        expires_at=now + timedelta(minutes=settings.otp_ttl_minutes),
    )
    session.add(otp)
    await session.commit()

    log.info("[OTP] %s code=%s (purpose=%s)", identifier, code, purpose.value)
    return OtpSendResult(identifier=identifier, alreadyPending=False, expiresAt=otp.expires_at)


async def verify_otp(session: AsyncSession, req: OtpVerifyRequest) -> TokenResponse:
    settings = get_settings()
    identifier = _normalize_identifier(req.identifier)
    if not identifier:
        raise AppException.bad_request("Identifier is required")
    from ...domain.enums import otp_purpose_from_string

    # Parse for validation side-effects (parity with the .NET VerifyOtpAsync).
    otp_purpose_from_string(req.purpose)

    otp = (
        await session.execute(
            select(Otp)
            .where(Otp.identifier == identifier, Otp.consumed_at.is_(None))
            .order_by(Otp.expires_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if otp is None or otp.expires_at <= utcnow():
        raise AppException.unauthorized("OTP expired or not found")

    if otp.attempts >= settings.otp_max_attempts:
        otp.consumed_at = utcnow()
        await session.commit()
        raise AppException.forbidden("Too many attempts; request a new code")

    if not fixed_equals(hash_code(req.code), otp.code_hash):
        otp.attempts += 1
        await session.commit()
        raise AppException.unauthorized("Invalid code")

    otp.consumed_at = utcnow()

    is_email = "@" in identifier
    user = await _find_by_identifier(session, identifier if is_email else None, None if is_email else identifier)

    if user is None:
        user = User(
            id=new_uuid_hex(),
            email=identifier if is_email else None,
            phone_number=None if is_email else identifier,
            first_name=req.firstName,
            last_name=req.lastName,
            email_verified=is_email,
            phone_number_verified=not is_email,
        )
        session.add(user)
    else:
        if user.status == UserStatus.Suspended:
            raise AppException.forbidden("Account suspended")
        if is_email:
            user.email_verified = True
        else:
            user.phone_number_verified = True

    await session.commit()
    return _issue_user(user)


async def user_me(session: AsyncSession, user_id: str) -> UserResponse:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise AppException.not_found("User not found")
    return _user_to_response(user)


async def update_profile(session: AsyncSession, user_id: str, req: UpdateUserRequest) -> UserResponse:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise AppException.not_found("User not found")
    if req.firstName is not None:
        user.first_name = req.firstName
    if req.lastName is not None:
        user.last_name = req.lastName
    if req.preferredLanguage and req.preferredLanguage.strip() in ("fa", "en"):
        user.preferred_language = req.preferredLanguage
    await session.commit()
    await session.refresh(user)
    return _user_to_response(user)


def _issue_user(user: User) -> TokenResponse:
    claims = {
        "username": user.username or "",
        "email": user.email or "",
        "phone": user.phone_number or "",
    }
    access, refresh, refresh_exp = security.issue_pair(user.id, USER_AUDIENCE, claims)
    return TokenResponse(
        id=user.id, accessToken=access, refreshToken=refresh, refreshTokenExpiresAt=refresh_exp, accountType="user"
    )


async def _ensure_unique(
    session: AsyncSession, username: str | None, email: str | None, phone: str | None
) -> None:
    if username is not None:
        if (await session.execute(select(User.id).where(User.username == username))).first():
            raise AppException.conflict("Username is already taken")
    if email is not None:
        if (await session.execute(select(User.id).where(User.email == email))).first():
            raise AppException.conflict("Email already registered")
    if phone is not None:
        if (await session.execute(select(User.id).where(User.phone_number == phone))).first():
            raise AppException.conflict("Phone number already registered")


async def _find_by_identifier(session: AsyncSession, email: str | None, phone: str | None) -> User | None:
    if email:
        return (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if phone:
        return (await session.execute(select(User).where(User.phone_number == phone))).scalar_one_or_none()
    return None


def _validate_password(password: str) -> None:
    settings = get_settings()
    if not password or len(password) < settings.password_min_length:
        raise AppException.validation(f"Password must be at least {settings.password_min_length} characters")


def _user_to_response(u: User) -> UserResponse:
    return UserResponse(
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
    )
