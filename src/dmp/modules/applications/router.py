"""Applications API routers (client + admin). New study-abroad application feature."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...deps import current_admin, current_user_id
from ...domain.models import Admin
from ...envelope import ok
from .dto import (
    ApplicationCreateRequest,
    ApplicationStatusUpdateRequest,
    ApplicationUpdateRequest,
)
from .service import ApplicationService

router_client = APIRouter(prefix="/api/v1/client/applications", tags=["applications (client)"])
router_admin = APIRouter(prefix="/api/v1/admin/applications", tags=["applications (admin)"])

_service = ApplicationService()


# ── Client ──────────────────────────────────────────────────────────────────────


@router_client.get("")
async def list_mine(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.list_mine(session, user_id))


@router_client.post("")
async def create(
    req: ApplicationCreateRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.create(session, user_id, req))


@router_client.get("/{id}")
async def get(
    id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.get(session, id, user_id))


@router_client.put("/{id}")
async def update(
    id: str,
    req: ApplicationUpdateRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.update(session, id, user_id, req))


@router_client.delete("/{id}")
async def delete(
    id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    await _service.delete(session, id, user_id)
    return ok()


@router_client.post("/{id}/documents")
async def add_document(
    id: str,
    kind: str = Form("other"),
    file: UploadFile = File(...),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.add_document(session, id, user_id, kind, file))


@router_client.delete("/{id}/documents/{doc_id}")
async def delete_document(
    id: str,
    doc_id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    await _service.delete_document(session, id, doc_id, user_id)
    return ok()


# ── Admin ───────────────────────────────────────────────────────────────────────


@router_admin.get("")
async def admin_list(
    status: str | None = None,
    universityId: str | None = None,
    userId: str | None = None,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.admin_list(session, status, universityId, userId))


@router_admin.get("/{id}")
async def admin_get(
    id: str,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.admin_get(session, id))


@router_admin.patch("/{id}/status")
async def admin_update_status(
    id: str,
    req: ApplicationStatusUpdateRequest,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _service.admin_update_status(session, id, req))
