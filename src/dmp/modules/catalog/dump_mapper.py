"""Maps rows from the `university_data` landing table (restored dumps) onto the
canonical catalog payload.

The dump payload is semi-structured and version-dependent — this mapper is the
SINGLE integration point between the dump schema and the app. Every access is
defensive: missing sections, missing sources, or empty strings degrade to None
rather than raising, so a future dump with extra/renamed fields only requires
updating this file (the raw rows stay untouched in `university_data`).

Observed payload shape (v1, 2026-08):

    university_identity:    { name, country{src}, website{src}, location{src}, founded{src} }
    university_overview:    { about_university{qs}, introduction{shanghai}, summary{us_news},
                              campus_location{qs} }
    rankings:               { global: { qs: { current_rank, ranking_criteria{...},
                              rankings_ratings{qs_sustainability_ranking, qs_wur_ranking_by_subject,
                              qs_world_university_rankings, ...} } } }
    admissions:             { qs: { bachelor|master|mba|phd|general: {GPA, GRE, SAT, GMAT,
                              IELTS, TOEFL, PTE_ACADEMIC, CAMBRIDGE_CAE_ADVANCED,
                              INTERNATIONAL_BACCALAUREATE} } }
    programmes:             { qs: { available_programmes: { level: [ {faculty_name,
                              departments: [{department_name, programs:
                              [{program_name, ...}]}]} ] } } }
    facilities:             { qs: { facilities } }
    employability:          { qs: { career_services } }
    costs_and_finances:     { qs: { scholarships, tuition_fees: {domestic_starts_from,
                              international_starts_from} } }
    university_statistics:  { qs: { student_and_staff: { student_life, total_student{...},
                              international_students{...}, total_faculty_staff{...} } } }
"""

from __future__ import annotations

import re
from typing import Any

from ...domain.enums import AdmissionLevel, ProgramLevel
from .mapper import (
    AdmissionPayload,
    ProgramPayload,
    RankingPayload,
    StudentStaffBucket,
    UniversityPayload,
)

MAX_PROGRAMS_PER_LEVEL = 100

_ADMISSION_LEVELS = {
    "general": AdmissionLevel.General,
    "bachelor": AdmissionLevel.Bachelor,
    "master": AdmissionLevel.Master,
    "mba": AdmissionLevel.Mba,
    "phd": AdmissionLevel.Phd,
}

_PROGRAM_LEVELS = {
    "bachelor": ProgramLevel.Bachelor,
    "master": ProgramLevel.Master,
    "mba": ProgramLevel.Mba,
    "phd": ProgramLevel.Phd,
}


def _pick(source: Any, *path: str) -> Any:
    """Walk a dict path defensively; return the value at the end or None."""
    node = source
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _pick_str(source: Any, *paths: tuple[str, ...], limit: int = 250) -> str | None:
    """First non-empty string among alternative paths (sources may differ).
    Truncated defensively so no dump value can overflow a varchar column."""
    for path in paths:
        value = _pick(source, *path)
        if isinstance(value, str) and value.strip():
            return value.strip()[:limit]
    return None


def _normalize_dashes(name: str) -> str:
    """Unify unicode dashes (—, –) and stray punctuation so near-duplicate source
    variants of the same university slug identically (e.g. 'Berkeley' from QS vs
    US News)."""
    return re.sub(r"[—–\-]", " ", name)


_SMALL_WORDS = {"of", "and", "the", "at", "in", "for", "a", "an", "on", "de"}


def _display_name(name: str) -> str:
    """Title-case dump names ("university of tehran" → "University of Tehran")
    while keeping acronyms (MIT, ETH) and already-cased names intact."""
    words: list[str] = []
    for i, w in enumerate(name.split()):
        if w.isupper() and len(w) > 1:
            words.append(w)  # acronym
            continue
        lw = w.lower()
        if i != 0 and lw in _SMALL_WORDS:
            words.append(lw)
        else:
            words.append(lw[0].upper() + lw[1:])
    return " ".join(words)


def map_dump_payload(json_content: dict, fallback_name: str | None) -> UniversityPayload | None:
    """Map one university_data row's JSON onto the canonical payload. Returns None
    when there is no usable name."""
    name = _pick_str(json_content, ("university_identity", "name")) or (
        fallback_name.strip() if fallback_name and fallback_name.strip() else None
    )
    if not name:
        return None

    payload = UniversityPayload(
        name=_display_name(name),
        about=_pick_str(
            json_content,
            ("university_overview", "about_university", "qs"),
            ("university_overview", "introduction", "shanghai"),
            ("university_overview", "summary", "us_news"),
        )
        or "",
        qs_world_rank=_pick_str(json_content, ("rankings", "global", "qs", "current_rank")),
        campus_location=_pick_str(
            json_content,
            ("university_overview", "campus_location", "qs"),
            ("university_identity", "location", "us_news"),
            ("university_identity", "location", "shanghai"),
        ),
        facilities=_pick_str(json_content, ("facilities", "qs", "facilities")),
        scholarships=_pick_str(json_content, ("costs_and_finances", "qs", "scholarships")),
        career_services=_pick_str(json_content, ("employability", "qs", "career_services")),
        country_name=_pick_str(
            json_content,
            ("university_identity", "country", "shanghai"),
            ("university_identity", "country", "us_news"),
        ),
        costs_of_living=None,
        overall_tuition=_tuition(json_content),
        admissions=_admissions(json_content),
        student_staff_buckets=_student_staff(json_content),
        ranking=_ranking(json_content),
        programs=_programs(json_content),
    )
    return payload


def _tuition(json_content: dict) -> dict | None:
    tuition = _pick(json_content, "costs_and_finances", "qs", "tuition_fees")
    if not isinstance(tuition, dict) or not tuition:
        return None
    domestic = tuition.get("domestic_starts_from")
    international = tuition.get("international_starts_from")
    if not (isinstance(domestic, str) and domestic.strip()) and not (
        isinstance(international, str) and international.strip()
    ):
        return None
    return {
        "domestic_from": domestic or None,
        "international_from": international or None,
    }


_ADMISSION_FIELDS = {
    "GPA": "gpa",
    "GRE": "gre",
    "SAT": "sat",
    "GMAT": "gmat",
    "IELTS": "ielts",
    "TOEFL": "toefl",
    "PTE_ACADEMIC": "pte",
    "CAMBRIDGE_CAE_ADVANCED": "cambridge_cae",
    "INTERNATIONAL_BACCALAUREATE": "ib",
}


def _admissions(json_content: dict) -> list[AdmissionPayload]:
    qs = _pick(json_content, "admissions", "qs")
    if not isinstance(qs, dict):
        return []
    out: list[AdmissionPayload] = []
    for level_key, level in _ADMISSION_LEVELS.items():
        bucket = qs.get(level_key)
        if not isinstance(bucket, dict):
            continue
        fields = {}
        for src_key, dst in _ADMISSION_FIELDS.items():
            value = bucket.get(src_key)
            if isinstance(value, str) and value.strip():
                fields[dst] = value.strip()
        if not fields:
            continue
        out.append(AdmissionPayload(level=level, **fields))
    return out


def _programs(json_content: dict) -> list[ProgramPayload]:
    available = _pick(json_content, "programmes", "qs", "available_programmes")
    if not isinstance(available, dict):
        return []
    out: list[ProgramPayload] = []
    for level_key, level in _PROGRAM_LEVELS.items():
        faculties = available.get(level_key)
        if not isinstance(faculties, list):
            continue
        count = 0
        for faculty in faculties:
            if not isinstance(faculty, dict):
                continue
            for department in faculty.get("departments") or []:
                if not isinstance(department, dict):
                    continue
                for program in department.get("programs") or []:
                    if count >= MAX_PROGRAMS_PER_LEVEL:
                        break
                    name = program.get("program_name") if isinstance(program, dict) else None
                    if isinstance(name, str) and name.strip():
                        out.append(ProgramPayload(level=level, name=name.strip()))
                        count += 1
    return out


def _student_staff(json_content: dict) -> list[StudentStaffBucket]:
    stats = _pick(json_content, "university_statistics", "qs", "student_and_staff")
    if not isinstance(stats, dict):
        return []
    buckets = []
    for key, bucket_key in (
        ("total_student", "Total Students"),
        ("international_students", "International Students"),
        ("total_faculty_staff", "Faculty"),
    ):
        bucket = stats.get(key)
        if isinstance(bucket, dict) and bucket:
            buckets.append(StudentStaffBucket(key=bucket_key, json=bucket))
    return buckets


def _ranking(json_content: dict) -> RankingPayload | None:
    qs = _pick(json_content, "rankings", "global", "qs")
    if not isinstance(qs, dict):
        return None
    criteria = qs.get("ranking_criteria")
    ratings = qs.get("rankings_ratings")

    def rating(key: str) -> str | None:
        value = ratings.get(key) if isinstance(ratings, dict) else None
        return value.strip() if isinstance(value, str) and value.strip() else None

    return RankingPayload(
        qs_world=_pick_str(json_content, ("rankings", "global", "qs", "current_rank")),
        qs_subject=rating("qs_wur_ranking_by_subject"),
        qs_sustainability=rating("qs_sustainability_ranking"),
        europe_rank=rating("europe_university_rankings_northern_europe")
        or rating("europe_university_rankings_northern")
        or rating("europe_university_rankings_northers_europe"),
        criteria=criteria if isinstance(criteria, dict) and criteria else None,
        yearly_data=None,
    )
