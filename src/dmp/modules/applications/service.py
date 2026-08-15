"""Study-abroad application management service (new feature).

Students create/manage applications (draft → submitted → under_review → accepted/
rejected/withdrawn) and upload supporting documents. Admins list/filter, view, and
update status + private reviewer notes. Documents are stored on disk under UPLOADS_DIR.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...config import get_settings
from ...domain.enums import ApplicationDocumentKind, ApplicationStatus, ProgramLevel
from ...domain.models import Application, ApplicationDocument, University
from ...envelope import AppException
from ...security import new_uuid_hex
from .dto import (
    ApplicationCreateRequest,
    ApplicationDocumentResponse,
    ApplicationResponse,
    ApplicationStatusUpdateRequest,
    ApplicationUpdateRequest,
)


def _parse_program_level(value: str | None):
    if not value:
        return None
    v = value.lower()
    for p in ProgramLevel:
        if p.value.lower() == v:
            return p
    return None


def _status_from_string(value: str) -> ApplicationStatus:
    """Map a wire status string (snake_case or PascalCase) to the enum."""
    v = value.lower().replace("_", "")
    for s in ApplicationStatus:
        if s.value.lower() == v:
            return s
    raise AppException.validation(f"Invalid status: {value}")


def _parse_status(value: str | None, allowed: list[ApplicationStatus]) -> ApplicationStatus:
    if not value:
        raise AppException.validation("status is required")
    s = _status_from_string(value)
    if allowed and s not in allowed:
        raise AppException.validation(f"Invalid status: {value}")
    return s


def _to_response(app: Application, include_admin_notes: bool = False) -> dict:
    docs = [
        ApplicationDocumentResponse(
            id=d.id,
            applicationId=d.application_id,
            kind=d.kind.value if hasattr(d.kind, "value") else str(d.kind),
            filename=d.filename,
            mime=d.mime,
            size=d.size,
            createdAt=d.created_at.isoformat() if d.created_at else None,
        ).model_dump(exclude_none=True)
        for d in app.documents
    ]
    return ApplicationResponse(
        id=app.id,
        userId=app.user_id,
        universityId=app.university_id,
        universityName=app.university.name if app.university else None,
        programLevel=app.program_level.value if app.program_level and hasattr(app.program_level, "value") else (
            app.program_level if app.program_level is None else str(app.program_level)
        ),
        status=app.status.value if hasattr(app.status, "value") else str(app.status),
        preferredIntake=app.preferred_intake,
        notes=app.notes,
        adminNotes=app.admin_notes if include_admin_notes else None,
        documents=docs,
        createdAt=app.created_at.isoformat() if app.created_at else None,
        updatedAt=app.updated_at.isoformat() if app.updated_at else None,
    ).model_dump(exclude_none=True)


class ApplicationService:
    # ── Client ──────────────────────────────────────────────────────────────────

    async def list_mine(self, session: AsyncSession, user_id: str) -> list[dict]:
        stmt = (
            select(Application)
            .options(selectinload(Application.documents), selectinload(Application.university))
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_response(a) for a in rows]

    async def create(self, session: AsyncSession, user_id: str, req: ApplicationCreateRequest) -> dict:
        if req.universityId:
            exists = (
                await session.execute(select(University.id).where(University.id == req.universityId))
            ).first()
            if not exists:
                raise AppException.not_found("University not found")
        app = Application(
            id=new_uuid_hex(),
            user_id=user_id,
            university_id=req.universityId,
            program_level=_parse_program_level(req.programLevel),
            preferred_intake=req.preferredIntake,
            notes=req.notes,
            status=ApplicationStatus.Draft,
        )
        session.add(app)
        await session.commit()
        # Reload with relationships for a full response.
        loaded = await self._load(session, app.id, user_id=user_id)
        return _to_response(loaded)

    async def get(self, session: AsyncSession, app_id: str, user_id: str) -> dict:
        app = await self._load(session, app_id, user_id=user_id)
        return _to_response(app)

    async def update(
        self, session: AsyncSession, app_id: str, user_id: str, req: ApplicationUpdateRequest
    ) -> dict:
        app = await self._load(session, app_id, user_id=user_id)
        # Client may only mutate these while in a pre-review state.
        if app.status not in (ApplicationStatus.Draft, ApplicationStatus.Submitted):
            raise AppException.conflict("Application can no longer be edited")
        if req.universityId is not None:
            if req.universityId:
                exists = (
                    await session.execute(select(University.id).where(University.id == req.universityId))
                ).first()
                if not exists:
                    raise AppException.not_found("University not found")
            app.university_id = req.universityId
        if req.programLevel is not None:
            app.program_level = _parse_program_level(req.programLevel)
        if req.preferredIntake is not None:
            app.preferred_intake = req.preferredIntake
        if req.notes is not None:
            app.notes = req.notes
        if req.status is not None:
            new_status = _parse_status(
                req.status, [ApplicationStatus.Submitted, ApplicationStatus.Withdrawn, ApplicationStatus.Draft]
            )
            app.status = new_status
        await session.commit()
        loaded = await self._load(session, app.id, user_id=user_id)
        return _to_response(loaded)

    async def delete(self, session: AsyncSession, app_id: str, user_id: str) -> None:
        app = await self._load(session, app_id, user_id=user_id)
        await session.delete(app)
        await session.commit()

    async def add_document(
        self,
        session: AsyncSession,
        app_id: str,
        user_id: str,
        kind: str,
        upload: UploadFile,
    ) -> dict:
        app = await self._load(session, app_id, user_id=user_id)
        # Resolve kind enum.
        kind_enum: ApplicationDocumentKind
        try:
            kind_enum = ApplicationDocumentKind(kind.capitalize()) if kind else ApplicationDocumentKind.Other
        except ValueError:
            kind_enum = ApplicationDocumentKind.Other

        settings = get_settings()
        uploads_root = Path(settings.uploads_dir) / app.id
        uploads_root.mkdir(parents=True, exist_ok=True)
        # Random filename to avoid collisions/path traversal; keep original name in DB.
        ext = Path(upload.filename or "").suffix[:16]
        stored_name = secrets.token_urlsafe(16) + ext
        storage_path = uploads_root / stored_name
        data = await upload.read()
        storage_path.write_bytes(data)

        doc = ApplicationDocument(
            id=new_uuid_hex(),
            application_id=app.id,
            kind=kind_enum,
            filename=upload.filename or stored_name,
            storage_path=str(storage_path),
            mime=upload.content_type or "application/octet-stream",
            size=len(data),
        )
        session.add(doc)
        await session.commit()
        loaded = await self._load(session, app.id, user_id=user_id)
        return _to_response(loaded)

    async def delete_document(
        self, session: AsyncSession, app_id: str, doc_id: str, user_id: str
    ) -> None:
        app = await self._load(session, app_id, user_id=user_id)
        doc = next((d for d in app.documents if d.id == doc_id), None)
        if doc is None:
            raise AppException.not_found("Document not found")
        try:
            p = Path(doc.storage_path)
            if p.is_file():
                p.unlink()
        except OSError:
            pass
        await session.delete(doc)
        await session.commit()

    # ── Admin ───────────────────────────────────────────────────────────────────

    async def admin_list(
        self,
        session: AsyncSession,
        status: str | None = None,
        university_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        stmt = (
            select(Application)
            .options(selectinload(Application.documents), selectinload(Application.university))
        )
        if status:
            status_enum = _status_from_string(status)
            stmt = stmt.where(Application.status == status_enum)
        if university_id:
            stmt = stmt.where(Application.university_id == university_id)
        if user_id:
            stmt = stmt.where(Application.user_id == user_id)
        stmt = stmt.order_by(Application.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_response(a, include_admin_notes=True) for a in rows]

    async def admin_get(self, session: AsyncSession, app_id: str) -> dict:
        app = await self._load(session, app_id, user_id=None)
        return _to_response(app, include_admin_notes=True)

    async def admin_update_status(
        self, session: AsyncSession, app_id: str, req: ApplicationStatusUpdateRequest
    ) -> dict:
        app = await self._load(session, app_id, user_id=None)
        new_status = _parse_status(req.status, list(ApplicationStatus))
        app.status = new_status
        if req.adminNotes is not None:
            app.admin_notes = req.adminNotes
        await session.commit()
        loaded = await self._load(session, app.id, user_id=None)
        return _to_response(loaded, include_admin_notes=True)

    # ── helpers ─────────────────────────────────────────────────────────────────

    async def _load(
        self, session: AsyncSession, app_id: str, user_id: str | None
    ) -> Application:
        # Expire any cached instance so relationship state (documents added/removed
        # in this same session) is re-fetched fresh.
        session.expire_all()
        stmt = (
            select(Application)
            .options(selectinload(Application.documents), selectinload(Application.university))
            .where(Application.id == app_id)
        )
        if user_id is not None:
            stmt = stmt.where(Application.user_id == user_id)
        app = (await session.execute(stmt)).scalar_one_or_none()
        if app is None:
            raise AppException.not_found("Application not found")
        return app
