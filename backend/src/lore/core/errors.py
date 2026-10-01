"""Typed application errors.

Services and routers raise these; ``lore.core.api.errors`` maps them to RFC 9457
``application/problem+json`` responses in one place. ``code`` values are stable machine
identifiers (``docs/architecture/api.md`` §3).
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, TypedDict


class ErrorItem(TypedDict):
    """One entry of a problem's ``errors`` list."""

    path: str
    code: str
    message: str


class LoreError(Exception):
    """Base class of every error that is reported to API clients as a problem."""

    code: ClassVar[str] = "internal_error"
    status: ClassVar[int] = 500
    title: ClassVar[str] = "Internal error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: Sequence[ErrorItem] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.detail = detail or self.title
        self.errors = list(errors) if errors is not None else None
        self.context = dict(context) if context is not None else None
        super().__init__(self.detail)


class NotFoundError(LoreError):
    code = "not_found"
    status = 404
    title = "Not found"


class InvalidInputError(LoreError):
    code = "validation_error"
    status = 422
    title = "Validation error"


class ConflictError(LoreError):
    code = "conflict"
    status = 409
    title = "Conflict"


class ForbiddenError(LoreError):
    code = "forbidden"
    status = 403
    title = "Forbidden"
