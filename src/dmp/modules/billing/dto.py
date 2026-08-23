"""Billing Pydantic DTOs (wire shapes match BillingDtos.cs, camelCase)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict


def _parse_jsonb(v: Any) -> dict | None:
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


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nameKey: str
    descriptionKey: str | None = None
    priceToman: int
    durationDays: int
    isActive: bool = True
    sortOrder: int = 0
    features: Any | None = None

    def parsed_features(self) -> dict | None:
        return _parse_jsonb(self.features)


class PlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nameKey: str | None = None
    descriptionKey: str | None = None
    priceToman: int | None = None
    durationDays: int | None = None
    isActive: bool | None = None
    sortOrder: int | None = None
    features: Any | None = None

    def parsed_features(self) -> dict | None:
        return _parse_jsonb(self.features)


class PlanResponse(BaseModel):
    id: str
    nameKey: str
    descriptionKey: str | None = None
    priceToman: int
    durationDays: int
    isActive: bool
    sortOrder: int
    features: dict | None = None
    createdAt: Any = None
    updatedAt: Any = None


class StartPaymentRequest(BaseModel):
    planId: str


class StartPaymentResponse(BaseModel):
    paymentId: str
    subscriptionId: str
    gatewayUrl: str


class PaymentResultResponse(BaseModel):
    succeeded: bool
    subscriptionId: str | None = None
    refId: str | None = None
    message: str
    planNameKey: str | None = None


class PaymentResponse(BaseModel):
    id: str
    planId: str
    amountToman: int
    status: str
    authority: str | None = None
    refId: str | None = None
    cardPan: str | None = None
    paidAt: Any = None
    createdAt: Any = None
    # Admin views join the paying user.
    userUsername: str | None = None
    userEmail: str | None = None


class SubscriptionResponse(BaseModel):
    id: str
    planId: str
    planNameKey: str = ""
    planPriceToman: int = 0
    planDurationDays: int = 0
    status: str
    startAt: Any = None
    endAt: Any = None
    createdAt: Any = None
    # Admin views join the owning user.
    userId: str | None = None
    userUsername: str | None = None
    userEmail: str | None = None


class GrantSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    userId: str
    planId: str


class SubscriptionStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
