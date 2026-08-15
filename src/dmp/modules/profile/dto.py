"""Profile + settings Pydantic DTOs (camelCase wire shapes)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ProfileResponse(BaseModel):
    id: str
    email: Optional[str] = None
    phoneNumber: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    preferredLanguage: str = "fa"
    bio: Optional[str] = None
    gpa: Optional[str] = None
    education: Optional[list[dict]] = None
    testScores: Optional[dict] = None
    researchInterests: Optional[list[str]] = None
    preferredCountries: Optional[list[str]] = None
    avatarUrl: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phoneNumber: Optional[str] = None
    bio: Optional[str] = None
    gpa: Optional[str] = None
    education: Optional[list[dict]] = None
    testScores: Optional[dict] = None
    researchInterests: Optional[list[str]] = None
    preferredCountries: Optional[list[str]] = None
    avatarUrl: Optional[str] = None
    preferredLanguage: Optional[str] = None


class SettingsResponse(BaseModel):
    notificationEmailEnabled: bool = True
    notificationPushEnabled: bool = True
    notificationDeadlineReminders: bool = True
    notificationEmailTracker: bool = True
    aiEnabled: bool = True
    aiModel: str = "default"
    aiTemperature: float = 0.7
    theme: str = "dark"
    integrations: Optional[dict] = None


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    notificationEmailEnabled: Optional[bool] = None
    notificationPushEnabled: Optional[bool] = None
    notificationDeadlineReminders: Optional[bool] = None
    notificationEmailTracker: Optional[bool] = None
    aiEnabled: Optional[bool] = None
    aiModel: Optional[str] = None
    aiTemperature: Optional[float] = None
    theme: Optional[str] = None
    integrations: Optional[dict] = None
