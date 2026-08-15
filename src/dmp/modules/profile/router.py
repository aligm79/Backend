"""Profile + settings API routers (client)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...deps import current_user_id
from ...envelope import ok
from . import service
from .dto import UpdateProfileRequest, UpdateSettingsRequest

router = APIRouter(prefix="/api/v1/client", tags=["profile & settings"])


@router.get("/profile")
async def get_profile(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    res = await service.get_profile(session, user_id)
    return ok(res.model_dump(exclude_none=True))


@router.put("/profile")
async def update_profile(
    req: UpdateProfileRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    res = await service.update_profile(session, user_id, req)
    return ok(res.model_dump(exclude_none=True))


@router.get("/settings")
async def get_settings(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    res = await service.get_settings(session, user_id)
    return ok(res.model_dump(exclude_none=True))


@router.patch("/settings")
async def update_settings(
    req: UpdateSettingsRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    res = await service.update_settings(session, user_id, req)
    return ok(res.model_dump(exclude_none=True))
