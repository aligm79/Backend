"""Catalog Pydantic DTOs (wire shapes match the .NET CatalogDtos records, camelCase)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _parse_jsonb(v: Any) -> dict | None:
    """Accept dict, JSON string, or None → dict | None."""
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return None


class CountryResponse(BaseModel):
    id: str
    code: str
    name: str
    flagEmoji: str | None = None


class ProgramDto(BaseModel):
    level: str
    name: str


class AdmissionDto(BaseModel):
    level: str
    toefl: str | None = None
    ielts: str | None = None
    cambridgeCae: str | None = None
    pte: str | None = None
    ib: str | None = None
    sat: str | None = None
    gre: str | None = None
    gmat: str | None = None
    gpa: str | None = None


class StudentStaffDto(BaseModel):
    totalStudents: dict | None = None
    internationalStudents: dict | None = None
    totalFaculty: dict | None = None
    studentLife: str | None = None


class RankingDto(BaseModel):
    qsWorld: str | None = None
    qsSubject: str | None = None
    qsSustainability: str | None = None
    europeRank: str | None = None
    criteria: dict | None = None
    yearlyData: dict | None = None


class UniversityCard(BaseModel):
    id: str
    slug: str
    name: str
    logoUrl: str | None = None
    coverImageUrl: str | None = None
    qsWorldRank: str | None = None
    campusLocation: str | None = None
    aboutTeaser: str = ""
    sortOrder: int = 0
    countryName: str | None = None
    countryFlag: str | None = None


class UniversityDetail(BaseModel):
    id: str
    slug: str
    name: str
    logoUrl: str | None = None
    coverImageUrl: str | None = None
    qsWorldRank: str | None = None
    campusLocation: str | None = None
    about: str = ""
    internationalStudentsPct: str | None = None
    facilities: str | None = None
    scholarships: str | None = None
    careerServices: str | None = None
    costsOfLiving: dict | None = None
    tuitionFees: dict | None = None
    programs: list[ProgramDto] = Field(default_factory=list)
    admissions: list[AdmissionDto] = Field(default_factory=list)
    studentStaff: StudentStaffDto | None = None
    ranking: RankingDto | None = None
    countryId: str | None = None
    countryName: str | None = None
    countryFlag: str | None = None
    isPublished: bool = True
    sortOrder: int = 0


class UniversityUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    slug: str | None = None
    logoUrl: str | None = None
    coverImageUrl: str | None = None
    qsWorldRank: str | None = None
    campusLocation: str | None = None
    about: str = ""
    internationalStudentsPct: str | None = None
    facilities: str | None = None
    scholarships: str | None = None
    careerServices: str | None = None
    costsOfLiving: Any | None = None
    tuitionFees: Any | None = None
    isPublished: bool = True
    sortOrder: int = 0
    countryId: str | None = None

    def parsed_costs(self) -> dict | None:
        return _parse_jsonb(self.costsOfLiving)

    def parsed_tuition(self) -> dict | None:
        return _parse_jsonb(self.tuitionFees)


class ImportResult(BaseModel):
    universityId: str
    slug: str
    name: str
    created: bool
    warnings: list[str] = Field(default_factory=list)
