"""University catalog operations: public cards (free), gated detail (subscription),
admin CRUD, and JSON import (idempotent by slug). Direct port of CatalogService.cs.
"""

from __future__ import annotations

import math
import re

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.models import (
    CatalogItemType,
    Country,
    University,
    UniversityAdmission,
    UniversityData,
    UniversityProgram,
    UniversityRanking,
    UniversityStudentStaff,
)
from ...envelope import AppException
from ...security import new_uuid_hex
from . import mapper
from .dto import (
    AdmissionDto,
    CountryResponse,
    ImportResult,
    ProgramDto,
    RankingDto,
    StudentStaffDto,
    UniversityCard,
    UniversityDetail,
    UniversityUpsertRequest,
)

UNIVERSITY_TYPE_CODE = "university"

_SAMPLE_IMAGES: dict[str, tuple[str, str]] = {
    "harvard": ("/university-covers/harvard.jpg", "/university-logos/harvard.svg"),
    "mit": ("/university-covers/mit.jpg", "/university-logos/mit.svg"),
    "stanford": ("/university-covers/stanford.jpg", "/university-logos/stanford.svg"),
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", value.lower().strip())
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug or "item"


_DUMP_SHAPE_KEYS = ("university_identity", "rankings", "programmes", "university_statistics")


def _parse_any_json(json_text: str) -> list:
    """Parse a bulk-import document in EITHER supported shape:
    - the legacy sample shape ({ "university": {...} } / bare {...} / arrays), or
    - the university_data dump shape (sections like rankings/programmes/...).
    Each element is mapped onto the canonical UniversityPayload."""
    import json as _json

    from . import dump_mapper

    root = _json.loads(json_text)
    elements = root if isinstance(root, list) else [root]
    out = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        target = el["university"] if isinstance(el.get("university"), dict) else el
        if any(k in target for k in _DUMP_SHAPE_KEYS):
            p = dump_mapper.map_dump_payload(target, None)
            if p is not None:
                # Normalize unicode dashes so source variants slug consistently
                # with the university_data importer.
                p.name = dump_mapper._normalize_dashes(p.name)
                out.append(p)
        else:
            out.append(mapper._parse_one(el))
    return out


def _teaser(text: str) -> str:
    if not text:
        return ""
    return text if len(text) <= 220 else text[:220].rstrip() + "…"


def _clamp_paging(page: int, limit: int) -> tuple[int, int]:
    p = max(1, page)
    lim = 20 if limit <= 0 else limit
    lim = max(1, min(100, lim))
    return p, lim


def _paginate(items: list, total: int, page: int, limit: int) -> dict:
    return {"items": items, "meta": {"total": total, "page": page, "limit": limit, "total_page": math.ceil(total / limit)}}


def _image_for(name: str) -> tuple[str, str]:
    for key, pair in _SAMPLE_IMAGES.items():
        if key in name.lower():
            return pair
    return ("/university-covers/default.svg", "/university-logos/default.svg")


class CatalogService:
    # ── Public (no auth) ────────────────────────────────────────────────────────

    async def list_public_cards(
        self,
        session: AsyncSession,
        search: str | None,
        country_id: str | None,
        page: int,
        limit: int,
    ) -> dict:
        p, lim = _clamp_paging(page, limit)
        stmt = select(University, Country).outerjoin(Country, University.country_id == Country.id).where(
            University.is_published.is_(True)
        )
        if search and search.strip():
            stmt = stmt.where(University.name.ilike(f"%{search}%"))
        if country_id:
            stmt = stmt.where(University.country_id == country_id)

        # Total count
        count_stmt = select(func.count()).select_from(University).where(University.is_published.is_(True))
        if search and search.strip():
            count_stmt = count_stmt.where(University.name.ilike(f"%{search}%"))
        if country_id:
            count_stmt = count_stmt.where(University.country_id == country_id)
        total = (await session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(University.sort_order, University.name).offset((p - 1) * lim).limit(lim)
        rows = (await session.execute(stmt)).all()

        items = [
            UniversityCard(
                id=u.id,
                slug=u.slug,
                name=u.name,
                logoUrl=u.logo_url,
                coverImageUrl=u.cover_image_url,
                qsWorldRank=u.qs_world_rank,
                campusLocation=u.campus_location,
                aboutTeaser=_teaser(u.about),
                sortOrder=u.sort_order,
                countryName=c.name if c else None,
                countryFlag=c.flag_emoji if c else None,
            )
            for u, c in rows
        ]
        return _paginate([item.model_dump(by_alias=False, exclude_none=True) for item in items], total, p, lim)

    async def get_public_card(self, session: AsyncSession, slug: str) -> dict | None:
        stmt = (
            select(University, Country)
            .outerjoin(Country, University.country_id == Country.id)
            .where(University.slug == slug, University.is_published.is_(True))
        )
        row = (await session.execute(stmt)).first()
        if not row:
            return None
        u, c = row
        card = UniversityCard(
            id=u.id,
            slug=u.slug,
            name=u.name,
            logoUrl=u.logo_url,
            coverImageUrl=u.cover_image_url,
            qsWorldRank=u.qs_world_rank,
            campusLocation=u.campus_location,
            aboutTeaser=_teaser(u.about),
            sortOrder=u.sort_order,
            countryName=c.name if c else None,
            countryFlag=c.flag_emoji if c else None,
        )
        return card.model_dump(exclude_none=True)

    # ── Client (subscription-gated) ─────────────────────────────────────────────


    async def _free_preview_ids(self, session: AsyncSession) -> set[str]:
        """Ids of the first universities by (sort_order, name) — viewable without
        a subscription (freemium preview; everything else stays gated)."""
        stmt = select(University.id).order_by(University.sort_order, University.name).limit(3)
        return {row for (row,) in (await session.execute(stmt)).all()}

    async def get_detail(
        self, session: AsyncSession, slug: str, user_id: str, has_subscription: bool
    ) -> dict:
        stmt = (
            select(University)
            .options(
                selectinload(University.programs),
                selectinload(University.admissions),
                selectinload(University.student_staff),
                selectinload(University.ranking),
                selectinload(University.country),
            )
            .where(University.slug == slug)
        )
        u = (await session.execute(stmt)).scalar_one_or_none()
        if u is None:
            raise AppException.not_found("University not found")
        if not u.is_published and not has_subscription:
            raise AppException.not_found("University not found")
        if not has_subscription and u.id not in await self._free_preview_ids(session):
            raise AppException.forbidden("An active subscription is required to view full details")
        return _to_detail(u).model_dump(exclude_none=True)

    # ── Admin CRUD ──────────────────────────────────────────────────────────────

    async def admin_list(self, session: AsyncSession) -> list[dict]:
        stmt = (
            select(University)
            .options(
                selectinload(University.programs),
                selectinload(University.admissions),
                selectinload(University.student_staff),
                selectinload(University.ranking),
                selectinload(University.country),
            )
            .order_by(University.sort_order, University.name)
        )
        unis = (await session.execute(stmt)).scalars().all()
        return [_to_detail(u).model_dump(exclude_none=True) for u in unis]

    async def admin_get(self, session: AsyncSession, id_: str) -> dict:
        u = await self._load(session, id_)
        return _to_detail(u).model_dump(exclude_none=True)

    async def admin_create(self, session: AsyncSession, req: UniversityUpsertRequest) -> dict:
        if not req.name or not req.name.strip():
            raise AppException.validation("name is required")
        type_id = await self._ensure_university_type_id(session)
        slug = await self._ensure_unique_slug(session, req.slug or _slugify(req.name), None)

        u = University(
            id=new_uuid_hex(),
            catalog_item_type_id=type_id,
            slug=slug,
            name=req.name.strip(),
            logo_url=req.logoUrl,
            cover_image_url=req.coverImageUrl,
            qs_world_rank=req.qsWorldRank,
            about=req.about,
            international_students_pct=req.internationalStudentsPct,
            facilities=req.facilities,
            scholarships=req.scholarships,
            career_services=req.careerServices,
            campus_location=req.campusLocation,
            country_id=req.countryId,
            costs_of_living=req.parsed_costs(),
            tuition_fees=req.parsed_tuition(),
            is_published=req.isPublished,
            sort_order=req.sortOrder,
        )
        session.add(u)
        await session.commit()
        # Re-fetch with relationships eagerly loaded (_load uses selectinload) so
        # _to_detail doesn't trigger lazy IO outside the async greenlet.
        loaded = await self._load(session, u.id)
        return _to_detail(loaded).model_dump(exclude_none=True)

    async def admin_update(self, session: AsyncSession, id_: str, req: UniversityUpsertRequest) -> dict:
        u = await self._load(session, id_)
        if req.name and req.name.strip():
            u.name = req.name.strip()
        if req.slug and req.slug.strip() and req.slug != u.slug:
            u.slug = await self._ensure_unique_slug(session, req.slug, u.id)
        u.logo_url = req.logoUrl
        u.cover_image_url = req.coverImageUrl
        u.qs_world_rank = req.qsWorldRank
        u.about = req.about
        u.international_students_pct = req.internationalStudentsPct
        u.facilities = req.facilities
        u.scholarships = req.scholarships
        u.career_services = req.careerServices
        u.campus_location = req.campusLocation
        u.country_id = req.countryId
        u.costs_of_living = req.parsed_costs()
        u.tuition_fees = req.parsed_tuition()
        u.is_published = req.isPublished
        u.sort_order = req.sortOrder
        await session.commit()
        # Re-fetch fresh (expire stale relationship state + eager-load).
        loaded = await self._load(session, id_)
        return _to_detail(loaded).model_dump(exclude_none=True)

    async def admin_delete(self, session: AsyncSession, id_: str) -> None:
        u = await self._load(session, id_)
        await session.delete(u)
        await session.commit()

    # ── JSON import ─────────────────────────────────────────────────────────────

    async def import_json(
        self,
        session: AsyncSession,
        json_text: str,
        source_name: str | None = None,
        country_code: str | None = None,
    ) -> list[dict]:
        payloads = _parse_any_json(json_text)
        results: list[dict] = []
        type_id = await self._ensure_university_type_id(session)

        country_id: str | None = None
        if country_code and country_code.strip():
            country_id = await self._resolve_country_id_by_code(session, country_code)

        for p in payloads:
            name = p.name.strip() if p.name and p.name.strip() else (
                source_name.strip() if source_name and source_name.strip() else "(imported)"
            )
            slug = _slugify(name)
            warnings: list[str] = []

            existing = (
                await session.execute(select(University).where(University.slug == slug))
            ).scalar_one_or_none()
            created = existing is None

            if created:
                u = University(
                    id=new_uuid_hex(),
                    catalog_item_type_id=type_id,
                    slug=slug,
                    name=name,
                )
                session.add(u)
            else:
                u = existing

            u.name = name
            u.about = p.about
            u.qs_world_rank = p.qs_world_rank
            u.international_students_pct = p.international_students_pct
            u.campus_location = p.campus_location
            # Only assign country on first import (don't clobber manual mapping).
            if created and country_id is not None:
                u.country_id = country_id
            u.facilities = p.facilities
            u.scholarships = p.scholarships
            u.career_services = p.career_services
            u.costs_of_living = p.costs_of_living
            u.tuition_fees = _extract_tuition(p)
            u.is_published = True

            cover, logo = _image_for(name)
            if u.cover_image_url is None:
                u.cover_image_url = cover
            if u.logo_url is None:
                u.logo_url = logo

            await session.commit()

            await self._replace_programs(session, u.id, p.programs)
            await self._replace_admissions(session, u.id, p.admissions)
            await self._upsert_student_staff(session, u.id, p.student_staff_buckets, p.student_life)
            await self._upsert_ranking(session, u.id, p.ranking)

            results.append(
                ImportResult(
                    universityId=u.id, slug=u.slug, name=u.name, created=created, warnings=warnings
                ).model_dump()
            )
        return results

    # ── university_data dump import (merge-fill) ────────────────────────────────

    async def import_university_data(self, session: AsyncSession) -> dict:
        """Import rows from the restored `university_data` landing table into the
        canonical catalog.

        Merge semantics (safe to re-run and future-dump tolerant):
        - New universities are created.
        - Existing ones (matched by slug) are only ENRICHED: scalar fields are
          filled when empty, children added only when absent, country set only
          when unmapped. Manual edits are never overwritten.
        """
        from . import dump_mapper

        rows = (
            await session.execute(
                select(UniversityData).order_by(UniversityData.inserted_at.nulls_last(), UniversityData.id)
            )
        ).scalars().all()

        summary = {"created": 0, "merged": 0, "skipped": 0, "totalRows": len(rows)}
        if not rows:
            return summary

        type_id = await self._ensure_university_type_id(session)
        order = (await session.execute(select(func.count(University.id)))).scalar_one()

        for row in rows:
            payload = dump_mapper.map_dump_payload(row.json_content or {}, row.university_name)
            if payload is None or not payload.name:
                summary["skipped"] += 1
                continue

            name = dump_mapper._normalize_dashes(payload.name)
            slug = _slugify(name)
            existing = (
                await session.execute(
                    select(University)
                    .options(
                        selectinload(University.programs),
                        selectinload(University.admissions),
                        selectinload(University.student_staff),
                        selectinload(University.ranking),
                    )
                    .where(University.slug == slug)
                )
            ).scalar_one_or_none()
            created = existing is None

            if created:
                u = University(
                    id=new_uuid_hex(),
                    catalog_item_type_id=type_id,
                    slug=slug,
                    name=payload.name.strip(),
                    sort_order=order,
                )
                session.add(u)
                order += 1
            else:
                u = existing

            # Fill-empty merge on scalars.
            if not u.about and payload.about:
                u.about = payload.about
            if not u.qs_world_rank and payload.qs_world_rank:
                u.qs_world_rank = payload.qs_world_rank
            if not u.campus_location and payload.campus_location:
                u.campus_location = payload.campus_location
            if not u.facilities and payload.facilities:
                u.facilities = payload.facilities
            if not u.scholarships and payload.scholarships:
                u.scholarships = payload.scholarships
            if not u.career_services and payload.career_services:
                u.career_services = payload.career_services
            if not u.tuition_fees and payload.overall_tuition:
                u.tuition_fees = payload.overall_tuition

            cover, logo = _image_for(payload.name)
            if u.cover_image_url is None:
                u.cover_image_url = cover
            if u.logo_url is None:
                u.logo_url = logo

            if u.country_id is None and payload.country_name:
                country_id = await self._resolve_country_id_by_name(session, payload.country_name)
                if country_id:
                    u.country_id = country_id

            await session.commit()

            # Children: for existing rows only populate when currently absent
            # (never clobber). New rows are empty by definition — accessing the
            # relationship would trigger a lazy load outside the async greenlet.
            if created:
                if payload.programs:
                    await self._replace_programs(session, u.id, payload.programs)
                if payload.admissions:
                    await self._replace_admissions(session, u.id, payload.admissions)
                if payload.student_staff_buckets:
                    await self._upsert_student_staff(session, u.id, payload.student_staff_buckets, payload.student_life)
                if payload.ranking:
                    await self._upsert_ranking(session, u.id, payload.ranking)
            else:
                if not u.programs and payload.programs:
                    await self._replace_programs(session, u.id, payload.programs)
                if not u.admissions and payload.admissions:
                    await self._replace_admissions(session, u.id, payload.admissions)
                if not u.student_staff and payload.student_staff_buckets:
                    await self._upsert_student_staff(session, u.id, payload.student_staff_buckets, payload.student_life)
                if not u.ranking and payload.ranking:
                    await self._upsert_ranking(session, u.id, payload.ranking)

            summary["created" if created else "merged"] += 1

        return summary

    # ── Countries ───────────────────────────────────────────────────────────────

    async def list_countries(self, session: AsyncSession) -> list[dict]:
        rows = (
            await session.execute(select(Country).order_by(Country.name))
        ).scalars().all()
        return [
            CountryResponse(id=c.id, code=c.code, name=c.name, flagEmoji=c.flag_emoji).model_dump(exclude_none=True)
            for c in rows
        ]

    # ── helpers ─────────────────────────────────────────────────────────────────

    async def _load(self, session: AsyncSession, id_: str) -> University:
        stmt = (
            select(University)
            .options(
                selectinload(University.programs),
                selectinload(University.admissions),
                selectinload(University.student_staff),
                selectinload(University.ranking),
                selectinload(University.country),
            )
            .where(University.id == id_)
        )
        u = (await session.execute(stmt)).scalar_one_or_none()
        if u is None:
            raise AppException.not_found("University not found")
        return u

    async def _ensure_university_type_id(self, session: AsyncSession) -> str:
        type_ = (
            await session.execute(select(CatalogItemType).where(CatalogItemType.code == UNIVERSITY_TYPE_CODE))
        ).scalar_one_or_none()
        if type_ is not None:
            return type_.id
        type_ = CatalogItemType(id=new_uuid_hex(), code=UNIVERSITY_TYPE_CODE, name_key="catalog.type.university")
        session.add(type_)
        await session.commit()
        return type_.id

    async def _resolve_country_id_by_code(self, session: AsyncSession, code: str) -> str | None:
        c = (
            await session.execute(select(Country).where(Country.code == code.upper()))
        ).scalar_one_or_none()
        return c.id if c else None

    async def _resolve_country_id_by_name(self, session: AsyncSession, name: str) -> str | None:
        """Case-insensitive country lookup by English name (dump payloads carry
        names like 'United States'; falls back to a prefix match for variants)."""
        exact = (
            await session.execute(select(Country).where(func.lower(Country.name) == name.strip().lower()))
        ).scalar_one_or_none()
        if exact:
            return exact.id
        fuzzy = (
            await session.execute(
                select(Country)
                .where(func.lower(Country.name).like(f"%{name.strip().lower()}%"))
                .limit(1)
            )
        ).scalar_one_or_none()
        return fuzzy.id if fuzzy else None

    async def _ensure_unique_slug(
        self, session: AsyncSession, slug: str, self_id: str | None
    ) -> str:
        slug = _slugify(slug)
        base = slug
        n = 1
        while True:
            stmt = select(University.id).where(University.slug == slug)
            if self_id:
                stmt = stmt.where(University.id != self_id)
            exists = (await session.execute(stmt)).first()
            if not exists:
                return slug
            n += 1
            slug = f"{base}-{n}"

    async def _replace_programs(self, session: AsyncSession, uni_id: str, programs: list) -> None:
        await session.execute(delete(UniversityProgram).where(UniversityProgram.university_id == uni_id))
        for p in programs:
            session.add(
                UniversityProgram(id=new_uuid_hex(), university_id=uni_id, level=p.level, name=p.name)
            )
        await session.commit()

    async def _replace_admissions(self, session: AsyncSession, uni_id: str, admissions: list) -> None:
        await session.execute(delete(UniversityAdmission).where(UniversityAdmission.university_id == uni_id))
        for a in admissions:
            session.add(
                UniversityAdmission(
                    id=new_uuid_hex(),
                    university_id=uni_id,
                    level=a.level,
                    toefl=a.toefl,
                    ielts=a.ielts,
                    cambridge_cae=a.cambridge_cae,
                    pte=a.pte,
                    ib=a.ib,
                    sat=a.sat,
                    gre=a.gre,
                    gmat=a.gmat,
                    gpa=a.gpa,
                )
            )
        await session.commit()

    async def _upsert_student_staff(
        self, session: AsyncSession, uni_id: str, buckets: list, student_life: str | None
    ) -> None:
        existing = (
            await session.execute(select(UniversityStudentStaff).where(UniversityStudentStaff.university_id == uni_id))
        ).scalar_one_or_none()
        if existing is None:
            existing = UniversityStudentStaff(id=new_uuid_hex(), university_id=uni_id)
            session.add(existing)
        existing.student_life = student_life
        for b in buckets:
            key = b.key.lower()
            if "total student" in key and "international" not in key:
                existing.total_students = b.json
            elif "international student" in key:
                existing.international_students = b.json
            elif "faculty" in key:
                existing.total_faculty = b.json
        await session.commit()

    async def _upsert_ranking(self, session: AsyncSession, uni_id: str, r: mapper.RankingPayload | None) -> None:
        if r is None:
            return
        existing = (
            await session.execute(select(UniversityRanking).where(UniversityRanking.university_id == uni_id))
        ).scalar_one_or_none()
        if existing is None:
            existing = UniversityRanking(id=new_uuid_hex(), university_id=uni_id)
            session.add(existing)
        existing.qs_world = r.qs_world
        existing.qs_subject = r.qs_subject
        existing.qs_sustainability = r.qs_sustainability
        existing.europe_rank = r.europe_rank
        existing.criteria = r.criteria
        existing.yearly_data = r.yearly_data
        await session.commit()


def _extract_tuition(p: mapper.UniversityPayload) -> dict | None:
    if p.overall_tuition is None:
        return None
    try:
        otf = p.overall_tuition.get("overall tuition fees")
        if isinstance(otf, dict):
            return otf
        return p.overall_tuition
    except Exception:
        return p.overall_tuition


def _to_detail(u: University) -> UniversityDetail:
    programs = sorted(u.programs, key=lambda p: p.level)
    admissions = sorted(u.admissions, key=lambda a: a.level)
    return UniversityDetail(
        id=u.id,
        slug=u.slug,
        name=u.name,
        logoUrl=u.logo_url,
        coverImageUrl=u.cover_image_url,
        qsWorldRank=u.qs_world_rank,
        campusLocation=u.campus_location,
        about=u.about,
        isPublished=u.is_published,
        sortOrder=u.sort_order,
        internationalStudentsPct=u.international_students_pct,
        facilities=u.facilities,
        scholarships=u.scholarships,
        careerServices=u.career_services,
        costsOfLiving=u.costs_of_living,
        tuitionFees=u.tuition_fees,
        programs=[ProgramDto(level=p.level.value if hasattr(p.level, "value") else str(p.level), name=p.name) for p in programs],
        admissions=[
            AdmissionDto(
                level=a.level.value if hasattr(a.level, "value") else str(a.level),
                toefl=a.toefl,
                ielts=a.ielts,
                cambridgeCae=a.cambridge_cae,
                pte=a.pte,
                ib=a.ib,
                sat=a.sat,
                gre=a.gre,
                gmat=a.gmat,
                gpa=a.gpa,
            )
            for a in admissions
        ],
        studentStaff=(
            StudentStaffDto(
                totalStudents=u.student_staff.total_students,
                internationalStudents=u.student_staff.international_students,
                totalFaculty=u.student_staff.total_faculty,
                studentLife=u.student_staff.student_life,
            )
            if u.student_staff
            else None
        ),
        ranking=(
            RankingDto(
                qsWorld=u.ranking.qs_world,
                qsSubject=u.ranking.qs_subject,
                qsSustainability=u.ranking.qs_sustainability,
                europeRank=u.ranking.europe_rank,
                criteria=u.ranking.criteria,
                yearlyData=u.ranking.yearly_data,
            )
            if u.ranking
            else None
        ),
        countryId=u.country_id,
        countryName=u.country.name if u.country else None,
        countryFlag=u.country.flag_emoji if u.country else None,
    )
