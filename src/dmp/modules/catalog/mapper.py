"""Maps the source `{ "university": { … } }` JSON (sample-data/*.json) onto typed payloads.

Direct port of UniversityJsonMapper.cs. Defensive: missing keys yield None/empty rather
than raising. The intermediate payload is consumed by CatalogService.import_json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ...domain.enums import AdmissionLevel, ProgramLevel


@dataclass
class AdmissionPayload:
    level: AdmissionLevel
    toefl: str | None = None
    ielts: str | None = None
    cambridge_cae: str | None = None
    pte: str | None = None
    ib: str | None = None
    sat: str | None = None
    gre: str | None = None
    gmat: str | None = None
    gpa: str | None = None


@dataclass
class StudentStaffBucket:
    key: str
    json: dict


@dataclass
class RankingPayload:
    qs_world: str | None = None
    qs_subject: str | None = None
    qs_sustainability: str | None = None
    europe_rank: str | None = None
    criteria: dict | None = None
    yearly_data: dict | None = None


@dataclass
class ProgramPayload:
    level: ProgramLevel
    name: str


@dataclass
class UniversityPayload:
    name: str = ""
    about: str = ""
    qs_world_rank: str | None = None
    international_students_pct: str | None = None
    campus_location: str | None = None
    facilities: str | None = None
    scholarships: str | None = None
    career_services: str | None = None
    student_life: str | None = None
    costs_of_living: dict | None = None
    overall_tuition: dict | None = None
    admissions: list[AdmissionPayload] = field(default_factory=list)
    student_staff_buckets: list[StudentStaffBucket] = field(default_factory=list)
    ranking: RankingPayload | None = None
    programs: list[ProgramPayload] = field(default_factory=list)


def _str(parent: Any, key: str) -> str | None:
    """Return parent[key] if it's a string, else None."""
    if isinstance(parent, dict):
        v = parent.get(key)
        if isinstance(v, str):
            return v
    return None


def _non_empty(s: str | None) -> str:
    if s is None or not s.strip():
        return ""
    return s.strip()


def _as_dict(element: Any) -> dict | None:
    """Deep-copy a JSON element into a plain dict (None if undefined/null)."""
    if element is None:
        return None
    if isinstance(element, (dict, list)):
        # Already parsed (we parse via json.loads into Python objects).
        return element  # type: ignore[return-value]
    return None


def parse(json_text: str) -> list[UniversityPayload]:
    """Parse one or many universities from the given JSON text."""
    root = json.loads(json_text)
    if isinstance(root, list):
        return [_parse_one(el) for el in root]
    return [_parse_one(root)]


def _parse_one(element: Any) -> UniversityPayload:
    # The wrapper is optional: { "university": {...} } OR a bare {...}.
    if isinstance(element, dict) and isinstance(element.get("university"), dict):
        u = element["university"]
    else:
        u = element if isinstance(element, dict) else {}

    name = _non_empty(_str(u, "name"))
    about = _non_empty(_str(u, "about_university"))
    qs = _str(u, "QS World University Rankings")
    intl_pct = _str(u, "International students percentage")
    campus = _str(u, "Campus location")

    info = u.get("University Information") or {}
    facilities = _str(info, "FACILITIES") if isinstance(info, dict) else None
    student_staff = info.get("STUDENT & STAFF") if isinstance(info, dict) else None
    student_life = _str(student_staff, "student life") if isinstance(student_staff, dict) else None

    admissions = info.get("admission") if isinstance(info, dict) else None
    costs = u.get("costs of living")
    tuition = u.get("tuition fees")
    scholarships = _str(u, "scholarships")
    employability = u.get("Employability")
    career_services = (
        _str(employability, "career services") if isinstance(employability, dict) else None
    )
    rankings = u.get("Rankings & ratings")

    return UniversityPayload(
        name=name,
        about=about,
        qs_world_rank=qs,
        international_students_pct=intl_pct,
        campus_location=campus,
        facilities=facilities,
        scholarships=scholarships,
        career_services=career_services,
        student_life=student_life,
        costs_of_living=_as_dict(costs),
        overall_tuition=_as_dict(tuition),
        admissions=_parse_admissions(admissions),
        student_staff_buckets=_parse_student_staff(student_staff),
        ranking=_parse_ranking(rankings),
        programs=_parse_programs(u.get("Available programmes")),
    )


def _parse_admissions(admissions: Any) -> list[AdmissionPayload]:
    out: list[AdmissionPayload] = []
    if not isinstance(admissions, dict):
        return out
    level_map = {
        "general": AdmissionLevel.General,
        "bachelor": AdmissionLevel.Bachelor,
        "master": AdmissionLevel.Master,
        "mba": AdmissionLevel.Mba,
        "phd": AdmissionLevel.Phd,
    }
    for key, value in admissions.items():
        level = level_map.get(key.lower())
        if level is None or not isinstance(value, dict):
            continue
        out.append(
            AdmissionPayload(
                level=level,
                toefl=_str(value, "TOEFL"),
                ielts=_str(value, "IELTS"),
                cambridge_cae=_str(value, "CAMBRIDGE CAE ADVANCED"),
                pte=_str(value, "PTE ACADEMIC"),
                ib=_str(value, "INTERNATIONAL BACCALAUREATE"),
                sat=_str(value, "SAT"),
                gre=_str(value, "GRE"),
                gmat=_str(value, "GMAT"),
                gpa=_str(value, "GPA"),
            )
        )
    return out


def _parse_student_staff(ss: Any) -> list[StudentStaffBucket]:
    out: list[StudentStaffBucket] = []
    if not isinstance(ss, dict):
        return out
    for key, value in ss.items():
        if isinstance(value, dict):
            out.append(StudentStaffBucket(key=key, json=value))
    return out


def _parse_ranking(rank: Any) -> RankingPayload | None:
    if not isinstance(rank, dict):
        return None
    return RankingPayload(
        qs_world=_str(rank, "QS world university rankings"),
        qs_subject=_str(rank, "QS WUR ranking by subject"),
        qs_sustainability=_str(rank, "QS sustainability ranking"),
        europe_rank=_str(rank, "Europe University rankings - Northers Europe"),
        criteria=_as_dict(rank.get("Ranking crieteria")),
        yearly_data=_as_dict(rank.get("data")),
    )


def _parse_programs(ap: Any) -> list[ProgramPayload]:
    out: list[ProgramPayload] = []
    if not isinstance(ap, dict):
        return out
    level_map = {
        "bachelor": ProgramLevel.Bachelor,
        "master": ProgramLevel.Master,
        "mba": ProgramLevel.Mba,
        "phd": ProgramLevel.Phd,
    }
    for key, value in ap.items():
        level = level_map.get(key.lower())
        if level is None or not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = str(item.get("name") or "")
            else:
                name = ""
            if name.strip():
                out.append(ProgramPayload(level=level, name=name.strip()))
    return out
