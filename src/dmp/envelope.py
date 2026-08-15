"""The standard `{ code, data, meta }` response envelope and AppException.

Mirrors Dmp.Domain.Common.ApiResponse / AppException exactly so the React frontend's
axios interceptor (which reads `r.data.data` and `meta.message`) keeps working.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class AppException(Exception):
    """Domain error translated into the `{ code, meta }` envelope with an HTTP status."""

    def __init__(self, code: str, message: str = "", status_code: int = 400, meta: Any = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        # Default meta is the message (the frontend reads meta.message).
        self.meta: Any = meta if meta is not None else ({"message": message} if message else None)
        super().__init__(message)

    # ── Factories matching the C# AppException static helpers ────────────────────
    @classmethod
    def not_found(cls, message: str = "Resource not found", meta: Any = None) -> AppException:
        return cls("NOT_FOUND", message, 404, meta)

    @classmethod
    def unauthorized(cls, message: str = "Unauthorized") -> AppException:
        return cls("UNAUTHORIZED", message, 401, {"message": message})

    @classmethod
    def forbidden(cls, message: str = "Forbidden") -> AppException:
        return cls("FORBIDDEN", message, 403, {"message": message})

    @classmethod
    def conflict(cls, message: str, meta: Any = None) -> AppException:
        return cls("CONFLICT", message, 409, meta)

    @classmethod
    def bad_request(cls, message: str, meta: Any = None) -> AppException:
        return cls("BAD_REQUEST", message, 400, meta)

    @classmethod
    def validation(cls, message: str, meta: Any = None) -> AppException:
        return cls("VALIDATION_ERROR", message, 422, meta)


class ApiResponse(BaseModel):
    """The wire shape: `{ code, data, meta }` with nulls omitted at the top level."""

    code: str = "SUCCESS"
    data: Any | None = None
    meta: Any | None = None


def ok(data: Any = None, meta: Any = None) -> dict:
    """Build a success envelope dict, omitting null fields (parity with WhenWritingNull)."""
    body: dict[str, Any] = {"code": "SUCCESS"}
    if data is not None:
        body["data"] = jsonable_encoder(data)
    if meta is not None:
        body["meta"] = jsonable_encoder(meta)
    return body


def error(code: str, meta: Any = None) -> dict:
    body: dict[str, Any] = {"code": code}
    if meta is not None:
        body["meta"] = jsonable_encoder(meta)
    return body


# ── Exception handlers (registered in main.py) ──────────────────────────────────


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error(exc.code, exc.meta))


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Mirror the AppException VALIDATION_ERROR shape.
    return JSONResponse(
        status_code=422,
        content=error("VALIDATION_ERROR", {"message": "Validation failed", "errors": exc.errors()}),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging

    logging.getLogger("dmp").exception("Unhandled exception")
    return JSONResponse(status_code=500, content=error("SERVER_ERROR", None))
