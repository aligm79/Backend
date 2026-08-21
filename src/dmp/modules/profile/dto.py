"""Profile + settings Pydantic DTOs (camelCase wire shapes)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProfileResponse(BaseModel):
    id: str
    email: str | None = None
    phoneNumber: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    preferredLanguage: str = "fa"
    bio: str | None = None
    gpa: str | None = None
    education: list[dict] | None = None
    testScores: dict | None = None
    researchInterests: list[str] | None = None
    preferredCountries: list[str] | None = None
    avatarUrl: str | None = None


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    firstName: str | None = None
    lastName: str | None = None
    phoneNumber: str | None = None
    bio: str | None = None
    gpa: str | None = None
    education: list[dict] | None = None
    testScores: dict | None = None
    researchInterests: list[str] | None = None
    preferredCountries: list[str] | None = None
    avatarUrl: str | None = None
    preferredLanguage: str | None = None


class SettingsResponse(BaseModel):
    notificationEmailEnabled: bool = True
    notificationPushEnabled: bool = True
    notificationDeadlineReminders: bool = True
    notificationEmailTracker: bool = True
    aiEnabled: bool = True
    aiModel: str = "default"
    aiTemperature: float = 0.7
    theme: str = "dark"
    integrations: dict | None = None


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    notificationEmailEnabled: bool | None = None
    notificationPushEnabled: bool | None = None
    notificationDeadlineReminders: bool | None = None
    notificationEmailTracker: bool | None = None
    aiEnabled: bool | None = None
    aiModel: str | None = None
    aiTemperature: float | None = None
    theme: str | None = None
    integrations: dict | None = None
