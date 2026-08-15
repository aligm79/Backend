"""Thin async client for the Zarinpal v4 gateway. Direct port of ZarinpalClient.cs.

Two-step purchase: request (get authority) → redirect to StartPay → verify on callback.
Amounts are integer Tomans (currency IRT). Sandbox host: sandbox.zarinpal.com;
production host: payment.zarinpal.com.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import get_settings

log = logging.getLogger("dmp.zarinpal")


def _base_url() -> str:
    settings = get_settings()
    return "https://sandbox.zarinpal.com" if settings.zarinpal_is_sandbox else "https://payment.zarinpal.com"


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> dict:
    """POST JSON. Zarinpal requires Accept: application/json to get JSON back."""
    resp = await client.post(path, json=body, headers={"Accept": "application/json"})
    text = resp.text
    try:
        data = resp.json()
    except Exception:
        log.error("[Zarinpal] non-JSON response from %s (status %s): %s", path, resp.status_code, text)
        raise RuntimeError(
            f"Zarinpal returned a non-JSON response from {path} (status {resp.status_code})."
        ) from None
    return data


def _has_errors(errors: Any) -> bool:
    if errors is None:
        return False
    if isinstance(errors, list):
        return len(errors) > 0
    return isinstance(errors, dict)


async def request_authority(
    client: httpx.AsyncClient,
    amount_toman: int,
    description: str,
    mobile: str | None,
    email: str | None,
) -> str:
    """POST /pg/v4/payment/request.json → returns the authority to redirect with."""
    settings = get_settings()
    body: dict[str, Any] = {
        "merchant_id": settings.zarinpal_merchant_id,
        "amount": amount_toman,
        "currency": "IRT",
        "callback_url": settings.zarinpal_callback_url,
        "description": description,
    }
    metadata: dict[str, str] = {}
    if mobile and mobile.strip():
        metadata["mobile"] = mobile.strip()
    if email and email.strip():
        metadata["email"] = email.strip()
    if metadata:
        body["metadata"] = metadata

    data = await _post(client, "/pg/v4/payment/request.json", body)
    envelope_data = data.get("data")
    errors = data.get("errors")
    if not envelope_data or _has_errors(errors):
        raise RuntimeError(f"Zarinpal request failed: {errors}")
    authority = envelope_data.get("authority")
    if not authority:
        raise RuntimeError("Zarinpal request returned no authority")
    return authority


async def verify(
    client: httpx.AsyncClient, amount_toman: int, authority: str
) -> tuple[bool, int, str | None, str | None]:
    """POST /pg/v4/payment/verify.json → (verified, code, ref_id, card_pan).

    code 100 = verified, 101 = already verified (idempotent success).
    """
    settings = get_settings()
    body = {"merchant_id": settings.zarinpal_merchant_id, "amount": amount_toman, "authority": authority}
    data = await _post(client, "/pg/v4/payment/verify.json", body)
    envelope_data = data.get("data") or {}
    code = envelope_data.get("code") or 0
    ok = code in (100, 101)
    if not ok:
        log.warning(
            "[Zarinpal] verify failed: code=%s message=%s errors=%s",
            code,
            envelope_data.get("message"),
            data.get("errors"),
        )
    ref_id = envelope_data.get("ref_id")
    ref_id = str(ref_id) if ref_id is not None else None
    return ok, code, ref_id, envelope_data.get("card_pan")


def start_pay_url(authority: str) -> str:
    return f"{_base_url()}/pg/StartPay/{authority}"
