"""Admin user-management DTOs (camelCase wire shapes)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminUserResponse(BaseModel):
    id: str
    username: str | None = None
    email: str | None = None
    phoneNumber: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    status: str
    emailVerified: bool = False
    phoneVerified: bool = False
    preferredLanguage: str = "fa"
    createdAt: datetime | None = None


class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    firstName: str | None = None
    lastName: str | None = None
    # "Active" | "Suspended" (case-insensitive, snake-tolerant)
    status: str | None = None
    # Optional password reset (min length enforced like registration).
    password: str | None = None
