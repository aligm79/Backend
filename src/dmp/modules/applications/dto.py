"""Study-abroad application DTOs (new feature). camelCase wire shapes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApplicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    universityId: str | None = None
    programLevel: str | None = None  # Bachelor/Master/Mba/Phd
    preferredIntake: str | None = None
    notes: str | None = None


class ApplicationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    universityId: str | None = None
    programLevel: str | None = None
    preferredIntake: str | None = None
    notes: str | None = None
    status: str | None = None  # client may submit/withdraw


class ApplicationStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    adminNotes: str | None = None


class ApplicationDocumentResponse(BaseModel):
    id: str
    applicationId: str
    kind: str
    filename: str
    mime: str
    size: int
    createdAt: str | None = None


class ApplicationResponse(BaseModel):
    id: str
    userId: str
    universityId: str | None = None
    universityName: str | None = None
    programLevel: str | None = None
    status: str
    preferredIntake: str | None = None
    notes: str | None = None
    adminNotes: str | None = None
    documents: list[ApplicationDocumentResponse] = []
    createdAt: str | None = None
    updatedAt: str | None = None
