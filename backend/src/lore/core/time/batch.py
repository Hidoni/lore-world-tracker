"""The batch time routes (``docs/architecture/api.md`` §2, Time): ``POST /time/resolve`` (time
points and end specs → moments, extents, statuses and displays, for pickers) and
``POST /time/convert`` (moments → fields and displays in given calendars, for non-TS clients).

Problems are reported per item (``error``), so one bad date doesn't fail the batch. The dimension
and the calendars named in the request must be visible (``404`` otherwise); time points resolve
only through records the request may see (``lore.core.time.resolve``).
"""

from typing import TYPE_CHECKING

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    format_absolute,
    format_date,
    to_fields,
    unit_bounds,
)
from lore.core.errors import NotFoundError
from lore.core.time.calendars import AbsoluteLens, lens
from lore.core.time.dimensions import DIMENSION
from lore.core.time.resolve import BASE, Resolution, Resolver
from lore.core.time.schemas import (
    ConvertIn,
    ConvertItem,
    ConvertOut,
    ConvertResult,
    Extent,
    ResolvedPoint,
    ResolveIn,
    ResolveItem,
    ResolveOut,
    TimeProblem,
)
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

type Lens = CompiledCalendar | AbsoluteLens


def _dimension(context: VaultContext, policy: VisibilityPolicy, dimension_id: str) -> None:
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    if EntityService(context, policy).load_visible(dimension_id).kind != DIMENSION:
        raise NotFoundError(f"No dimension {dimension_id}.")


def _lens(
    context: VaultContext, policy: VisibilityPolicy, dimension_id: str, calendar_id: str
) -> Lens:
    if calendar_id != ABSOLUTE_CALENDAR_ID and not policy.visible_ids(
        context.session, [calendar_id]
    ):
        raise NotFoundError(f"No calendar {calendar_id} in this dimension.")
    return lens(context, dimension_id, calendar_id)


def display_level(calendar: CompiledCalendar, resolution: Resolution) -> str:
    """The level to display a resolution at in a calendar: its precision if the calendar has it,
    else the coarsest level whose unit (at ``t``) fits in the extent (the finest level if none
    does)."""
    if resolution.precision in calendar.levels or resolution.precision == BASE:
        return resolution.precision
    assert resolution.t is not None
    assert resolution.extent is not None
    width = resolution.extent[1] - resolution.extent[0]
    chosen = calendar.levels[0]
    for level in calendar.levels:
        bounds = unit_bounds(calendar, resolution.t, level)
        if bounds.end - bounds.start > width:
            break
        chosen = level
    return chosen


def display(lens_: Lens, resolution: Resolution) -> str | None:
    """A resolution formatted in a calendar (``None`` when it has no moment, or the calendar
    can't show it)."""
    if resolution.t is None or resolution.extent is None:
        return None
    if isinstance(lens_, AbsoluteLens):
        return format_absolute(resolution.t, lens_.base_unit, approximate=resolution.approximate)
    try:
        level = display_level(lens_, resolution)
        return format_date(lens_, resolution.t, level, approximate=resolution.approximate)
    except DateError:
        return None


def _point(resolution: Resolution, lens_: Lens | None) -> ResolvedPoint:
    problem = resolution.problem
    return ResolvedPoint(
        t=resolution.t,
        status=resolution.status,
        extent=None
        if resolution.extent is None
        else Extent(lo=resolution.extent[0], hi=resolution.extent[1]),
        precision=resolution.precision if resolution.t is not None else None,
        approximate=resolution.approximate,
        display=None if lens_ is None else display(lens_, resolution),
        error=None
        if problem is None
        else TimeProblem(code=problem.code, message=problem.message, path=problem.path),
    )


def resolve_batch(context: VaultContext, policy: VisibilityPolicy, body: ResolveIn) -> ResolveOut:
    _dimension(context, policy, body.dimension_id)
    resolver = Resolver(context, body.dimension_id, body.timeline_id, policy)
    calendar_id = body.calendar_id or resolver.default_calendar_id or ABSOLUTE_CALENDAR_ID
    lens_ = _lens(context, policy, body.dimension_id, calendar_id)
    items: list[ResolveItem] = []
    for item in body.items:
        start = resolver.resolve(item.time_point)
        end = None
        if item.end is not None:
            resolved_end = resolver.resolve_end(item.end, start)
            end = _point(resolved_end, lens_)
            if item.end.kind == "unknown":
                end.display = "?"
        items.append(ResolveItem(start=_point(start, lens_), end=end))
    return ResolveOut(calendar_id=calendar_id, items=items)


def convert_batch(context: VaultContext, policy: VisibilityPolicy, body: ConvertIn) -> ConvertOut:
    _dimension(context, policy, body.dimension_id)
    resolver = Resolver(context, body.dimension_id, policy=policy)
    lenses = [_lens(context, policy, body.dimension_id, c) for c in body.calendars]
    items: list[ConvertItem] = []
    for t in body.moments:
        results: list[ConvertResult] = []
        for calendar_id, lens_ in zip(body.calendars, lenses, strict=True):
            results.append(_convert(t, calendar_id, lens_, body.precision, resolver.duration))
        items.append(ConvertItem(t=t, results=results))
    return ConvertOut(items=items)


def _convert(
    t: int, calendar_id: str, lens_: Lens, precision: str | None, duration: int
) -> ConvertResult:
    if t > duration:
        message = "The moment lies after the end of the dimension."
        return ConvertResult(
            calendar_id=calendar_id,
            error=TimeProblem(code="out_of_bounds", message=message, path="moments"),
        )
    if isinstance(lens_, AbsoluteLens):
        return ConvertResult(calendar_id=calendar_id, display=format_absolute(t, lens_.base_unit))
    level = precision or lens_.levels[0]
    if level != BASE and level not in lens_.levels:
        message = f"Unknown precision {level!r}."
        return ConvertResult(
            calendar_id=calendar_id,
            error=TimeProblem(code="invalid_date", message=message, path="precision"),
        )
    try:
        return ConvertResult(
            calendar_id=calendar_id,
            fields=to_fields(lens_, t).as_json(),
            display=format_date(lens_, t, level),
        )
    except DateError as error:
        return ConvertResult(
            calendar_id=calendar_id,
            error=TimeProblem(code="invalid_date", message=str(error), path="moments"),
        )
