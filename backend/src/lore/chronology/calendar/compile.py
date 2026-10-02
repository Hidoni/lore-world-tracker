"""Calendar compilation: semantic validation and precomputation (``chronology-engine.md`` §4).

:func:`compile_calendar` takes schema-valid models and returns a :class:`CompiledCalendar` or
**all** semantic errors (§11), each with a stable code and a JSON-pointer path. It reports root
causes only: checks that depend on an invalid part are skipped. :func:`validate_calendar` takes
raw JSON documents and also reports structural (schema) errors first.

Not yet compiled (later issues): ``local`` anchors (#14), cycle values (#13), eras (#14),
overlays (#15). They are validated here as far as possible without resolving local anchors.
"""

import hashlib
import json
import math
from bisect import bisect_left
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import accumulate
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from lore.chronology.calendar import formats
from lore.chronology.calendar.compiled import (
    CompiledCalendar,
    CompiledCycle,
    CompiledRegime,
    CompiledTemplate,
    Segment,
    build_template,
    is_number,
)
from lore.chronology.calendar.units import counted_position, cycle_filter
from lore.chronology.schema import (
    AllPredicate,
    CalendarDefinition,
    CompileContext,
    DefinitionTimePoint,
    FixedPattern,
    LocalAnchor,
    ModPredicate,
    NamedChild,
    NotPredicate,
    Predicate,
    Regime,
    RulesPattern,
    SequenceTemplate,
    TimePoint,
    UniformTemplate,
)

RESERVED_LEVEL_IDS = frozenset({"base", "intercalary"})
MAX_PERIOD = 1_000_000
BYTE_VALUES = 256  # top-template indexes that fit one byte of the bit-parallel sequence

__all__ = ["ValidationError", "compile_calendar", "validate_calendar"]


@dataclass(frozen=True, slots=True)
class ValidationError:
    """One definition error: a stable ``code`` (§11) and a JSON pointer ``path``."""

    code: str
    path: str
    message: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


def pointer(*parts: str | int) -> str:
    """A JSON pointer (RFC 6901) from path parts."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _digest(document: Any) -> str:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


# --- compilation ---------------------------------------------------------------------------------


def compile_calendar(
    definition: CalendarDefinition, context: CompileContext
) -> CompiledCalendar | list[ValidationError]:
    """Compile a schema-valid definition, or return every semantic error (sorted by path)."""
    return _Compiler(definition, context).run()


class _Compiler:
    def __init__(self, definition: CalendarDefinition, context: CompileContext) -> None:
        self.definition = definition
        self.context = context
        self.errors: list[ValidationError] = []
        self.levels = tuple(level.id for level in definition.levels)
        self.level_index = {level_id: i for i, level_id in enumerate(self.levels)}
        self.numbering = tuple(level.numbering_start for level in definition.levels)

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append(ValidationError(code, path, message))

    def resolved(self, path: str) -> int | None:
        value = self.context.resolved.get(path)
        return None if value is None else int(value)

    def run(self) -> CompiledCalendar | list[ValidationError]:
        self.check_levels()
        if self.errors:  # everything else is addressed by level
            return self.result()
        self.check_regimes()
        self.check_time_points()
        self.check_eras()
        self.check_overlays()
        regimes: list[CompiledRegime | None] = []
        for i, regime in enumerate(self.definition.regimes):
            regimes.append(self.compile_regime(i, regime, regimes[-1] if regimes else None))
        self.check_formats()
        if self.errors:
            return self.result()
        return CompiledCalendar(
            definition=self.definition,
            context=self.context,
            levels=self.levels,
            numbering_starts=self.numbering,
            regimes=tuple(regime for regime in regimes if regime is not None),
            definition_hash=_digest(self.definition.model_dump(mode="json")),
            context_hash=_digest(self.context.model_dump(mode="json")),
        )

    def result(self) -> list[ValidationError]:
        unique = {(e.path, e.code): e for e in self.errors}
        return [unique[key] for key in sorted(unique)]

    # --- levels, regimes, eras, overlays, time points ---------------------------------------

    def check_levels(self) -> None:
        seen: set[str] = set()
        for i, level in enumerate(self.definition.levels):
            path = pointer("levels", i, "id")
            if level.id in RESERVED_LEVEL_IDS:
                self.error("level.invalid_id", path, f"level id {level.id!r} is reserved")
            if level.id in seen:
                self.error("level.duplicate_id", path, f"duplicate level id {level.id!r}")
            seen.add(level.id)

    def _ordered_starts(
        self,
        kind: str,
        items: Sequence[tuple[str, DefinitionTimePoint | None]],
        member: str,
    ) -> None:
        """Unique ids; item 0 starts at -∞ (``None``), later ones at strictly increasing moments."""
        seen: set[str] = set()
        last: int | None = None
        plural = f"{kind}s"
        for i, (item_id, start) in enumerate(items):
            if item_id in seen:
                self.error(
                    f"{kind}.duplicate_id", pointer(plural, i, "id"), f"duplicate id {item_id!r}"
                )
            seen.add(item_id)
            path = pointer(plural, i, member)
            if i == 0:
                if start is not None:
                    self.error(f"{kind}.first_has_start", path, f"the first {kind} starts at -∞")
                continue
            if start is None:
                self.error(
                    f"{kind}.missing_start", path, f"every {kind} after the first needs a start"
                )
                continue
            if isinstance(start.anchor, LocalAnchor):
                continue  # resolved with the compiled structure (#14)
            value = self.resolved(path)
            if value is None:
                continue  # anchor.unresolved
            if last is not None and value <= last:
                self.error(f"{kind}.start_not_increasing", path, f"{kind} starts must increase")
            last = value

    def check_regimes(self) -> None:
        regimes = self.definition.regimes
        self._ordered_starts("regime", [(r.id, r.starts_at) for r in regimes], "starts_at")

    def check_eras(self) -> None:
        self._ordered_starts("era", [(e.id, e.start) for e in self.definition.eras], "start")

    def check_overlays(self) -> None:
        seen: set[str] = set()
        for i, overlay in enumerate(self.definition.overlays):
            if overlay.id in seen:
                self.error("overlay.duplicate_id", pointer("overlays", i, "id"), "duplicate id")
            seen.add(overlay.id)
            num, _ = overlay.period.as_pair()
            if num <= 0:
                self.error(
                    "overlay.bad_period", pointer("overlays", i, "period"), "period must be > 0"
                )
            previous: tuple[int, int] | None = None
            for k, phase in enumerate(overlay.phases):
                a, b = phase.from_.as_pair()
                in_range = 0 <= a < b and (k > 0 or a == 0)
                increasing = previous is None or a * previous[1] > previous[0] * b
                if not (in_range and increasing):
                    path = pointer("overlays", i, "phases", k, "from")
                    self.error("overlay.phases_unsorted", path, "phases start at 0, increase, < 1")
                previous = (a, b)

    def time_points(self) -> Iterator[tuple[str, TimePoint | DefinitionTimePoint]]:
        for r, regime in enumerate(self.definition.regimes):
            yield pointer("regimes", r, "alignment", "at"), regime.alignment.at
            if regime.starts_at is not None:
                yield pointer("regimes", r, "starts_at"), regime.starts_at
        for e, era in enumerate(self.definition.eras):
            if era.start is not None:
                yield pointer("eras", e, "start"), era.start
        for o, overlay in enumerate(self.definition.overlays):
            yield pointer("overlays", o, "epoch"), overlay.epoch

    def check_time_points(self) -> None:
        for path, point in self.time_points():
            anchor = point.anchor
            if isinstance(anchor, LocalAnchor):
                continue
            if (
                path.endswith("/alignment/at")
                and anchor.kind == "calendar"
                and anchor.calendar_id == self.context.calendar_id
            ):
                self.error(
                    "alignment.self_reference",
                    pointer(*path.split("/")[1:], "anchor", "calendar_id"),
                    "the alignment cannot be a date of this calendar",
                )
            if path not in self.context.resolved:
                self.error("anchor.unresolved", path, "no resolved moment in the context")

    def check_formats(self) -> None:
        formats_ = self.definition.formats
        if formats_ is None:
            return
        levels = frozenset(self.levels)
        cycles = frozenset(c.id for regime in self.definition.regimes for c in regime.cycles)
        overlays = frozenset(o.id for o in self.definition.overlays)
        patterns = [(pointer("formats", k), k, v) for k, v in (formats_.model_extra or {}).items()]
        patterns += [
            (pointer("formats", "intercalary", k), k, v) for k, v in formats_.intercalary.items()
        ]
        for path, key, pattern in patterns:
            if key not in levels:
                self.error("format.unknown_level", path, f"{key!r} is not a level of this calendar")
            unknown = formats.unknown_tokens(
                pattern, levels=levels, cycles=cycles, overlays=overlays
            )
            if unknown:
                self.error("format.unknown_token", path, f"unknown tokens: {unknown}")

    # --- regimes ----------------------------------------------------------------------------

    def compile_regime(
        self, r: int, regime: Regime, previous: CompiledRegime | None
    ) -> CompiledRegime | None:
        before = len(self.errors)
        base = ("regimes", r)
        cycle_ids = self.check_cycles(r, regime)
        templates = self.compile_templates(base, regime, cycle_ids)
        self.check_top(base, regime)
        if len(self.errors) > before or templates is None:
            return None
        compiled = self.build_regime(r, regime, templates)
        offset = self.locate(
            compiled,
            regime.alignment.fields,
            (*base, "alignment", "fields"),
            "alignment.invalid_fields",
        )
        anchors = self.check_cycle_anchors(r, regime, compiled)
        at = self.resolved(pointer(*base, "alignment", "at"))
        if offset is None or at is None or len(self.errors) > before:
            return None
        year, within = offset
        starts_at = None
        if regime.starts_at is not None and not isinstance(regime.starts_at.anchor, LocalAnchor):
            starts_at = self.resolved(pointer(*base, "starts_at"))
        epoch = at - compiled.rel_start(year) - within
        compiled = replace(compiled, epoch=epoch, starts_at=starts_at)
        cycles = self.build_cycles(r, regime, compiled, anchors, previous)
        if len(self.errors) > before:
            return None
        return replace(compiled, cycles=cycles)

    # --- templates --------------------------------------------------------------------------

    def compile_templates(
        self, base: tuple[str | int, ...], regime: Regime, cycle_ids: frozenset[str]
    ) -> dict[str, CompiledTemplate] | None:
        """Validate every template; build them all if the regime's templates are valid."""
        definitions = regime.templates
        ok = True
        children: dict[str, list[str]] = {}
        for template_id, template in definitions.items():
            path = (*base, "templates", template_id)
            refs = self.check_template(path, template, definitions, cycle_ids)
            if refs is None:
                ok = False
            else:
                children[template_id] = refs
        if not ok:
            return None
        compiled: dict[str, CompiledTemplate] = {}

        def build(template_id: str) -> CompiledTemplate:
            if template_id not in compiled:
                for child in children[template_id]:
                    build(child)
                compiled[template_id] = self.build_template(
                    template_id, definitions[template_id], compiled
                )
            return compiled[template_id]

        for template_id in definitions:
            build(template_id)
        return compiled

    def child_template(self, level: int, explicit: str | None) -> str | None:
        return (
            explicit if explicit is not None else self.definition.levels[level - 1].default_template
        )

    def check_template(
        self,
        path: tuple[str | int, ...],
        template: UniformTemplate | SequenceTemplate,
        definitions: Mapping[str, UniformTemplate | SequenceTemplate],
        cycle_ids: frozenset[str],
    ) -> list[str] | None:
        """Local checks of one template; returns the child template ids, or None if invalid."""
        before = len(self.errors)
        level = self.level_index.get(template.level)
        if level is None:
            self.error(
                "template.unknown_level",
                pointer(*path, "level"),
                f"unknown level {template.level!r}",
            )
            return None
        refs: list[str] = []

        def reference(
            explicit: str | None,
            ref_path: tuple[str | int, ...],
            implicit_path: tuple[str | int, ...],
        ) -> None:
            child = self.child_template(level, explicit)
            where = pointer(*(ref_path if explicit is not None else implicit_path))
            if child is None or child not in definitions:
                self.error("template.unknown_template", where, f"unknown child template {child!r}")
                return
            child_level = self.level_index.get(definitions[child].level)
            if child_level is not None and child_level != level - 1:
                self.error(
                    "template.child_level_mismatch",
                    where,
                    f"{child!r} is not a {self.levels[level - 1]} template",
                )
                return
            refs.append(child)

        if isinstance(template, UniformTemplate) and level == 0:
            if template.uniform.template is not None:
                self.error(
                    "template.level0_not_uniform",
                    pointer(*path, "uniform", "template"),
                    "level-0 units are made of base units",
                )
        elif isinstance(template, UniformTemplate):
            reference(template.uniform.template, (*path, "uniform", "template"), (*path, "uniform"))
        elif level == 0:
            self.error(
                "template.level0_not_uniform",
                pointer(*path, "sequence"),
                "level-0 templates are uniform",
            )
        else:
            slots: set[str] = set()
            for k, child in enumerate(template.sequence):
                child_path = (*path, "sequence", k)
                if isinstance(child, NamedChild):
                    self.check_named_child(child, child_path, slots, cycle_ids)
                    reference(child.template, (*child_path, "template"), (*child_path, "template"))
                else:
                    reference(
                        child.run.template, (*child_path, "run", "template"), (*child_path, "run")
                    )
        return refs if len(self.errors) == before else None

    def check_named_child(
        self,
        child: NamedChild,
        path: tuple[str | int, ...],
        slots: set[str],
        cycle_ids: frozenset[str],
    ) -> None:
        if child.id in slots:
            self.error(
                "template.duplicate_slot_id",
                pointer(*path, "id"),
                f"duplicate slot id {child.id!r}",
            )
        slots.add(child.id)
        for j, cycle_id in enumerate(child.cycle_excluded):
            if cycle_id not in cycle_ids:
                self.error(
                    "template.unknown_cycle",
                    pointer(*path, "cycle_excluded", j),
                    f"unknown cycle {cycle_id!r}",
                )

    def build_template(
        self,
        template_id: str,
        template: UniformTemplate | SequenceTemplate,
        compiled: Mapping[str, CompiledTemplate],
    ) -> CompiledTemplate:
        level = self.level_index[template.level]
        segments: list[Segment] = []
        if isinstance(template, UniformTemplate):
            count = int(template.uniform.count)
            child_id = None if level == 0 else self.child_template(level, template.uniform.template)
            length = 1 if child_id is None else compiled[child_id].length
            segments.append(Segment(count, child_id, length, 0, 0))
        else:
            start = regular = 0
            for child in template.sequence:
                if isinstance(child, NamedChild):
                    child_id, count = child.template, 1
                    extra: dict[str, Any] = {
                        "slot_id": child.id,
                        "name": child.name,
                        "abbr": child.abbr,
                        "intercalary": child.intercalary,
                        "cycle_excluded": tuple(child.cycle_excluded),
                    }
                else:
                    child_id = self.child_template(level, child.run.template)
                    count, extra = int(child.run.count), {}
                assert child_id is not None  # checked by check_template
                segment = Segment(
                    count, child_id, compiled[child_id].length, start, regular, **extra
                )
                segments.append(segment)
                start += count * segment.child_length
                regular += segment.regular_count
        units = self.units(level, segments, compiled)
        return build_template(template_id, level, segments, units)

    @staticmethod
    def units(
        level: int, segments: Sequence[Segment], compiled: Mapping[str, CompiledTemplate]
    ) -> dict[int, tuple[int, int]]:
        """Level → (total, regular) descendant units; a unit is regular unless it is intercalary."""
        if level == 0:
            return {}
        total = sum(s.count for s in segments)
        units = {level - 1: (total, sum(s.regular_count for s in segments))}
        for below in range(level - 1):
            units[below] = (
                sum(s.count * compiled[s.child].units[below][0] for s in segments if s.child),
                sum(s.count * compiled[s.child].units[below][1] for s in segments if s.child),
            )
        return units

    # --- top pattern ------------------------------------------------------------------------

    def check_top(self, base: tuple[str | int, ...], regime: Regime) -> None:
        top = regime.top
        path = (*base, "top")
        top_level = self.levels[-1]

        def reference(template_id: str, ref_path: tuple[str | int, ...]) -> None:
            template = regime.templates.get(template_id)
            if template is None:
                self.error(
                    "top.unknown_template", pointer(*ref_path), f"unknown template {template_id!r}"
                )
            elif template.level != top_level and template.level in self.level_index:
                self.error(
                    "top.template_wrong_level",
                    pointer(*ref_path),
                    f"{template_id!r} is not a {top_level} template",
                )

        pattern = top.pattern
        pattern_path = (*path, "pattern")
        if isinstance(pattern, FixedPattern):
            reference(pattern.template, (*pattern_path, "template"))
        elif isinstance(pattern, RulesPattern):
            reference(pattern.default, (*pattern_path, "default"))
            moduli: list[int] = []
            for k, rule in enumerate(pattern.rules):
                reference(rule.template, (*pattern_path, "rules", k, "template"))
                self.check_predicate(rule.when, (*pattern_path, "rules", k, "when"), moduli)
            if _lcm_exceeds(moduli, MAX_PERIOD):
                self.error(
                    "top.period_too_large",
                    pointer(*pattern_path),
                    f"the period exceeds {MAX_PERIOD}",
                )
        else:
            for k, template_id in enumerate(pattern.templates):
                reference(template_id, (*pattern_path, "templates", k))
        years: set[int] = set()
        for k, exception in enumerate(top.exceptions):
            year = int(exception.year)
            if year in years:
                self.error(
                    "top.duplicate_exception",
                    pointer(*path, "exceptions", k, "year"),
                    f"duplicate exception year {year}",
                )
            years.add(year)
            reference(exception.template, (*path, "exceptions", k, "template"))

    def check_predicate(
        self, predicate: Predicate, path: tuple[str | int, ...], moduli: list[int]
    ) -> None:
        if isinstance(predicate, ModPredicate):
            mod, eq = int(predicate.mod), int(predicate.eq)
            if eq >= mod:
                self.error("top.bad_predicate", pointer(*path), "eq must lie in [0, mod)")
            moduli.append(mod)
        elif isinstance(predicate, NotPredicate):
            self.check_predicate(predicate.not_, (*path, "not"), moduli)
        else:
            key, inner = (
                ("all", predicate.all)
                if isinstance(predicate, AllPredicate)
                else ("any", predicate.any)
            )
            for j, part in enumerate(inner):
                self.check_predicate(part, (*path, key, j), moduli)

    def build_regime(
        self, r: int, regime: Regime, templates: dict[str, CompiledTemplate]
    ) -> CompiledRegime:
        """Period, per-period template sequence, prefix sums and exceptions (§4 step 3, §5.2)."""
        pattern = regime.top.pattern
        top_templates, sequence = _top_sequence(pattern)
        period = len(sequence)
        lengths = [templates[t].length for t in top_templates]
        year_starts = list(accumulate((lengths[i] for i in sequence), initial=0))
        cycle_length = year_starts[-1]
        exceptions = sorted((int(e.year), e.template) for e in regime.top.exceptions)
        years = tuple(year for year, _ in exceptions)
        deltas = [
            templates[template_id].length - lengths[sequence[year % period]]
            for year, template_id in exceptions
        ]
        prefix = tuple(accumulate(deltas, initial=0))
        negative = prefix[bisect_left(years, 0)]
        starts = tuple(
            (year // period) * cycle_length + year_starts[year % period] + prefix[e] - negative
            for e, year in enumerate(years)
        )
        return CompiledRegime(
            id=regime.id,
            index=r,
            templates=templates,
            period=period,
            top_templates=top_templates,
            top_sequence=sequence,
            year_starts=year_starts,
            cycle_length=cycle_length,
            exception_years=years,
            exception_templates=tuple(template_id for _, template_id in exceptions),
            exception_deltas=prefix,
            exception_starts=starts,
            epoch=0,
            starts_at=None,
        )

    # --- fields, cycles ---------------------------------------------------------------------

    def locate(
        self,
        regime: CompiledRegime,
        fields: Mapping[str, str],
        path: tuple[str | int, ...],
        code: str,
        finest: str | None = None,
    ) -> tuple[int, int] | None:
        """(year, offset within the year) of the unit ``fields`` denote, or None (error added).

        Fields go from the top level down without gaps; values are regular numbers or slot ids.
        With ``finest``, the fields must stop exactly at that level.
        """
        unknown = [key for key in fields if key not in self.level_index]
        for key in unknown:
            self.error(code, pointer(*path, key), f"{key!r} is not a level")
        present = sorted(
            (self.level_index[key] for key in fields if key in self.level_index), reverse=True
        )
        top = len(self.levels) - 1
        lowest = present[-1] if present else top
        expected = list(range(top, lowest - 1, -1))
        if unknown:
            return None
        if present != expected or (finest is not None and lowest != self.level_index[finest]):
            self.error(code, pointer(*path), "fields must go from the top level down without gaps")
            return None
        year_value = fields[self.levels[top]]
        if not is_number(year_value):
            self.error(code, pointer(*path, self.levels[top]), "the year must be a number")
            return None
        year = int(year_value)
        template: CompiledTemplate = regime.year_template(year)
        offset = 0
        for level in range(top - 1, lowest - 1, -1):
            value = fields[self.levels[level]]
            if is_number(value):
                child = template.child_by_regular_index(int(value) - self.numbering[level])
            else:
                child = template.child_by_slot(value)
            if child is None:
                self.error(
                    code,
                    pointer(*path, self.levels[level]),
                    f"no {self.levels[level]} {value!r} here",
                )
                return None
            offset += child.offset
            assert child.template is not None  # children of level >= 1 templates are templates
            template = regime.templates[child.template]
        return year, offset

    def check_cycles(self, r: int, regime: Regime) -> frozenset[str]:
        seen: set[str] = set()
        for c, cycle in enumerate(regime.cycles):
            path = ("regimes", r, "cycles", c)
            if cycle.id in seen:
                self.error(
                    "cycle.duplicate_id", pointer(*path, "id"), f"duplicate cycle id {cycle.id!r}"
                )
            seen.add(cycle.id)
            level = self.level_index.get(cycle.level)
            if level is None:
                self.error(
                    "cycle.unknown_level", pointer(*path, "level"), f"unknown level {cycle.level!r}"
                )
            for member in ("names", "abbrs"):
                values = getattr(cycle, member)
                if values is not None and len(values) != cycle.length:
                    self.error(
                        "cycle.names_length_mismatch",
                        pointer(*path, member),
                        f"{member} must have {cycle.length} entries",
                    )
            if cycle.mode != "continuous":
                reset = self.level_index.get(cycle.mode.reset)
                if reset is None or level is None or reset <= level:
                    self.error(
                        "cycle.bad_reset_level",
                        pointer(*path, "mode", "reset"),
                        "the reset level must be coarser",
                    )
            if cycle.continue_from_previous_regime and cycle.mode != "continuous":
                self.error(
                    "cycle.anchor_invalid",
                    pointer(*path, "continue_from_previous_regime"),
                    "only continuous cycles continue across regimes",
                )
            elif cycle.continue_from_previous_regime and r == 0:
                self.error(
                    "cycle.anchor_invalid",
                    pointer(*path, "continue_from_previous_regime"),
                    "regime 0 has no previous regime",
                )
            elif cycle.continue_from_previous_regime:
                previous = self.definition.regimes[r - 1]
                self.check_continued_cycle(path, cycle.id, cycle.length, previous)
            elif (
                cycle.mode == "continuous"
                and not cycle.continue_from_previous_regime
                and (cycle.anchor is None or cycle.anchor.fields is None)
            ):
                missing = ("anchor",) if cycle.anchor is None else ("anchor", "fields")
                self.error(
                    "cycle.anchor_invalid",
                    pointer(*path, *missing),
                    "a continuous cycle needs an anchor date",
                )
            if cycle.anchor is not None and cycle.anchor.index >= cycle.length:
                self.error(
                    "cycle.anchor_invalid",
                    pointer(*path, "anchor", "index"),
                    "index must be < length",
                )
        return frozenset(seen)

    def check_continued_cycle(
        self, path: tuple[str | int, ...], cycle_id: str, length: int, previous: Regime
    ) -> None:
        """A continued cycle needs a continuous cycle of the same id and length before it."""
        where = pointer(*path, "continue_from_previous_regime")
        before = next((c for c in previous.cycles if c.id == cycle_id), None)
        if before is None or before.mode != "continuous":
            self.error(
                "cycle.anchor_invalid",
                where,
                f"the previous regime has no continuous cycle {cycle_id!r}",
            )
        elif before.length != length:
            self.error(
                "cycle.anchor_invalid", where, "the previous regime's cycle has another length"
            )

    def check_cycle_anchors(
        self, r: int, regime: Regime, compiled: CompiledRegime
    ) -> dict[int, tuple[int, int]]:
        """Locate the anchor date of every anchored continuous cycle: cycle index → position."""
        anchors: dict[int, tuple[int, int]] = {}
        for c, cycle in enumerate(regime.cycles):
            anchored = cycle.mode == "continuous" and not cycle.continue_from_previous_regime
            if (
                anchored
                and cycle.anchor is not None
                and cycle.anchor.fields is not None
                and cycle.level in self.level_index
            ):
                path = ("regimes", r, "cycles", c, "anchor", "fields")
                found = self.locate(
                    compiled, cycle.anchor.fields, path, "cycle.anchor_invalid", finest=cycle.level
                )
                if found is not None:
                    anchors[c] = found
        return anchors

    def build_cycles(
        self,
        r: int,
        regime: Regime,
        compiled: CompiledRegime,
        anchors: Mapping[int, tuple[int, int]],
        previous: CompiledRegime | None,
    ) -> tuple[CompiledCycle, ...]:
        """Compile cycles; continuous anchors become counted ordinals (§3.7)."""
        top = len(self.levels) - 1
        result: list[CompiledCycle] = []
        for c, cycle in enumerate(regime.cycles):
            level = self.level_index[cycle.level]
            path = ("regimes", r, "cycles", c)
            unit_filter = cycle_filter(cycle.id)
            anchor_index = cycle.anchor.index if cycle.anchor is not None else 0
            anchor_ordinal: int | None = None
            if cycle.mode != "continuous":
                reset: int | None = self.level_index[cycle.mode.reset]
            else:
                reset = None
                if cycle.continue_from_previous_regime:
                    continued = self.continue_cycle(
                        path,
                        cycle_id=cycle.id,
                        length=cycle.length,
                        level=level,
                        compiled=compiled,
                        previous=previous,
                    )
                    if continued is not None:
                        anchor_index, anchor_ordinal = continued
                else:
                    year, offset = anchors[c]
                    start = compiled.year_start(year) + offset
                    before, counted, _ = counted_position(top, compiled, start, level, unit_filter)
                    if not counted:
                        self.error(
                            "cycle.anchor_invalid",
                            pointer(*path, "anchor", "fields"),
                            "the anchor unit is excluded from the cycle",
                        )
                    anchor_ordinal = before
            result.append(
                CompiledCycle(
                    id=cycle.id,
                    level=level,
                    length=cycle.length,
                    names=tuple(cycle.names) if cycle.names is not None else None,
                    abbrs=tuple(cycle.abbrs) if cycle.abbrs is not None else None,
                    number_start=cycle.number_start,
                    reset=reset,
                    anchor_index=anchor_index,
                    anchor_ordinal=anchor_ordinal,
                )
            )
        return tuple(result)

    def continue_cycle(
        self,
        path: tuple[str | int, ...],
        *,
        cycle_id: str,
        length: int,
        level: int,
        compiled: CompiledRegime,
        previous: CompiledRegime | None,
    ) -> tuple[int, int] | None:
        """(anchor index, anchor ordinal) so the first counted unit of this regime follows the
        previous regime's last one. ``None`` while this regime's start is ``local`` (#14).
        """
        if previous is None:
            return None  # the previous regime failed to compile: its errors are the root cause
        before_cycle = next(c for c in previous.cycles if c.id == cycle_id)  # check_cycles
        assert before_cycle.reset is None  # checked by check_cycles
        assert before_cycle.length == length
        start = compiled.starts_at
        if start is None or before_cycle.anchor_ordinal is None:
            return None
        top = len(self.levels) - 1
        unit_filter = cycle_filter(cycle_id)
        last, counted, _ = counted_position(top, previous, start - 1, level, unit_filter)
        last_ordinal = last if counted else last - 1
        last_index = (
            last_ordinal - before_cycle.anchor_ordinal + before_cycle.anchor_index
        ) % length
        first, _, _ = counted_position(top, compiled, start, level, unit_filter)
        return (last_index + 1) % length, first


def _lcm_exceeds(moduli: Sequence[int], limit: int) -> bool:
    period = 1
    for mod in moduli:
        period = math.lcm(period, mod)
        if period > limit:
            return True
    return False


def _top_sequence(pattern: Any) -> tuple[tuple[str, ...], Sequence[int]]:
    """Distinct top templates and the template index of each year in one period."""
    if isinstance(pattern, FixedPattern):
        return (pattern.template,), b"\x00"
    if isinstance(pattern, RulesPattern):
        ids = tuple(dict.fromkeys([pattern.default, *(rule.template for rule in pattern.rules)]))
        index = {template_id: i for i, template_id in enumerate(ids)}
        moduli: list[int] = []
        for rule in pattern.rules:
            _collect_moduli(rule.when, moduli)
        period = math.lcm(*moduli) if moduli else 1
        rules = [(index[rule.template], rule.when) for rule in pattern.rules]
        return ids, _rules_sequence(period, index[pattern.default], rules, len(ids))
    ids = tuple(dict.fromkeys(pattern.templates))
    index = {template_id: i for i, template_id in enumerate(ids)}
    count, start = len(pattern.templates), int(pattern.start)
    sequence = [index[pattern.templates[(i - start) % count]] for i in range(count)]
    return ids, bytes(sequence) if len(ids) <= BYTE_VALUES else sequence


def _collect_moduli(predicate: Predicate, moduli: list[int]) -> None:
    if isinstance(predicate, ModPredicate):
        moduli.append(int(predicate.mod))
    elif isinstance(predicate, NotPredicate):
        _collect_moduli(predicate.not_, moduli)
    else:
        for inner in predicate.all if isinstance(predicate, AllPredicate) else predicate.any:
            _collect_moduli(inner, moduli)


def _rules_sequence(
    period: int, default: int, rules: Sequence[tuple[int, Predicate]], count: int
) -> Sequence[int]:
    """The template index per year of the period: the first matching rule wins, else default.

    Bit-parallel: each year is one byte of a big integer, so a period of 1,000,000 years takes a
    few big-integer operations per predicate instead of a Python loop per year.
    """
    if count > BYTE_VALUES:
        matchers = [(index, _predicate_function(when)) for index, when in rules]
        return [next((i for i, match in matchers if match(y)), default) for y in range(period)]
    ones = int.from_bytes(b"\x01" * period, "little")
    full = ones * 0xFF

    def mask(predicate: Predicate) -> int:
        if isinstance(predicate, ModPredicate):
            mod, eq = int(predicate.mod), int(predicate.eq)
            bits = bytearray(period)
            bits[eq::mod] = b"\x01" * len(range(eq, period, mod))
            return int.from_bytes(bits, "little")
        if isinstance(predicate, NotPredicate):
            return ones ^ mask(predicate.not_)
        if isinstance(predicate, AllPredicate):
            result = ones
            for inner in predicate.all:
                result &= mask(inner)
            return result
        result = 0
        for inner in predicate.any:
            result |= mask(inner)
        return result

    sequence = ones * default
    for index, when in reversed(rules):
        selected = mask(when)
        sequence = (sequence & (full ^ (selected * 0xFF))) | (selected * index)
    return sequence.to_bytes(period, "little")


def _predicate_function(predicate: Predicate) -> Callable[[int], bool]:
    if isinstance(predicate, ModPredicate):
        mod, eq = int(predicate.mod), int(predicate.eq)
        return lambda year: year % mod == eq
    if isinstance(predicate, NotPredicate):
        inner = _predicate_function(predicate.not_)
        return lambda year: not inner(year)
    if isinstance(predicate, AllPredicate):
        parts = [_predicate_function(p) for p in predicate.all]
        return lambda year: all(part(year) for part in parts)
    parts = [_predicate_function(p) for p in predicate.any]
    return lambda year: any(part(year) for part in parts)


# --- raw documents (schema + semantics) ----------------------------------------------------------


def validate_calendar(definition: Any, context: Any) -> CompiledCalendar | list[ValidationError]:
    """Validate raw JSON documents: structural (schema) errors first, then :func:`compile_calendar`.

    Some schema violations have specific codes (§11): too many levels, a bad level id, a zero or
    oversized count, too many templates or children, an intercalary child without id, an era on a
    local anchor. Every other violation is ``schema.invalid``.
    """
    errors = _prescan(definition)
    try:
        parsed = CalendarDefinition.model_validate(definition)
    except PydanticValidationError as error:
        parsed = None
        errors += _schema_errors(error, {"": definition}, "", skip=[e.path for e in errors])
    try:
        parsed_context = CompileContext.model_validate(context)
    except PydanticValidationError as error:
        parsed_context = None
        errors += _schema_errors(error, {"": context}, "/$context", skip=[])
    if errors or parsed is None or parsed_context is None:
        unique = {(e.path, e.code): e for e in errors}
        return [unique[key] for key in sorted(unique)]
    return compile_calendar(parsed, parsed_context)


def _prescan(definition: Any) -> list[ValidationError]:
    """Violations with dedicated codes that the schema would only report as unknown members."""
    errors: list[ValidationError] = []
    if not isinstance(definition, dict):
        return errors
    regimes = definition.get("regimes")
    for r, regime in enumerate(regimes if isinstance(regimes, list) else []):
        if not isinstance(regime, dict):
            continue
        templates = regime.get("templates")
        for template_id, template in templates.items() if isinstance(templates, dict) else []:
            sequence = template.get("sequence") if isinstance(template, dict) else None
            for k, child in enumerate(sequence if isinstance(sequence, list) else []):
                if (
                    isinstance(child, dict)
                    and child.get("intercalary") is True
                    and "id" not in child
                ):
                    path = pointer("regimes", r, "templates", template_id, "sequence", k)
                    errors.append(
                        ValidationError(
                            "template.intercalary_without_id",
                            path,
                            "an intercalary child needs an id",
                        )
                    )
        errors += _local_era(regime.get("starts_at"), ("regimes", r, "starts_at"))
    for kind, member in (("eras", "start"), ("overlays", "epoch")):
        items = definition.get(kind)
        for i, item in enumerate(items if isinstance(items, list) else []):
            if isinstance(item, dict):
                errors += _local_era(item.get(member), (kind, i, member))
    return errors


def _local_era(point: Any, path: tuple[str | int, ...]) -> list[ValidationError]:
    anchor = point.get("anchor") if isinstance(point, dict) else None
    if isinstance(anchor, dict) and anchor.get("kind") == "local" and "era" in anchor:
        where = pointer(*path, "anchor", "era")
        return [
            ValidationError(
                "era.local_anchor_uses_era", where, "local anchors use astronomical years"
            )
        ]
    return []


def _schema_errors(
    error: PydanticValidationError, root: dict[str, Any], prefix: str, skip: Sequence[str]
) -> list[ValidationError]:
    groups: dict[tuple[str, str], list[ValidationError]] = {}
    for detail in error.errors():
        path, union = _clean_location(root[""], detail["loc"])
        code = _schema_code(path, detail["type"], detail.get("input"))
        item = ValidationError(code, prefix + path, detail["msg"])
        groups.setdefault(union or ("", ""), []).append(item)
    return [
        e
        for e in _best_union_members(groups)
        if not any(e.path == s or e.path.startswith(s + "/") for s in skip)
    ]


def _clean_location(
    document: Any, location: Sequence[str | int]
) -> tuple[str, tuple[str, str] | None]:
    """Drop union-member names from a pydantic location (they aren't document keys)."""
    parts: list[str | int] = []
    node = document
    union: tuple[str, str] | None = None
    for part in location:
        in_list = isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node)
        if in_list or (isinstance(node, dict) and part in node):
            node = node[part]
            parts.append(part)
        elif isinstance(part, str) and _is_member(node, part):
            union = union or (pointer(*parts), part)
        else:
            parts.append(part)
            node = None
    return pointer(*parts), union


def _is_member(node: Any, part: str) -> bool:
    """A union member in a location: a model name, a validator name, or a ``kind`` tag."""
    if part[:1].isupper() or "[" in part:
        return True
    return isinstance(node, dict) and node.get("kind") == part


def _best_union_members(
    groups: dict[tuple[str, str], list[ValidationError]],
) -> list[ValidationError]:
    """Of a union's members, keep those whose errors are not about the member's own shape."""
    result = list(groups.pop(("", ""), []))
    by_node: dict[str, list[tuple[str, list[ValidationError]]]] = {}
    for (node, member), items in groups.items():
        by_node.setdefault(node, []).append((member, items))
    for node, members in by_node.items():

        def shaped(items: list[ValidationError], node: str = node) -> bool:
            return not any(
                e.message.startswith(("Field required", "Extra inputs"))
                and e.path.count("/") <= node.count("/") + 1
                for e in items
            )

        fitting = [items for _, items in members if shaped(items)]
        for items in fitting or [items for _, items in members]:
            result.extend(items)
    return result


def _schema_code(path: str, error_type: str, value: Any) -> str:
    code = "schema.invalid"
    match path.split("/")[1:]:
        case ["levels"] if error_type == "too_long":
            code = "level.too_many"
        case ["levels", _, "id"]:
            code = "level.invalid_id"
        case ["regimes", _, "templates"] | ["regimes", _, "templates", *_, "sequence"] if (
            error_type == "too_long"
        ):
            code = "template.too_large"
        case ["regimes", _, "templates", *_, "count"] if error_type == "string_too_long":
            code = "template.too_large"
        case ["regimes", _, "templates", *_, "count"] if value == "0":
            code = "template.zero_length"
    return code
