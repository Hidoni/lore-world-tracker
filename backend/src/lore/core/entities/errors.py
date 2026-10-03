"""Errors of the entity service (``docs/architecture/api.md`` §3)."""

from lore.core.errors import ConflictError, InvalidInputError


class RevisionConflictError(ConflictError):
    """The PATCH was based on an older revision. ``context.current`` holds the current entity."""

    code = "revision_conflict"
    title = "Revision conflict"


class ParentNotAllowedError(InvalidInputError):
    """The parent breaks the parent rules (``data-model.md`` §3.4): kind not allowed, a cycle, a
    dimension mismatch, or a trashed/hidden parent."""

    code = "parent_not_allowed"
    title = "Parent not allowed"
