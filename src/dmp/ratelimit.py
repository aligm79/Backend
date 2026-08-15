"""Rate limiting via slowapi.

Two policies, matching RateLimitingSetup.cs:
  - global default: per-IP token bucket, 100 tokens, 20/sec replenish
  - "auth": per-IP fixed window, 10 req/min — applied to login/register/OTP endpoints
On 429 we emit the standard `{ code: "RATE_LIMITED", meta }` envelope.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .envelope import error


def _client_ip(request) -> str:  # honour a single-hop X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, default_limits=["100 per second"])

# A dedicated limiter for the strict auth policy. Applied per-route via decorator.
auth_limiter = Limiter(key_func=_client_ip)


async def rate_limit_handler(request, exc: RateLimitExceeded):  # type: ignore[no-untyped-def]
    from fastapi.responses import JSONResponse

    retry_after = getattr(exc, "retry_after", None)
    meta = {
        "message": "Too many requests. Please slow down.",
        "retryAfterSeconds": retry_after if retry_after is not None else None,
    }
    return JSONResponse(status_code=429, content=error("RATE_LIMITED", meta))
