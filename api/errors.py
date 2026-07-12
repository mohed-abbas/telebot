"""api/errors.py — enveloped-error exception handler for /api/v2 (Phase 08 Plan 01).

Failure shape (T-08-02, V13 — no raw detail/traceback leakage):

    {"error": {"code": "<machine-code>", "message": "<human-readable>",
               "fields": {...}}}   # `fields` only present for validation errors

Success responses stay BARE (the resource itself), never wrapped — only failures
carry the envelope (RESEARCH error-envelope recommendation, adopted).

`register_error_handlers(app)` is called once from dashboard.py wiring (Task 2)
and installs handlers for HTTPException and RequestValidationError so that the
existing HTML routes are unaffected (these handlers only reshape responses on the
/api/v2 prefix; other paths fall back to FastAPI defaults).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Map common HTTP status codes to stable machine codes the SPA can branch on.
_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def _is_api_v2(request: Request) -> bool:
    """Only reshape responses for the JSON API surface; HTML routes untouched."""
    return request.url.path.startswith("/api/v2")


def _envelope(code: str, message: str, fields: dict | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if fields is not None:
        err["fields"] = fields
    return {"error": err}


async def _http_exception_handler(request: Request, exc: HTTPException):
    """Reshape HTTPException into the enveloped failure shape for /api/v2."""
    if not _is_api_v2(request):
        # Preserve default behaviour for legacy HTML / HTMX routes.
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )
    code = _STATUS_CODES.get(exc.status_code, "error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message),
        headers=getattr(exc, "headers", None),
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """Reshape Pydantic/request validation errors into the envelope with `fields`."""
    if not _is_api_v2(request):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    fields: dict = {}
    for err in exc.errors():
        # loc is a tuple like ("body", "close_volume"); use the last meaningful key.
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        key = loc[-1] if loc else "_"
        fields[key] = err.get("msg", "invalid")
    return JSONResponse(
        status_code=422,
        content=_envelope("validation_error", "Validation failed", fields=fields),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so an unexpected error still returns the envelope, not a bare 500.

    The specific HTTPException / RequestValidationError handlers take precedence
    (FastAPI dispatches by the most specific registered type), so this only fires
    for genuinely unhandled exceptions. Never leaks the traceback/detail (V13).
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    if not _is_api_v2(request):
        # Preserve default behaviour for legacy HTML / HTMX routes.
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    return JSONResponse(
        status_code=500,
        content=_envelope("error", "Internal server error"),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install the enveloped-error handlers. Called once from dashboard.py wiring."""
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
