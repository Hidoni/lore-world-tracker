"""Dates in and out of the MCP tools (``docs/architecture/mcp.md`` §5, Dates).

In: a moment (decimal string), ``present``, or a calendar date ``{calendar, fields}``: the
calendar by id or name, fields as in anchors (strings: numbers, or slot ids; slot names are
accepted too), resolved by the time core exactly as ``POST /time/resolve`` resolves a calendar
anchor at the precision of its finest field. Out: every moment with its date in the dimension's
default calendar (Absolute without one), as ``POST /time/convert`` formats it.
"""

from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from lore.chronology.calendar import CompiledCalendar, DateError, format_absolute, format_date
from lore.chronology.calendar.compiled import is_number
from lore.chronology.schema import CalendarAnchor, TimePoint
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, InvalidInputError, NotFoundError
from lore.core.modules.spec import VaultContext
from lore.core.time.calendars import CALENDAR, AbsoluteLens, lens
from lore.core.time.models import Calendar, Dimension
from lore.core.time.resolve import BASE, Resolver
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID
from lore.core.visibility import VisibilityPolicy

PRESENT = "present"

Moment = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9][0-9]*|present)$", max_length=1000),
    Field(description='A moment (base units since the dimension\'s inception), or "present".'),
]


class CalendarDate(BaseModel):
    """A date in a calendar, as anchors store it."""

    model_config = ConfigDict(extra="forbid")

    calendar: Annotated[str, Field(min_length=1, max_length=200)] = Field(
        description="The calendar's id or name."
    )
    fields: dict[str, str | int] = Field(
        min_length=1,
        max_length=20,
        description='Level id -> value, from the top level down (e.g. {"year": "1022", '
        '"month": "frostmoon", "day": "3"}): numbers, or named units by slot id or name. The '
        "finest level given is the date's precision.",
    )
    era: str | None = Field(default=None, description="An era id: the year counts in it.")


type DateIn = Moment | CalendarDate


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(
        message, errors=[{"path": path, "code": "invalid_date", "message": message}]
    )


@dataclass(frozen=True)
class Resolved:
    t: int
    dimension_id: str | None  # None: a moment given without a dimension


@dataclass
class Dates:
    """Date input and output of one tool call."""

    context: VaultContext
    policy: VisibilityPolicy
    _lenses: dict[str, CompiledCalendar | AbsoluteLens] = field(default_factory=dict)

    # --- in -------------------------------------------------------------------------------------

    def resolve(self, value: DateIn, *, dimension_id: str | None, path: str) -> Resolved:
        """A date argument as a moment (``422 validation_error`` when it isn't one)."""
        if isinstance(value, CalendarDate):
            return self._calendar_date(value, dimension_id, path)
        if value == PRESENT:
            if dimension_id is None:
                raise _invalid(path, '"present" needs a dimension (or a timeline).')
            present = self.context.session.scalar(
                select(Dimension.present_t).where(Dimension.entity_id == dimension_id)
            )
            if present is None:
                raise _invalid(path, "The dimension has no present moment.")
            return Resolved(present, dimension_id)
        return Resolved(int(value), dimension_id)

    def calendar(self, name: str, dimension_id: str | None) -> Calendar:
        """A calendar the policy shows, by id or (case-insensitive) name."""
        session = self.context.session
        statement = (
            select(Calendar)
            .join(Entity, Entity.id == Calendar.entity_id)
            .where(
                Entity.kind == CALENDAR,
                Entity.deleted_at.is_(None),
                *self.policy.entities(Entity),
            )
        )
        if dimension_id is not None:
            statement = statement.where(Calendar.dimension_id == dimension_id)
        by_id = session.scalars(statement.where(Entity.id == name)).first()
        if by_id is not None:
            return by_id
        found = list(
            session.scalars(statement.where(func.lower(Entity.name) == name.lower()).limit(2))
        )
        if not found:
            raise NotFoundError(f"No calendar {name!r}.")
        if len(found) > 1:
            raise ConflictError(f"Several calendars are named {name!r}: pass its id.")
        return found[0]

    def _calendar_date(self, value: CalendarDate, dimension_id: str | None, path: str) -> Resolved:
        row = self.calendar(value.calendar, dimension_id)
        try:
            compiled = lens(self.context, row.dimension_id, row.entity_id)
        except ConflictError as error:
            raise _invalid(path, f"The calendar doesn't compile: {error.detail}") from None
        assert isinstance(compiled, CompiledCalendar)
        fields = self._fields(compiled, value.fields, path)
        present = [level for level in compiled.levels if level in fields]
        try:
            point = TimePoint.model_validate(
                {
                    "anchor": CalendarAnchor(
                        kind="calendar", calendar_id=row.entity_id, fields=fields, era=value.era
                    ).model_dump(mode="json", exclude_none=True),
                    "precision": present[0],
                }
            )
        except ValueError as error:
            raise _invalid(path, str(error)) from None
        resolver = Resolver(self.context, row.dimension_id, policy=self.policy)
        resolution = resolver.resolve(point)
        if resolution.t is None or resolution.problem is not None:
            message = resolution.problem.message if resolution.problem else "Not a date."
            raise _invalid(path, message)
        return Resolved(resolution.t, row.dimension_id)

    @staticmethod
    def _fields(
        calendar: CompiledCalendar, given: dict[str, str | int], path: str
    ) -> dict[str, str]:
        """Field values as anchors store them: named units given by name become slot ids."""
        unknown = sorted(set(given) - set(calendar.levels))
        if unknown:
            levels = ", ".join(reversed(calendar.levels))
            raise _invalid(path, f"Unknown levels {unknown}: the calendar's are {levels}.")
        out: dict[str, str] = {}
        for level, raw in given.items():
            value = str(raw).strip()
            if not is_number(value):
                value = _slot_id(calendar, calendar.level_index(level), value)
            out[level] = value
        return out

    # --- out ------------------------------------------------------------------------------------

    def lens_of(self, dimension_id: str) -> CompiledCalendar | AbsoluteLens:
        """The dimension's default calendar if the policy shows it and it compiles, else
        Absolute."""
        if dimension_id not in self._lenses:
            default = self.context.session.scalar(
                select(Dimension.default_calendar_id).where(Dimension.entity_id == dimension_id)
            )
            chosen: CompiledCalendar | AbsoluteLens | None = None
            if default is not None and self.policy.visible_ids(self.context.session, [default]):
                try:
                    chosen = lens(self.context, dimension_id, default)
                except ConflictError, NotFoundError:
                    chosen = None
            self._lenses[dimension_id] = chosen or lens(
                self.context, dimension_id, ABSOLUTE_CALENDAR_ID
            )
        return self._lenses[dimension_id]

    def text(
        self,
        dimension_id: str | None,
        t: int | None,
        precision: str | None = None,
        *,
        approximate: bool = False,
    ) -> str | None:
        """``t`` in the dimension's default calendar, at ``precision`` when the calendar has it
        (else its finest level)."""
        if dimension_id is None or t is None:
            return None
        calendar = self.lens_of(dimension_id)
        if isinstance(calendar, AbsoluteLens):
            return format_absolute(t, calendar.base_unit, approximate=approximate)
        level = precision if precision in calendar.levels or precision == BASE else None
        try:
            return format_date(calendar, t, level or calendar.levels[0], approximate=approximate)
        except DateError:
            return None

    def moment(
        self,
        dimension_id: str | None,
        t: int | None,
        precision: str | None = None,
        *,
        approximate: bool = False,
    ) -> dict[str, Any] | None:
        """A moment in a result: ``{t, date}``."""
        if t is None:
            return None
        date = self.text(dimension_id, t, precision, approximate=approximate)
        return {"t": str(t), "date": date}


def _slot_id(calendar: CompiledCalendar, level: int, value: str) -> str:
    """The slot id of the named unit at ``level`` whose id, name or abbreviation is ``value``
    (case-insensitive); ``value`` itself when none is (the engine then says what is wrong)."""
    wanted = value.casefold()
    for regime in calendar.regimes:
        for template in regime.templates.values():
            if template.level != level + 1:
                continue
            for segment in template.segments:
                if segment.slot_id is None:
                    continue
                names = (segment.slot_id, segment.name, segment.abbr)
                if any(name is not None and name.casefold() == wanted for name in names):
                    return segment.slot_id
    return value
