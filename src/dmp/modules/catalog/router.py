"""Catalog API routers (public, client, admin).

Path-for-path parity with the .NET controllers. The client detail route is
subscription-gated; the gate is shared from the billing module.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...deps import current_admin, current_user_id
from ...domain.models import Admin
from ...envelope import AppException, ok
from .service import CatalogService

router_public = APIRouter(prefix="/api/v1/public", tags=["catalog (public)"])
router_client = APIRouter(prefix="/api/v1/client/universities", tags=["catalog (client)"])
router_admin = APIRouter(prefix="/api/v1/admin/catalog", tags=["catalog (admin)"])

_catalog = CatalogService()


# ── Public (no auth) ────────────────────────────────────────────────────────────


@router_public.get("/universities")
async def list_public(
    search: str | None = None,
    countryId: str | None = None,
    page: int = 1,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    data = await _catalog.list_public_cards(session, search, countryId, page, limit)
    return ok(data)


@router_public.get("/universities/{slug}")
async def get_public_card(slug: str, session: AsyncSession = Depends(get_session)):
    card = await _catalog.get_public_card(session, slug)
    if card is None:
        raise AppException.not_found("University not found")
    return ok(card)


@router_public.get("/countries")
async def list_countries(session: AsyncSession = Depends(get_session)):
    return ok(await _catalog.list_countries(session))


# ── Client (subscription-gated) ─────────────────────────────────────────────────


@router_client.get("/{slug}")
async def client_detail(
    slug: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # Local import: billing.subscription_gate imports domain only (no cycle).
    from ..billing.subscription_gate import has_active_subscription

    has_sub = await has_active_subscription(session, user_id)
    detail = await _catalog.get_detail(session, slug, user_id, has_sub)
    return ok({"detail": detail, "hasSubscription": has_sub})


# ── Admin ───────────────────────────────────────────────────────────────────────


@router_admin.get("/universities")
async def admin_list(
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _catalog.admin_list(session))


@router_admin.get("/universities/{id}")
async def admin_get(
    id: str,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _catalog.admin_get(session, id))


@router_admin.post("/universities")
async def admin_create(
    req: dict,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    from .dto import UniversityUpsertRequest

    return ok(await _catalog.admin_create(session, UniversityUpsertRequest(**req)))


@router_admin.put("/universities/{id}")
async def admin_update(
    id: str,
    req: dict,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    from .dto import UniversityUpsertRequest

    return ok(await _catalog.admin_update(session, id, UniversityUpsertRequest(**req)))


@router_admin.delete("/universities/{id}")
async def admin_delete(
    id: str,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _catalog.admin_delete(session, id)
    return ok()


@router_admin.post("/import-json")
async def admin_import_json(
    request: Request,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    json_text = (await request.body()).decode("utf-8")
    result = await _catalog.import_json(session, json_text, source_name=None, country_code=None)
    return ok(result)
