"""Subscription plans, subscription creation, and the Zarinpal purchase flow.

Direct port of BillingService.cs. Flow: start_payment creates a pending subscription +
payment, asks Zarinpal for an authority, returns the gateway URL. On redirect-back,
handle_callback verifies and activates the subscription (extending an existing one).
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db import utcnow
from ...domain.enums import PaymentStatus, SubscriptionStatus, UserStatus
from ...domain.models import Payment, Subscription, SubscriptionPlan, User
from ...envelope import AppException
from ...security import new_uuid_hex
from . import zarinpal
from .dto import (
    PaymentResponse,
    PaymentResultResponse,
    PlanResponse,
    StartPaymentRequest,
    StartPaymentResponse,
    SubscriptionResponse,
)

log = logging.getLogger("dmp.billing")


class BillingService:
    # ── Plans (admin) ───────────────────────────────────────────────────────────

    async def create_plan(self, session: AsyncSession, req) -> PlanResponse:
        _validate_plan(req.priceToman, req.durationDays, req.nameKey)
        plan = SubscriptionPlan(
            id=new_uuid_hex(),
            name_key=req.nameKey,
            description_key=req.descriptionKey or "",
            price_toman=req.priceToman,
            duration_days=req.durationDays,
            is_active=req.isActive,
            sort_order=req.sortOrder,
            features=req.parsed_features(),
        )
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return _to_plan(plan)

    async def update_plan(self, session: AsyncSession, id_: str, req) -> PlanResponse:
        plan = await self._get_plan(session, id_)
        if req.nameKey is not None:
            plan.name_key = req.nameKey
        if req.descriptionKey is not None:
            plan.description_key = req.descriptionKey
        if req.priceToman is not None:
            if req.priceToman < 0:
                raise AppException.validation("Price must be non-negative")
            plan.price_toman = req.priceToman
        if req.durationDays is not None:
            if req.durationDays <= 0:
                raise AppException.validation("Duration must be positive")
            plan.duration_days = req.durationDays
        if req.isActive is not None:
            plan.is_active = req.isActive
        if req.sortOrder is not None:
            plan.sort_order = req.sortOrder
        if req.features is not None:
            plan.features = req.parsed_features()
        await session.commit()
        await session.refresh(plan)
        return _to_plan(plan)

    async def list_plans(self, session: AsyncSession, include_inactive: bool) -> list[PlanResponse]:
        stmt = select(SubscriptionPlan)
        if not include_inactive:
            stmt = stmt.where(SubscriptionPlan.is_active.is_(True))
        stmt = stmt.order_by(SubscriptionPlan.sort_order, SubscriptionPlan.price_toman)
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_plan(p) for p in rows]

    async def delete_plan(self, session: AsyncSession, id_: str) -> None:
        plan = await self._get_plan(session, id_)
        has_subs = (
            await session.execute(select(Subscription.id).where(Subscription.plan_id == id_).limit(1))
        ).first()
        if has_subs:
            raise AppException.conflict("Cannot delete a plan that has subscriptions; deactivate it instead")
        await session.delete(plan)
        await session.commit()

    # ── Client: list & buy ──────────────────────────────────────────────────────

    async def list_active_plans(self, session: AsyncSession) -> list[PlanResponse]:
        return await self.list_plans(session, include_inactive=False)

    async def start_payment(
        self, session: AsyncSession, user_id: str, req: StartPaymentRequest
    ) -> StartPaymentResponse:
        plan = (
            await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == req.planId))
        ).scalar_one_or_none()
        if plan is None:
            raise AppException.not_found("Plan not found")
        if not plan.is_active:
            raise AppException.bad_request("This plan is not available")

        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise AppException.not_found("User not found")
        if user.status == UserStatus.Suspended:
            raise AppException.forbidden("Account suspended")

        from datetime import timedelta

        now = utcnow()
        subscription = Subscription(
            id=new_uuid_hex(),
            user_id=user_id,
            plan_id=plan.id,
            start_at=now,
            end_at=now + timedelta(days=plan.duration_days),
            status=SubscriptionStatus.PendingPayment,
        )
        payment = Payment(
            id=new_uuid_hex(),
            user_id=user_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            amount_toman=plan.price_toman,
            status=PaymentStatus.Pending,
            gateway="zarinpal",
            description=f"Subscription {plan.name_key} ({plan.duration_days} days)",
        )
        session.add(subscription)
        session.add(payment)
        await session.commit()

        # Ask Zarinpal for an authority (min 1000 Toman).
        amount = max(plan.price_toman, 1000)
        async with httpx.AsyncClient(base_url=zarinpal._base_url(), timeout=30.0) as client:
            authority = await zarinpal.request_authority(
                client, amount, payment.description, user.phone_number, user.email
            )

        payment.authority = authority
        await session.commit()

        return StartPaymentResponse(
            paymentId=payment.id, subscriptionId=subscription.id, gatewayUrl=zarinpal.start_pay_url(authority)
        )

    # ── Callback (public) ───────────────────────────────────────────────────────

    async def handle_callback(
        self, session: AsyncSession, authority: str | None, status: str | None
    ) -> PaymentResultResponse:
        if not authority or not authority.strip():
            return _failed(None, "Missing authority")
        if (status or "").upper() != "OK":
            return await self._cancel(session, authority)

        # Eagerly load subscription (+plan) and plan for activation.
        stmt = (
            select(Payment)
            .options(
                selectinload(Payment.subscription).selectinload(Subscription.plan),
                selectinload(Payment.plan),
            )
            .where(Payment.authority == authority)
        )
        payment = (await session.execute(stmt)).scalar_one_or_none()
        if payment is None:
            return _failed(None, "Payment not found")

        # Idempotent: already finalised.
        if payment.status == PaymentStatus.Succeeded:
            return _ok(payment)

        async with httpx.AsyncClient(base_url=zarinpal._base_url(), timeout=30.0) as client:
            verified, code, ref_id, card_pan = await zarinpal.verify(client, payment.amount_toman, authority)

        if not verified:
            payment.status = PaymentStatus.Failed
            if payment.subscription and payment.subscription.status == SubscriptionStatus.PendingPayment:
                payment.subscription.status = SubscriptionStatus.Cancelled
            await session.commit()
            return _failed(payment.subscription_id, "Payment verification failed")

        payment.status = PaymentStatus.Succeeded
        payment.ref_id = ref_id
        payment.card_pan = card_pan
        payment.paid_at = utcnow()

        if payment.subscription:
            now = utcnow()
            # Latest active subscription end (extend from there).
            existing_end_stmt = (
                select(func.max(Subscription.end_at))
                .where(
                    Subscription.user_id == payment.user_id,
                    Subscription.status == SubscriptionStatus.Active,
                    Subscription.end_at > now,
                )
            )
            existing_end = (await session.execute(existing_end_stmt)).scalar_one_or_none() or now
            from datetime import timedelta

            plan = payment.plan
            if plan is None:
                plan = (
                    await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == payment.plan_id))
                ).scalar_one()
            payment.subscription.status = SubscriptionStatus.Active
            payment.subscription.start_at = existing_end
            payment.subscription.end_at = existing_end + timedelta(days=plan.duration_days)

        await session.commit()
        log.info("[Payment] succeeded payment=%s ref=%s", payment.id, ref_id)
        return _ok(payment)

    async def _cancel(self, session: AsyncSession, authority: str) -> PaymentResultResponse:
        stmt = (
            select(Payment)
            .options(selectinload(Payment.subscription))
            .where(Payment.authority == authority)
        )
        payment = (await session.execute(stmt)).scalar_one_or_none()
        if payment is None:
            return _failed(None, "Payment not found")
        if payment.status == PaymentStatus.Pending:
            payment.status = PaymentStatus.Cancelled
            if payment.subscription and payment.subscription.status == SubscriptionStatus.PendingPayment:
                payment.subscription.status = SubscriptionStatus.Cancelled
            await session.commit()
        return _failed(payment.subscription_id, "Payment cancelled")

    # ── History / admin views ───────────────────────────────────────────────────

    async def list_my_subscriptions(self, session: AsyncSession, user_id: str) -> list[SubscriptionResponse]:
        stmt = (
            select(Subscription)
            .options(selectinload(Subscription.plan), selectinload(Subscription.user))
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_sub(s) for s in rows]

    async def list_my_payments(self, session: AsyncSession, user_id: str) -> list[PaymentResponse]:
        stmt = (
            select(Payment)
            .options(selectinload(Payment.user))
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_pay(p) for p in rows]

    async def admin_stats(self, session: AsyncSession) -> dict:
        now = utcnow()
        users = (await session.execute(select(func.count(User.id)))).scalar_one()
        active_subs = (
            await session.execute(
                select(func.count(Subscription.id)).where(
                    Subscription.status == SubscriptionStatus.Active, Subscription.end_at > now
                )
            )
        ).scalar_one()
        from ...domain.models import University

        revenue = (
            await session.execute(
                select(func.coalesce(func.sum(Payment.amount_toman), 0)).where(
                    Payment.status == PaymentStatus.Succeeded
                )
            )
        ).scalar_one()
        universities = (await session.execute(select(func.count(University.id)))).scalar_one()

        recent_stmt = (
            select(Payment, User)
            .outerjoin(User, Payment.user_id == User.id)
            .order_by(Payment.created_at.desc())
            .limit(10)
        )
        recent_rows = (await session.execute(recent_stmt)).all()
        recent_payments = [
            {
                "id": p.id,
                "amountToman": p.amount_toman,
                "status": _enum_name(p.status),
                "refId": p.ref_id,
                "createdAt": p.created_at.isoformat() if p.created_at else None,
                "email": u.email if u else None,
                "phone": u.phone_number if u else None,
            }
            for p, u in recent_rows
        ]
        return {
            "users": users,
            "activeSubscriptions": active_subs,
            "revenueToman": revenue,
            "universities": universities,
            "recentPayments": recent_payments,
        }

    async def admin_list_payments(self, session: AsyncSession) -> list[PaymentResponse]:
        stmt = (
            select(Payment)
            .options(selectinload(Payment.user))
            .order_by(Payment.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_pay(p) for p in rows]

    # ── Admin subscriptions ────────────────────────────────────────────────────

    async def admin_list_subscriptions(
        self, session: AsyncSession, status: str | None, user_id: str | None
    ) -> list[SubscriptionResponse]:
        stmt = select(Subscription).options(
            selectinload(Subscription.plan), selectinload(Subscription.user)
        )
        if status:
            stmt = stmt.where(Subscription.status == _parse_subscription_status(status))
        if user_id:
            stmt = stmt.where(Subscription.user_id == user_id)
        stmt = stmt.order_by(Subscription.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_sub(s) for s in rows]

    async def admin_grant_subscription(
        self, session: AsyncSession, user_id: str, plan_id: str
    ) -> SubscriptionResponse:
        """Grant a subscription to a user (admin action): creates an Active
        subscription for the plan's duration — extending an existing active sub's
        window like the payment callback does — plus a Succeeded manual Payment
        row so the grant shows up in the transactions view."""
        from datetime import timedelta

        plan = await self._get_plan(session, plan_id)
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise AppException.not_found("User not found")
        if user.status != UserStatus.Active:
            raise AppException.bad_request("Cannot grant a subscription to a suspended user")

        now = utcnow()
        # Extend from the end of any currently-active subscription (callback parity).
        existing_end_stmt = (
            select(func.max(Subscription.end_at))
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.Active,
                Subscription.end_at > now,
            )
        )
        start = (await session.execute(existing_end_stmt)).scalar_one_or_none() or now

        subscription = Subscription(
            id=new_uuid_hex(),
            user_id=user_id,
            plan_id=plan.id,
            start_at=start,
            end_at=start + timedelta(days=plan.duration_days),
            status=SubscriptionStatus.Active,
        )
        payment = Payment(
            id=new_uuid_hex(),
            user_id=user_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            amount_toman=plan.price_toman,
            status=PaymentStatus.Succeeded,
            gateway="manual",
            description=f"Admin grant: {plan.name_key} ({plan.duration_days} days)",
            paid_at=now,
        )
        session.add(subscription)
        session.add(payment)
        await session.commit()

        loaded = (
            await session.execute(
                select(Subscription)
                .options(selectinload(Subscription.plan), selectinload(Subscription.user))
                .where(Subscription.id == subscription.id)
            )
        ).scalar_one()
        return _to_sub(loaded)

    async def admin_update_subscription_status(
        self, session: AsyncSession, id_: str, status: str
    ) -> SubscriptionResponse:
        new_status = _parse_subscription_status(status)
        sub = (
            await session.execute(select(Subscription).where(Subscription.id == id_))
        ).scalar_one_or_none()
        if sub is None:
            raise AppException.not_found("Subscription not found")
        sub.status = new_status
        await session.commit()
        loaded = (
            await session.execute(
                select(Subscription)
                .options(selectinload(Subscription.plan), selectinload(Subscription.user))
                .where(Subscription.id == id_)
            )
        ).scalar_one()
        return _to_sub(loaded)

    # ── helpers ─────────────────────────────────────────────────────────────────

    async def _get_plan(self, session: AsyncSession, id_: str) -> SubscriptionPlan:
        plan = (
            await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == id_))
        ).scalar_one_or_none()
        if plan is None:
            raise AppException.not_found("Plan not found")
        return plan


def _validate_plan(price_toman: int, duration_days: int, name_key: str) -> None:
    if not name_key or not name_key.strip():
        raise AppException.validation("name_key is required")
    if price_toman < 0:
        raise AppException.validation("price_toman must be non-negative")
    if duration_days <= 0:
        raise AppException.validation("duration_days must be positive")


def _enum_name(value) -> str:
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _parse_subscription_status(value: str) -> SubscriptionStatus:
    """Case-insensitive, snake-tolerant status parsing (Active / active /
    pending_payment / PendingPayment …)."""
    v = (value or "").strip().lower().replace("_", "")
    for s in SubscriptionStatus:
        if s.value.lower() == v:
            return s
    raise AppException.validation(f"Invalid status: {value}")


def _ok(p: Payment) -> PaymentResultResponse:
    plan_key = p.plan.name_key if p.plan else None
    return PaymentResultResponse(
        succeeded=True,
        subscriptionId=p.subscription_id,
        refId=p.ref_id,
        message="Payment successful",
        planNameKey=plan_key,
    )


def _failed(sub_id: str | None, msg: str) -> PaymentResultResponse:
    return PaymentResultResponse(succeeded=False, subscriptionId=sub_id, refId=None, message=msg, planNameKey=None)


def _to_plan(p: SubscriptionPlan) -> PlanResponse:
    return PlanResponse(
        id=p.id,
        nameKey=p.name_key,
        descriptionKey=p.description_key,
        priceToman=p.price_toman,
        durationDays=p.duration_days,
        isActive=p.is_active,
        sortOrder=p.sort_order,
        features=p.features,
        createdAt=p.created_at.isoformat() if p.created_at else None,
        updatedAt=p.updated_at.isoformat() if p.updated_at else None,
    )


def _to_sub(s: Subscription) -> SubscriptionResponse:
    plan = s.plan
    return SubscriptionResponse(
        id=s.id,
        planId=s.plan_id,
        planNameKey=plan.name_key if plan else "",
        planPriceToman=plan.price_toman if plan else 0,
        planDurationDays=plan.duration_days if plan else 0,
        status=_enum_name(s.status),
        startAt=s.start_at.isoformat() if s.start_at else None,
        endAt=s.end_at.isoformat() if s.end_at else None,
        createdAt=s.created_at.isoformat() if s.created_at else None,
        userId=s.user_id,
        userUsername=(s.user.username if s.user else None) or "",
        userEmail=(s.user.email if s.user else None) or "",
    )


def _to_pay(p: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=p.id,
        planId=p.plan_id,
        amountToman=p.amount_toman,
        status=_enum_name(p.status),
        authority=p.authority,
        refId=p.ref_id,
        cardPan=p.card_pan,
        paidAt=p.paid_at.isoformat() if p.paid_at else None,
        createdAt=p.created_at.isoformat() if p.created_at else None,
        userUsername=(p.user.username if p.user else None) or "",
        userEmail=(p.user.email if p.user else None) or "",
    )
