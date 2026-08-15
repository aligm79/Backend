"""Auth Pydantic DTOs (wire shapes match AuthDtos.cs, camelCase)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TokenResponse(BaseModel):
    id: str
    accessToken: str
    refreshToken: str
    refreshTokenExpiresAt: datetime
    accountType: str  # "user" | "admin"


# ── Admin ───────────────────────────────────────────────────────────────────────


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminCreateRequest(BaseModel):
    username: str
    password: str
    firstName: str | None = None
    lastName: str | None = None
    role: str = "admin"


class AdminUpdateRequest(BaseModel):
    firstName: str | None = None
    lastName: str | None = None
    isActive: bool | None = None


class AdminResponse(BaseModel):
    id: str
    username: str
    firstName: str
    lastName: str
    role: str
    isActive: bool
    createdAt: datetime | None = None


# ── User (client) ───────────────────────────────────────────────────────────────


class UserRegisterRequest(BaseModel):
    email: str | None = None
    phoneNumber: str | None = None
    password: str
    firstName: str | None = None
    lastName: str | None = None


class UserLoginRequest(BaseModel):
    email: str | None = None
    phoneNumber: str | None = None
    password: str


class OtpSendRequest(BaseModel):
    identifier: str
    purpose: str = "register"


class OtpVerifyRequest(BaseModel):
    identifier: str
    code: str
    purpose: str = "register"
    firstName: str | None = None
    lastName: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str | None = None
    phoneNumber: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    status: str
    emailVerified: bool
    phoneVerified: bool
    preferredLanguage: str
    createdAt: datetime | None = None


class UpdateUserRequest(BaseModel):
    firstName: str | None = None
    lastName: str | None = None
    preferredLanguage: str | None = None


class OtpSendResult(BaseModel):
    identifier: str
    alreadyPending: bool
    expiresAt: datetime
