"""Calendars as entities of a dimension (``chronology-engine.md`` §3-§4, §13; ``time-model.md`` §3;
R-CAL-1, R-CAL-9, R-CAL-12).

A calendar's ``ext`` is ``{definition}``. Writes validate the definition with the Python engine in
the dimension's context (base unit, ``D``) and store it with ``resolved_anchors`` (JSON pointer →
moment) and the compile status. Rules (decided 2026-10-05 where noted):

- Non-local anchors inside definitions may be absolute, calendar (another calendar of the
  dimension) or relative anchors; they resolve in the dimension (``anchor.<problem code>``, e.g.
  ``anchor.invalid_date``, ``anchor.unresolved_ref``) and must lie within ``[0, D]``
  (``anchor.out_of_bounds``). Anchoring to the calendar itself is ``anchor.self_reference`` (use a
  ``local`` anchor). Without a dimension (the wizard's preview) only absolute anchors resolve
  (``anchor.not_supported``). Invalid definitions answer ``422 calendar_invalid``;
  ``errors[].path`` are JSON pointers into the definition. A calendar is a node of the dependency
  graph (``lore.core.time.propagate``): it depends on its anchor slots, and propagation compiles it
  again when they move.
- The definition can be edited directly only while nothing depends on the calendar (no time slot
  and no recurring series, whose occurrences it places); otherwise
  ``409 conflict`` points to the proposals flow (#54).
- The first calendar of a dimension becomes its default (decided). The default calendar can't be
  trashed or purged while it's the default (``409``), unless it's the dimension's only calendar:
  then trashing keeps the default (trashed calendars still resolve) and purging clears it.
- Purging a calendar freezes what depends on it (``time-model.md`` §7.3).
- The virtual ``absolute`` calendar (``time-model.md`` §3) is accepted wherever a calendar is
  referenced for display or input (:func:`lens`), and is never stored.

Compiled calendars come from a process-wide LRU cache (``lore.core.time.cache``).
"""

import copy
import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lore.chronology.calendar import (
    CompiledCalendar,
    DateError,
    compile_calendar,
    format_absolute,
    format_date,
    to_fields,
    unit_bounds,
    validate_calendar,
)
from lore.chronology.presets import PresetError, instantiate_preset, load_presets
from lore.chronology.schema import (
    BaseUnit,
    CalendarAnchor,
    CalendarDefinition,
    CalendarDuration,
    CompileContext,
    MomentStr,
    Preset,
    Rational,
    RelativeAnchor,
    TimePoint,
)
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.time.cache import CALENDARS
from lore.core.time.dependencies import (
    CalendarNode,
    DependencyIndex,
)
from lore.core.time.models import Calendar, Dimension
from lore.core.time.resolve import Resolver
from lore.core.time.slots import SlotKey, SlotMoment, SlotUpdate, SlotValue, SpecUpdate
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID, dump_spec, parse_time_point
from lore.core.time.status import TimeStatus
from lore.core.visibility import VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext
    from lore.core.time.propagate import TimeWriter

CALENDAR = "calendar"
SAMPLE_YEARS = 5


class CalendarInvalidError(InvalidInputError):
    """A calendar definition the engine (or the server's anchor rules) rejects."""

    code = "calendar_invalid"
    title = "Invalid calendar definition"


class PresetIncompatibleError(InvalidInputError):
    code = "preset_incompatible"
    title = "Preset incompatible with the base unit"


# --- definition sources -------------------------------------------------------------------------


class PresetChoice(BaseModel):
    """A preset instantiated for a dimension (``chronology-engine.md`` §13)."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=64)]
    seconds_per_base_unit: Rational = Field(
        default=Rational(num="1", den="1"), description="How long one base unit lasts (> 0)."
    )
    origin: MomentStr = Field(
        default="0", description="The moment at which the preset's alignment unit starts."
    )


class CalendarSource(BaseModel):
    """Exactly one of ``definition`` (a full definition) and ``preset``."""

    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any] | None = None
    preset: PresetChoice | None = None


@cache
def _presets(spec_dir: Path) -> dict[str, Preset]:
    return load_presets(spec_dir)


def presets(spec_dir: Path | None) -> list[Preset]:
    """The preset catalog (``LORE_SPEC_DIR``); empty without a spec directory."""
    return [] if spec_dir is None else list(_presets(spec_dir).values())


def source_definition(source: CalendarSource, spec_dir: Path | None) -> dict[str, Any]:
    """The definition document a source stands for (a preset is instantiated)."""
    if (source.definition is None) == (source.preset is None):
        message = "Give exactly one of definition and preset."
        raise InvalidInputError(
            message, errors=[ErrorItem(path="source", code="invalid_value", message=message)]
        )
    if source.definition is not None:
        return source.definition
    assert source.preset is not None
    choice = source.preset
    preset = {p.id: p for p in presets(spec_dir)}.get(choice.id)
    if preset is None:
        message = f"Unknown preset {choice.id!r}."
        raise InvalidInputError(
            message, errors=[ErrorItem(path="preset.id", code="invalid_value", message=message)]
        )
    seconds = Fraction(int(choice.seconds_per_base_unit.num), int(choice.seconds_per_base_unit.den))
    try:
        definition = instantiate_preset(preset, seconds, origin=int(choice.origin))
    except PresetError as exc:
        raise PresetIncompatibleError(
            str(exc),
            errors=[
                ErrorItem(path="preset.seconds_per_base_unit", code=exc.code, message=str(exc))
            ],
        ) from exc
    return definition.model_dump(mode="json", by_alias=True, exclude_unset=True)


# --- validation ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class AnchorSlot:
    """A non-local-capable time point of a definition: its slot name and JSON pointer."""

    slot: str
    pointer: str
    point: Mapping[str, Any]


def anchor_slots(document: Mapping[str, Any]) -> Iterator[AnchorSlot]:
    """The definition's time points as calendar slots (``time-model.md`` §6):
    ``alignment:<regime>``, ``regime:<regime>`` (its start), ``era:<era>`` and
    ``overlay:<overlay>`` (its epoch)."""
    for i, regime in enumerate(document.get("regimes", [])):
        yield AnchorSlot(f"alignment:{regime['id']}", f"/regimes/{i}/alignment/at",
                         regime["alignment"]["at"])  # fmt: skip
        if regime.get("starts_at") is not None:
            yield AnchorSlot(f"regime:{regime['id']}", f"/regimes/{i}/starts_at",
                             regime["starts_at"])  # fmt: skip
    for i, era in enumerate(document.get("eras", [])):
        if era.get("start") is not None:
            yield AnchorSlot(f"era:{era['id']}", f"/eras/{i}/start", era["start"])
    for i, overlay in enumerate(document.get("overlays", [])):
        yield AnchorSlot(f"overlay:{overlay['id']}", f"/overlays/{i}/epoch", overlay["epoch"])


@dataclass(frozen=True)
class Compiled:
    definition: dict[str, Any]  # canonical document (members as sent)
    resolved: dict[str, str]
    calendar: CompiledCalendar


def _error(code: str, path: str, message: str) -> ErrorItem:
    return ErrorItem(path=path, code=code, message=message)


def _invalid(errors: list[ErrorItem]) -> CalendarInvalidError:
    count = f"{len(errors)} problem" + ("" if len(errors) == 1 else "s")
    return CalendarInvalidError(f"The calendar definition is invalid ({count}).", errors=errors)


def compile_document(
    document: Any,
    base_unit: BaseUnit,
    duration: int,
    calendar_id: str | None,
    resolver: Resolver | None = None,
) -> Compiled:
    """Validate and compile a definition document for a dimension; ``CalendarInvalidError``
    lists every problem (JSON pointers into the definition). ``resolver`` resolves non-absolute
    anchors (without one, they are ``anchor.not_supported``)."""
    context: dict[str, Any] = {
        "calendar_id": calendar_id,
        "base_unit": base_unit.model_dump(),
        "dimension_duration": str(duration),
    }
    try:
        definition = CalendarDefinition.model_validate(document)
    except PydanticValidationError:
        result = validate_calendar(document, context)  # the engine locates schema errors
        assert isinstance(result, list)
        raise _invalid([_error(e.code, e.path, e.message) for e in result]) from None
    canonical = definition.model_dump(mode="json", by_alias=True, exclude_unset=True)
    resolved: dict[str, str] = {}
    errors: list[ErrorItem] = []
    for anchor in anchor_slots(canonical):
        kind = anchor.point["anchor"]["kind"]
        if kind == "local":
            continue
        if kind == "absolute":
            t = int(anchor.point["anchor"]["t"])
            if t > duration:
                message = "The moment lies after the end of the dimension."
                errors.append(_error("anchor.out_of_bounds", f"{anchor.pointer}/anchor/t", message))
            resolved[anchor.pointer] = str(t)
            continue
        found = _resolve_anchor(anchor, calendar_id, resolver)
        if isinstance(found, dict):
            errors.append(found)
        else:
            resolved[anchor.pointer] = str(found)
    if errors:
        raise _invalid(errors)
    result = compile_calendar(
        definition, CompileContext.model_validate({**context, "resolved": resolved})
    )
    if isinstance(result, list):
        raise _invalid([_error(e.code, e.path, e.message) for e in result if e.severity == "error"])
    return Compiled(canonical, resolved, result)


def _references(point: TimePoint, calendar_id: str) -> bool:
    """Whether a time point names a calendar (its anchor's or its offset's)."""
    anchor = point.anchor
    if isinstance(anchor, CalendarAnchor):
        return anchor.calendar_id == calendar_id
    if isinstance(anchor, RelativeAnchor) and isinstance(anchor.offset, CalendarDuration):
        return anchor.offset.calendar_id == calendar_id
    return False


def resolvable(point: TimePoint) -> TimePoint:
    """A definition anchor as it resolves: a precision only shapes the moment of a calendar
    anchor; on absolute and relative anchors it may name a level of the calendar being defined,
    so they resolve at ``base``."""
    if isinstance(point.anchor, CalendarAnchor) or point.precision == "base":
        return point
    return point.model_copy(update={"precision": "base"})


def _pointer(base: str, dotted: str) -> str:
    """A resolution problem's dotted path, as a JSON pointer under ``base``."""
    return base + "".join(f"/{part}" for part in dotted.split(".") if part)


def _resolve_anchor(
    anchor: AnchorSlot, calendar_id: str | None, resolver: Resolver | None
) -> int | ErrorItem:
    """The moment of a non-local, non-absolute definition anchor (or the problem)."""
    kind_path = f"{anchor.pointer}/anchor/kind"
    if resolver is None:
        message = "Only absolute (or local) anchors resolve before the dimension exists."
        return _error("anchor.not_supported", kind_path, message)
    point = parse_time_point(dict(anchor.point))
    if calendar_id is not None and _references(point, calendar_id):
        message = "An anchor can't use the calendar it defines: use a local anchor."
        return _error("anchor.self_reference", kind_path, message)
    result = resolver.resolve(resolvable(point))
    if result.ok and result.t is not None:
        return result.t
    problem = result.problem
    code = problem.code if problem is not None else "invalid_date"
    message = problem.message if problem is not None else "The anchor doesn't resolve."
    path = _pointer(anchor.pointer, problem.path if problem is not None else "")
    return _error(f"anchor.{code}", path, message)


def dimension_spec(session: Session, dimension_id: str) -> tuple[BaseUnit, int]:
    row = session.get(Dimension, dimension_id)
    if row is None:
        raise ConflictError("The dimension has no time spec.")
    return BaseUnit.model_validate(row.base_unit), row.duration


def _digest(document: Any) -> str:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def compiled_calendar(context: VaultContext, calendar_id: str) -> CompiledCalendar:
    """The stored calendar, compiled (cached). ``NotFoundError`` for a missing calendar,
    ``ConflictError`` for one whose stored definition doesn't compile."""
    session = context.session
    row = session.get(Calendar, calendar_id)
    if row is None:
        raise NotFoundError(f"No calendar {calendar_id}.")
    base_unit, duration = dimension_spec(session, row.dimension_id)
    compile_context = CompileContext(
        calendar_id=calendar_id,
        base_unit=base_unit,
        dimension_duration=str(duration),
        resolved=row.resolved_anchors,
    )
    # The definition is part of the digest: a proposal's dry run (rolled back) compiles a
    # definition under the next revision number, which the applied one may reuse.
    key = (
        context.vault.info.manifest.vault_id,
        calendar_id,
        row.definition_revision,
        _digest([row.definition, compile_context.model_dump(mode="json")]),
    )

    def build() -> CompiledCalendar:
        result = compile_calendar(
            CalendarDefinition.model_validate(row.definition), compile_context
        )
        if isinstance(result, list):
            raise ConflictError("The calendar's definition doesn't compile.")
        return result

    return CALENDARS.get(key, build)


@dataclass(frozen=True)
class AbsoluteLens:
    """The virtual Absolute calendar of a dimension: raw base units."""

    base_unit: BaseUnit


def lens(
    context: VaultContext, dimension_id: str, calendar_id: str
) -> CompiledCalendar | AbsoluteLens:
    """A calendar to display or read dates of the dimension with: one of its calendars, or the
    virtual ``absolute`` calendar."""
    if calendar_id == ABSOLUTE_CALENDAR_ID:
        return AbsoluteLens(dimension_spec(context.session, dimension_id)[0])
    row = context.session.get(Calendar, calendar_id)
    if row is None or row.dimension_id != dimension_id:
        raise NotFoundError(f"No calendar {calendar_id} in this dimension.")
    return compiled_calendar(context, calendar_id)


# --- the kind -----------------------------------------------------------------------------------


class CalendarExt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any] | None = None


def _parse_ext(ext: dict[str, Any] | None) -> CalendarExt:
    try:
        return CalendarExt.model_validate(ext or {})
    except PydanticValidationError as exc:
        raise InvalidInputError(
            "The calendar's extension data is invalid.",
            errors=[
                ErrorItem(
                    path=".".join(["ext", *(str(part) for part in error["loc"])]),
                    code="invalid_value",
                    message=str(error["msg"]),
                )
                for error in exc.errors(include_url=False)
            ],
        ) from exc


def dependents(session: Session, calendar_id: str) -> int:
    """Time slots and recurring series that depend on the calendar."""
    from lore.core.time.series import series_using  # noqa: PLC0415 (import cycle)

    slots = len(DependencyIndex(session).dependents_of(CalendarNode(calendar_id)))
    return slots + len(series_using(session, calendar_id))


def store_definition(context: VaultContext, row: Calendar, compiled: Compiled) -> TimeWriter:
    """Store a compiled definition and rewrite the edges of its anchors; returns the writer to
    propagate with (a cycle through other records answers ``409 time_cycle``)."""
    from lore.core.time.propagate import TimeWriter  # noqa: PLC0415 (import cycle)

    row.definition = compiled.definition
    row.resolved_anchors = compiled.resolved
    row.compile_status, row.compile_errors = "ok", []
    context.session.flush()
    writer = TimeWriter(context)
    writer.index.drop_record(CALENDAR, row.entity_id)
    for anchor in anchor_slots(compiled.definition):
        if anchor.point["anchor"]["kind"] != "local":
            point = parse_time_point(dict(anchor.point))
            writer.set_spec(CALENDAR, row.entity_id, anchor.slot, point)
    writer.touch(CalendarNode(row.entity_id))
    return writer


def _store(context: VaultContext, row: Calendar, compiled: Compiled) -> None:
    store_definition(context, row, compiled).propagate(path="ext.definition")


def write_calendar(
    context: VaultContext, entity: Entity, ext: dict[str, Any] | None, creating: bool
) -> None:
    data = _parse_ext(ext)
    session = context.session
    if creating:
        if data.definition is None:
            message = "A calendar needs a definition."
            raise InvalidInputError(
                message, errors=[ErrorItem(path="ext.definition", code="required", message=message)]
            )
        assert entity.dimension_id is not None
        base_unit, duration = dimension_spec(session, entity.dimension_id)
        resolver = Resolver(context, entity.dimension_id)
        compiled = compile_document(data.definition, base_unit, duration, entity.id, resolver)
        created = Calendar(
            entity_id=entity.id, dimension_id=entity.dimension_id, compile_status="ok"
        )
        session.add(created)
        _store(context, created, compiled)
        session.flush()
        dimension = session.get(Dimension, entity.dimension_id)
        if dimension is not None and dimension.default_calendar_id is None:
            dimension.default_calendar_id = entity.id  # the first calendar (decided)
            session.flush()
        return
    if "definition" not in data.model_fields_set:
        return
    if data.definition is None:
        raise InvalidInputError(
            "The definition can't be removed.",
            errors=[ErrorItem(path="ext.definition", code="invalid_value",
                              message="The definition can't be removed.")],
        )  # fmt: skip
    row = session.get(Calendar, entity.id)
    if row is None:
        raise ConflictError("The calendar has no definition.")
    count = dependents(session, entity.id)
    if count:
        raise ConflictError(
            f"{count} time slots or recurring series depend on this calendar: change its "
            "definition through a "
            "calendar proposal (impact preview), not directly.",
            context={"dependents": count, "proposals": f"/calendars/{entity.id}/proposals"},
        )
    base_unit, duration = dimension_spec(session, row.dimension_id)
    resolver = Resolver(context, row.dimension_id)
    compiled = compile_document(data.definition, base_unit, duration, entity.id, resolver)
    if compiled.definition != row.definition or compiled.resolved != row.resolved_anchors:
        row.definition_revision += 1
        _store(context, row, compiled)
        session.flush()


def read_calendar(
    context: VaultContext, entity: Entity, _policy: VisibilityPolicy
) -> dict[str, Any] | None:
    row = context.session.get(Calendar, entity.id)
    if row is None:
        return None
    return {
        "dimension_id": row.dimension_id,
        "definition": row.definition,
        "definition_revision": row.definition_revision,
        "resolved_anchors": row.resolved_anchors,
        "compile_status": row.compile_status,
        "compile_errors": row.compile_errors,
    }


def _is_default(session: Session, entity: Entity) -> Dimension | None:
    if entity.dimension_id is None:
        return None
    dimension = session.get(Dimension, entity.dimension_id)
    return (
        dimension if dimension is not None and dimension.default_calendar_id == entity.id else None
    )


def _others(session: Session, entity: Entity) -> int:
    """The dimension's other calendars not in the trash."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Calendar)
            .join(Entity, Entity.id == Calendar.entity_id)
            .where(
                Calendar.dimension_id == entity.dimension_id,
                Calendar.entity_id != entity.id,
                Entity.deleted_at.is_(None),
            )
        )
        or 0
    )


def _default_conflict(action: str) -> ConflictError:
    return ConflictError(
        f"This is the dimension's default calendar: choose another default before you {action} it."
    )


def trash_calendar(context: VaultContext, entity: Entity, trashing: bool) -> None:
    session = context.session
    if trashing and _is_default(session, entity) is not None and _others(session, entity):
        raise _default_conflict("trash")


def purge_calendar(context: VaultContext, entity: Entity) -> None:
    session = context.session
    dimension = _is_default(session, entity)
    if dimension is not None:
        if _others(session, entity):
            raise _default_conflict("purge")
        dimension.default_calendar_id = None
    # What depends on the calendar is frozen by the core purge hook (time-model §7.3).
    row = session.get(Calendar, entity.id)
    if row is not None:
        session.delete(row)
    DependencyIndex(session).drop_record(CALENDAR, entity.id)
    session.flush()


def calendar_problems(context: VaultContext, entity: Entity) -> list[str]:
    row = context.session.get(Calendar, entity.id)
    if row is None:
        return [f"{entity.name}: the calendar has no definition."]
    if row.dimension_id != entity.dimension_id:
        return [f"{entity.name}: the calendar's dimension differs from its home dimension."]
    return []


def check_default_calendar(session: Session, dimension_id: str, calendar_id: str | None) -> None:
    """``ext.default_calendar_id`` of a dimension: one of its calendars, not in the trash."""
    if calendar_id is None:
        if session.scalar(select(Calendar.entity_id).where(Calendar.dimension_id == dimension_id)):
            raise InvalidInputError(
                "A dimension with calendars needs a default calendar.",
                errors=[ErrorItem(path="ext.default_calendar_id", code="required",
                                  message="A dimension with calendars needs a default calendar.")],
            )  # fmt: skip
        return
    row = session.get(Calendar, calendar_id)
    entity = session.get(Entity, calendar_id)
    if row is None or entity is None or row.dimension_id != dimension_id:
        message = "The default calendar must be a calendar of this dimension."
    elif entity.deleted_at is not None:
        message = "The default calendar is in the trash."
    else:
        return
    raise InvalidInputError(
        message, errors=[ErrorItem(path="ext.default_calendar_id", code="invalid_value",
                                   message=message)]
    )  # fmt: skip


# --- slots: the definition's anchors ------------------------------------------------------------


def _slot_pointers(row: Calendar) -> dict[str, AnchorSlot]:
    return {anchor.slot: anchor for anchor in anchor_slots(row.definition)}


def load_calendar_slots(session: Session, keys: Sequence[SlotKey]) -> dict[SlotKey, SlotValue]:
    result: dict[SlotKey, SlotValue] = {}
    for key in keys:
        row = session.get(Calendar, key.id)
        entity = session.get(Entity, key.id)
        anchor = _slot_pointers(row).get(key.slot) if row is not None else None
        if row is None or entity is None or anchor is None:
            continue
        t = row.resolved_anchors.get(anchor.pointer)
        local = anchor.point["anchor"]["kind"] == "local"
        result[key] = SlotValue(
            spec=None if local else parse_time_point(dict(anchor.point)),
            t=None if t is None else int(t),
            status=TimeStatus.OK if row.compile_status == "ok" else TimeStatus.CALENDAR_ERROR,
            trashed=entity.deleted_at is not None,
            dimension_id=row.dimension_id,
        )
    return result


def write_calendar_specs(session: Session, updates: Sequence[SpecUpdate]) -> None:
    """New specs for a calendar's anchors (anchor freezing): the definition changes (a new
    revision), its resolved anchors stay."""
    for update in updates:
        row = session.get(Calendar, update.key.id)
        anchor = _slot_pointers(row).get(update.key.slot) if row is not None else None
        if row is None or anchor is None:
            continue
        definition = copy.deepcopy(row.definition)
        parts = [p for p in anchor.pointer.split("/") if p]
        node: Any = definition
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        node[parts[-1]] = dump_spec(update.spec)
        row.definition = definition
        row.definition_revision += 1


def calendar_slot_keys(session: Session) -> list[SlotKey]:
    """Every non-local anchor slot of every calendar."""
    return [
        SlotKey(row.entity_id, anchor.slot)
        for row in session.scalars(select(Calendar).order_by(Calendar.entity_id))
        for anchor in anchor_slots(row.definition)
        if anchor.point["anchor"]["kind"] != "local"
    ]


def write_calendar_slots(session: Session, updates: Sequence[SlotUpdate]) -> None:
    for update in updates:
        row = session.get(Calendar, update.key.id)
        anchor = _slot_pointers(row).get(update.key.slot) if row is not None else None
        if row is None or anchor is None:
            continue
        resolved = dict(row.resolved_anchors)
        if update.t is None:
            resolved.pop(anchor.pointer, None)
        else:
            resolved[anchor.pointer] = str(update.t)
        row.resolved_anchors = resolved


def calendar_moments_beyond(session: Session, dimension_id: str, bound: int) -> list[SlotMoment]:
    found: list[SlotMoment] = []
    rows = session.scalars(select(Calendar).where(Calendar.dimension_id == dimension_id))
    for row in rows:
        for anchor in anchor_slots(row.definition):
            t = row.resolved_anchors.get(anchor.pointer)
            if t is not None and int(t) > bound:
                found.append(SlotMoment(CALENDAR, row.entity_id, anchor.slot, int(t)))
    return found


# --- preview ------------------------------------------------------------------------------------


class Sample(BaseModel):
    t: str
    display: str
    fields: dict[str, Any]


class Preview(BaseModel):
    ok: bool
    errors: list[dict[str, str]]
    definition: dict[str, Any] | None = Field(
        description="The definition previewed (a preset's instantiation)."
    )
    samples: list[Sample] = Field(
        description="The starts of a few top-level units from the first alignment on."
    )


def samples(calendar: CompiledCalendar, duration: int, start: int) -> list[Sample]:
    """The starts of ``SAMPLE_YEARS`` top-level units from the one containing ``start``."""
    top = calendar.levels[-1]
    finest = calendar.levels[0]
    found: list[Sample] = []
    t = min(max(start, 0), duration)
    for _ in range(SAMPLE_YEARS):
        try:
            bounds = unit_bounds(calendar, t, top)
            unit_start = max(bounds.start, 0)
            found.append(
                Sample(
                    t=str(unit_start),
                    display=format_date(calendar, unit_start, finest),
                    fields=to_fields(calendar, unit_start).as_json(),
                )
            )
        except DateError:
            break
        if bounds.end > duration:
            break
        t = bounds.end
    return found


def preview(
    document: dict[str, Any],
    base_unit: BaseUnit,
    duration: int,
    calendar_id: str | None,
    resolver: Resolver | None = None,
) -> Preview:
    try:
        compiled = compile_document(document, base_unit, duration, calendar_id, resolver)
    except CalendarInvalidError as exc:
        errors = [{"code": e["code"], "path": e["path"], "message": e["message"]}
                  for e in exc.errors or []]  # fmt: skip
        return Preview(ok=False, errors=errors, definition=document, samples=[])
    alignment = compiled.resolved.get("/regimes/0/alignment/at", "0")
    return Preview(
        ok=True,
        errors=[],
        definition=compiled.definition,
        samples=samples(compiled.calendar, duration, int(alignment)),
    )


def format_moment(lens_: CompiledCalendar | AbsoluteLens, t: int, precision: str) -> str:
    if isinstance(lens_, AbsoluteLens):
        return format_absolute(t, lens_.base_unit)
    return format_date(lens_, t, precision)


__all__ = [
    "CALENDAR",
    "AbsoluteLens",
    "CalendarInvalidError",
    "CalendarSource",
    "PresetChoice",
    "Preview",
    "compile_document",
    "compiled_calendar",
    "lens",
    "preview",
    "source_definition",
]
