"""Profile + settings service.

Profile extends the `users` table; settings lives in a one-to-one `user_settings`
row that is lazily created on first read (upsert-on-get).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.models import User, UserSettings
from ...envelope import AppException
from ...security import new_uuid_hex
from .dto import ProfileResponse, SettingsResponse, UpdateProfileRequest, UpdateSettingsRequest


def _profile_response(u: User) -> ProfileResponse:
    return ProfileResponse(
        id=u.id,
        email=u.email,
        phoneNumber=u.phone_number,
        firstName=u.first_name,
        lastName=u.last_name,
        preferredLanguage=u.preferred_language,
        bio=u.bio,
        gpa=u.gpa,
        education=u.education,
        testScores=u.test_scores,
        researchInterests=u.research_interests,
        preferredCountries=u.preferred_countries,
        avatarUrl=u.avatar_url,
    )


def _settings_response(s: UserSettings) -> SettingsResponse:
    return SettingsResponse(
        notificationEmailEnabled=s.notification_email_enabled,
        notificationPushEnabled=s.notification_push_enabled,
        notificationDeadlineReminders=s.notification_deadline_reminders,
        notificationEmailTracker=s.notification_email_tracker,
        aiEnabled=s.ai_enabled,
        aiModel=s.ai_model,
        aiTemperature=float(s.ai_temperature) if s.ai_temperature is not None else 0.7,
        theme=s.theme,
        integrations=s.integrations,
    )


async def get_profile(session: AsyncSession, user_id: str) -> ProfileResponse:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise AppException.not_found("User not found")
    return _profile_response(user)


async def update_profile(
    session: AsyncSession, user_id: str, req: UpdateProfileRequest
) -> ProfileResponse:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise AppException.not_found("User not found")
    if req.firstName is not None:
        user.first_name = req.firstName
    if req.lastName is not None:
        user.last_name = req.lastName
    if req.phoneNumber is not None:
        user.phone_number = req.phoneNumber
    if req.bio is not None:
        user.bio = req.bio
    if req.gpa is not None:
        user.gpa = req.gpa
    if req.education is not None:
        user.education = req.education
    if req.testScores is not None:
        user.test_scores = req.testScores
    if req.researchInterests is not None:
        user.research_interests = req.researchInterests
    if req.preferredCountries is not None:
        user.preferred_countries = req.preferredCountries
    if req.avatarUrl is not None:
        user.avatar_url = req.avatarUrl
    if req.preferredLanguage is not None and req.preferredLanguage in ("fa", "en"):
        user.preferred_language = req.preferredLanguage
    await session.commit()
    await session.refresh(user)
    return _profile_response(user)


async def get_settings(session: AsyncSession, user_id: str) -> SettingsResponse:
    s = (
        await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if s is None:
        # Lazily create defaults on first read.
        s = UserSettings(id=new_uuid_hex(), user_id=user_id)
        session.add(s)
        await session.commit()
        await session.refresh(s)
    return _settings_response(s)


async def update_settings(
    session: AsyncSession, user_id: str, req: UpdateSettingsRequest
) -> SettingsResponse:
    s = (
        await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if s is None:
        s = UserSettings(id=new_uuid_hex(), user_id=user_id)
        session.add(s)
    if req.notificationEmailEnabled is not None:
        s.notification_email_enabled = req.notificationEmailEnabled
    if req.notificationPushEnabled is not None:
        s.notification_push_enabled = req.notificationPushEnabled
    if req.notificationDeadlineReminders is not None:
        s.notification_deadline_reminders = req.notificationDeadlineReminders
    if req.notificationEmailTracker is not None:
        s.notification_email_tracker = req.notificationEmailTracker
    if req.aiEnabled is not None:
        s.ai_enabled = req.aiEnabled
    if req.aiModel is not None:
        s.ai_model = req.aiModel
    if req.aiTemperature is not None:
        s.ai_temperature = req.aiTemperature
    if req.theme is not None and req.theme in ("light", "dark", "system"):
        s.theme = req.theme
    if req.integrations is not None:
        s.integrations = req.integrations
    await session.commit()
    await session.refresh(s)
    return _settings_response(s)
