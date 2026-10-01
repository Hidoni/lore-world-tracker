"""The one place where exceptions become RFC 9457 ``application/problem+json`` responses."""

import logging
import traceback
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from lore.core.errors import ErrorItem, LoreError

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_PREFIX = "urn:lore:problem:"
_FASTAPI_VALIDATION_REF = "#/components/schemas/HTTPValidationError"

# Codes for plain HTTP errors raised by the framework (routing, method mismatch, ...).
_HTTP_STATUS_CODES = {
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
}


class ProblemErrorItem(BaseModel):
    path: str
    code: str
    message: str


class Problem(BaseModel):
    """Body of every error response."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    errors: list[ProblemErrorItem] | None = None
    context: dict[str, Any] | None = None


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": Problem, "description": "Problem"},
}


def use_problem_media_type(openapi: dict[str, Any]) -> dict[str, Any]:
    """Declare ``default`` (problem) responses as ``application/problem+json``.

    FastAPI documents ``responses`` models under the route's media type (``application/json``)
    and adds its own ``422 HTTPValidationError`` response, which this app never returns
    (validation errors are problems too), so that one is removed.
    """
    for operations in openapi.get("paths", {}).values():
        for operation in operations.values():
            responses = operation.get("responses", {})
            if _FASTAPI_VALIDATION_REF in str(responses.get("422", "")):
                del responses["422"]
            content = responses.get("default", {}).get("content")
            if content is not None and "application/json" in content:
                content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
    schemas = openapi.get("components", {}).get("schemas", {})
    if _FASTAPI_VALIDATION_REF not in str(openapi.get("paths", {})):
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
    return openapi


def problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[ErrorItem] | None = None,
    context: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    problem = Problem(
        type=PROBLEM_TYPE_PREFIX + code,
        title=title,
        status=status,
        detail=detail,
        code=code,
        errors=[ProblemErrorItem(**item) for item in errors] if errors is not None else None,
        context=context,
    )
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def _location_to_path(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in loc)


def _handle_lore_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LoreError)
    return problem_response(
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
        context=exc.context,
    )


def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors: list[ErrorItem] = [
        {
            "path": _location_to_path(tuple(error["loc"])),
            "code": str(error["type"]),
            "message": str(error["msg"]),
        }
        for error in exc.errors()
    ]
    return problem_response(
        status=422,
        code="validation_error",
        title="Validation error",
        detail="The request is invalid.",
        errors=errors,
    )


def _handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    phrase = HTTPStatus(exc.status_code).phrase
    return problem_response(
        status=exc.status_code,
        code=_HTTP_STATUS_CODES.get(exc.status_code, f"http_{exc.status_code}"),
        title=phrase,
        detail=exc.detail if isinstance(exc.detail, str) else phrase,
        headers=exc.headers,
    )


def internal_error_response(exc: BaseException, *, debug: bool = False) -> JSONResponse:
    """The ``internal_error`` problem. The traceback is included only with ``LORE_DEBUG=true``.

    Unexpected exceptions are caught by ``RequestContextMiddleware`` (inside the request context,
    so the response still carries the request id and security headers) and rendered here.
    """
    logger.error("unhandled exception", exc_info=exc)
    context = None
    if debug:
        context = {
            "exception": type(exc).__qualname__,
            "traceback": traceback.format_exception(exc),
        }
    return problem_response(
        status=500,
        code="internal_error",
        title="Internal error",
        detail="An unexpected error occurred.",
        context=context,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LoreError, _handle_lore_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
