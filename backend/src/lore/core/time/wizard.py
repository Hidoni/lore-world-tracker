"""The dimension wizard and calendar preview (``api.md`` §2, Time): a dimension, its prime
timeline and its first calendar in one transaction (one changeset)."""

from pathlib import Path
from typing import TYPE_CHECKING

from lore.chronology.schema import BaseUnit
from lore.core.entities.schemas import EntityCreate
from lore.core.entities.service import EntityService
from lore.core.errors import ErrorItem, InvalidInputError, LoreError, NotFoundError
from lore.core.time.calendars import (
    CalendarInvalidError,
    Preview,
    preview,
    source_definition,
)
from lore.core.time.dimensions import DIMENSION, dimension_row
from lore.core.time.resolve import Resolver
from lore.core.time.schemas import CalendarPreviewIn, DimensionCreated, DimensionWizardIn
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext


def _prefixed(error: LoreError, prefix: str) -> LoreError:
    """Errors about the calendar source, located under ``prefix`` in the request. Definition
    errors keep their JSON pointers."""
    if isinstance(error, CalendarInvalidError) or not error.errors:
        return error
    error.errors = [
        ErrorItem(path=f"{prefix}.{e['path']}", code=e["code"], message=e["message"])
        for e in error.errors
    ]
    return error


def create_dimension(
    context: VaultContext, data: DimensionWizardIn, spec_dir: Path | None
) -> DimensionCreated:
    entities = EntityService(context)
    try:
        definition = source_definition(data.calendar.source, spec_dir)
    except InvalidInputError as exc:
        raise _prefixed(exc, "calendar.source") from None
    dimension = entities.create(
        EntityCreate(
            kind=DIMENSION,
            name=data.name,
            summary=data.summary,
            visibility=data.visibility,
            ext=data.ext,
        )
    ).entity
    calendar = entities.create(
        EntityCreate(
            kind="calendar",
            name=data.calendar.name,
            summary=data.calendar.summary,
            dimension_id=dimension.id,
            ext={"definition": definition},
        )
    ).entity
    dimension_out = entities.get(dimension.id)  # with the default calendar set
    prime_id = str((dimension_out.ext or {})["prime_timeline_id"])
    return DimensionCreated(
        dimension=dimension_out, prime_timeline=entities.get(prime_id), calendar=calendar
    )


def preview_calendar(
    context: VaultContext,
    policy: VisibilityPolicy,
    data: CalendarPreviewIn,
    spec_dir: Path | None,
) -> Preview:
    if (data.dimension_id is None) == (data.time_spec is None):
        message = "Give exactly one of dimension_id and time_spec."
        raise InvalidInputError(
            message, errors=[ErrorItem(path="dimension_id", code="invalid_value", message=message)]
        )
    resolver: Resolver | None = None
    if data.dimension_id is not None:
        dimension = EntityService(context, policy).load_visible(data.dimension_id)
        if dimension.kind != DIMENSION:
            raise NotFoundError(f"No dimension {data.dimension_id}.")
        row = dimension_row(context.session, dimension.id)
        base_unit, duration = BaseUnit.model_validate(row.base_unit), row.duration
        resolver = Resolver(context, dimension.id, policy=policy)
    else:
        assert data.time_spec is not None
        base_unit, duration = data.time_spec.base_unit, int(data.time_spec.duration)
        if duration < 1:
            message = "The duration must be at least 1 base unit."
            raise InvalidInputError(
                message,
                errors=[
                    ErrorItem(path="time_spec.duration", code="invalid_value", message=message)
                ],
            )
    try:
        document = source_definition(data.source, spec_dir)
    except InvalidInputError as exc:
        raise _prefixed(exc, "source") from None
    return preview(document, base_unit, duration, data.calendar_id, resolver)
