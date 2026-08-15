"""Subscription gate: the single source of truth for "does this user have access?".

Lives in the billing module (parity with Dmp.Domain.Common.SubscriptionGate). Catalog
imports this helper so it never needs a hard dependency on billing services.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import utcnow
from ...domain.enums import SubscriptionStatus
from ...domain.models import Subscription


async def has_active_subscription(session: AsyncSession, user_id: str) -> bool:
    now = utcnow()
    stmt = select(Subscription.id).where(
        Subscription.user_id == user_id,
        Subscription.status == SubscriptionStatus.Active,
        Subscription.end_at > now,
    )
    return (await session.execute(stmt)).first() is not None


async def get_active_subscription(session: AsyncSession, user_id: str) -> Subscription | None:
    now = utcnow()
    stmt = (
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.Active,
            Subscription.end_at > now,
        )
        .order_by(Subscription.end_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
