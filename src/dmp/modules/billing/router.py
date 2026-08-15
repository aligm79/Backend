"""Billing API routers (admin, client, public callback). Path-for-path parity with
AdminBillingController / ClientBillingController / PublicPaymentController.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...deps import current_admin, current_user_id
from ...domain.models import Admin
from ...envelope import ok
from .dto import PlanCreateRequest, PlanUpdateRequest, StartPaymentRequest
from .service import BillingService

router_admin = APIRouter(prefix="/api/v1/admin", tags=["billing (admin)"])
router_client = APIRouter(prefix="/api/v1/client/billing", tags=["billing (client)"])
router_public = APIRouter(prefix="/api/v1/public/payments", tags=["billing (public)"])

_billing = BillingService()


# ── Admin ───────────────────────────────────────────────────────────────────────


@router_admin.get("/stats")
async def stats(
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _billing.admin_stats(session))


@router_admin.get("/subscription-plans")
async def list_plans(
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok([p.model_dump(exclude_none=True) for p in await _billing.list_plans(session, True)])


@router_admin.post("/subscription-plans")
async def create_plan(
    req: PlanCreateRequest,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    plan = await _billing.create_plan(session, req)
    return ok(plan.model_dump(exclude_none=True))


@router_admin.put("/subscription-plans/{id}")
async def update_plan(
    id: str,
    req: PlanUpdateRequest,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    plan = await _billing.update_plan(session, id, req)
    return ok(plan.model_dump(exclude_none=True))


@router_admin.delete("/subscription-plans/{id}")
async def delete_plan(
    id: str,
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    await _billing.delete_plan(session, id)
    return ok()


@router_admin.get("/payments")
async def list_payments(
    _admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    return ok([p.model_dump(exclude_none=True) for p in await _billing.admin_list_payments(session)])


# ── Client ──────────────────────────────────────────────────────────────────────


@router_client.get("/plans")
async def plans(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok([p.model_dump(exclude_none=True) for p in await _billing.list_active_plans(session)])


@router_client.post("/payments/start")
async def start_payment(
    req: StartPaymentRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await _billing.start_payment(session, user_id, req)
    return ok(result.model_dump(exclude_none=True))


@router_client.get("/subscriptions")
async def my_subscriptions(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok([s.model_dump(exclude_none=True) for s in await _billing.list_my_subscriptions(session, user_id)])


@router_client.get("/payments")
async def my_payments(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    return ok([p.model_dump(exclude_none=True) for p in await _billing.list_my_payments(session, user_id)])


# ── Public callback (no auth — Zarinpal hits this from the browser) ─────────────


@router_public.get("/callback")
async def callback(
    authority: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    result = await _billing.handle_callback(session, authority, status)
    return ok(result.model_dump(exclude_none=True))
