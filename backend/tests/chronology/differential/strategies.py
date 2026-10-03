"""Hypothesis strategies for differential testing: random calendars and conformance ops.

Everything here produces the conformance README's JSON shapes (``spec/chronology/conformance/
README.md``), so a generated case can be pasted into a case file as is. Sizes are bounded (at most
four levels, two regimes, small templates and periods) to keep each engine call fast, while the
moments, years and counts span the full range of big integers.

Calendars are built in two phases. The structure (levels, templates, top patterns, eras,
overlays) is generated first; cycles are added once that structure compiles, because a continuous
cycle's anchor names a date, which is read off the compiled calendar with the Python engine. Ops
take their dates from the Python engine too (``to_fields`` of a random moment, then perturbed), so
most inputs are valid and reach deep into both engines, while the perturbations exercise the
error paths. Using one engine to build inputs is fine: both engines then get the same input.
"""

import copy
import math
from collections.abc import Sequence
from typing import Any

from hypothesis import strategies as st

from lore.chronology.calendar import CompiledCalendar, validate_calendar
from tests.chronology.ops import run_op

type Json = dict[str, Any]

BASE_UNIT = {"singular": "tick", "plural": "ticks", "abbr": "tk"}
SLOT_IDS = ("aa", "bb", "cc", "dd", "ee", "ff")
DURATIONS = (10**6, 10**12, 10**18, 10**40)
MODS = (2, 3, 4, 5, 7, 10, 100, 400)


def _absolute(t: int) -> Json:
    """A time point given as a moment; its resolution goes into ``context.resolved``."""
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


def _ids(level: int, count: int) -> list[str]:
    return [f"t{level}_{j}" for j in range(count)]


# --- structure ---------------------------------------------------------------------------------


@st.composite
def _child(draw: st.DrawFn, child_templates: Sequence[str], slot: str | None) -> Json:
    template = draw(st.sampled_from(child_templates))
    if slot is None:
        run: Json = {"count": str(draw(st.integers(1, 5)))}
        if draw(st.booleans()):
            run["template"] = template
        return {"run": run}
    named: Json = {"id": slot, "template": template, "name": slot.upper()}
    if draw(st.booleans()):
        named["abbr"] = slot[0].upper()
    return named


@st.composite
def _template(draw: st.DrawFn, level_id: str, child_templates: Sequence[str] | None) -> Json:
    if child_templates is None:  # level 0: base units
        count = draw(st.sampled_from([1, 1, 2, 3, 5, 60, 3600]))
        return {"level": level_id, "uniform": {"count": str(count)}}
    if draw(st.integers(0, 2)) == 0:
        uniform: Json = {"count": str(draw(st.integers(1, 12)))}
        if draw(st.booleans()):
            uniform["template"] = draw(st.sampled_from(child_templates))
        return {"level": level_id, "uniform": uniform}
    size = draw(st.integers(1, 5))
    named = draw(st.lists(st.booleans(), min_size=size, max_size=size))
    slots = iter(draw(st.permutations(SLOT_IDS)))
    children = [draw(_child(child_templates, next(slots) if n else None)) for n in named]
    named_positions = [i for i, child in enumerate(children) if "id" in child]
    if size > 1 and named_positions and draw(st.integers(0, 3)) == 0:
        children[draw(st.sampled_from(named_positions))]["intercalary"] = True
    return {"level": level_id, "sequence": children}


@st.composite
def _predicate(draw: st.DrawFn, depth: int = 0) -> Json:
    kind = draw(st.sampled_from(["mod", "mod", "all", "any", "not"] if depth < 2 else ["mod"]))
    if kind == "mod":
        mod = draw(st.sampled_from(MODS))
        return {"mod": str(mod), "eq": str(draw(st.integers(0, mod - 1)))}
    if kind == "not":
        return {"not": draw(_predicate(depth + 1))}
    return {kind: draw(st.lists(_predicate(depth + 1), min_size=1, max_size=3))}


@st.composite
def _top(draw: st.DrawFn, templates: Sequence[str]) -> Json:
    kind = draw(st.sampled_from(["fixed", "cycle", "rules"]))
    pattern: Json
    if kind == "fixed":
        pattern = {"kind": "fixed", "template": draw(st.sampled_from(templates))}
    elif kind == "cycle":
        cycle = draw(st.lists(st.sampled_from(templates), min_size=1, max_size=5))
        pattern = {"kind": "cycle", "templates": cycle, "start": str(draw(st.integers(-50, 50)))}
    else:
        rules = draw(
            st.lists(
                st.fixed_dictionaries(
                    {"when": _predicate(), "template": st.sampled_from(templates)}
                ),
                max_size=3,
            )
        )
        pattern = {"kind": "rules", "default": draw(st.sampled_from(templates)), "rules": rules}
    top: Json = {"pattern": pattern}
    years = draw(st.lists(st.integers(-100, 100), max_size=2, unique=True))
    if years:
        top["exceptions"] = [
            {"year": str(year), "template": draw(st.sampled_from(templates))} for year in years
        ]
    return top


@st.composite
def _regime(draw: st.DrawFn, index: int, levels: Sequence[str]) -> Json:
    templates: Json = {}
    below: list[str] | None = None
    for i, level_id in enumerate(levels):
        count = draw(st.integers(1, 2 if i == 0 else 3))
        ids = _ids(i, count)
        for template_id in ids:
            templates[template_id] = draw(_template(level_id, below))
        below = ids
    assert below is not None
    year = draw(st.integers(-1000, 1000))
    return {
        "id": f"r{index}",
        "name": f"Regime {index}",
        "templates": templates,
        "top": draw(_top(below)),
        "alignment": {"fields": {levels[-1]: str(year)}, "at": _absolute(0)},
    }


@st.composite
def _local(draw: st.DrawFn, top: str, regimes: Sequence[str]) -> Json:
    """A `local` anchor (a year of this calendar), resolved by the engines themselves."""
    anchor: Json = {"kind": "local", "fields": {top: str(draw(st.integers(-300, 300)))}}
    if draw(st.booleans()):
        anchor["regime"] = draw(st.sampled_from(regimes))
    return {"anchor": anchor, "precision": top}


def _resolve_absolute(document: Json, path: str, t: int) -> None:
    document["context"]["resolved"][path] = str(t)


@st.composite
def _structure(draw: st.DrawFn) -> Json:
    """A calendar document without cycles."""
    count = draw(st.integers(2, 4))
    levels = [f"l{i}" for i in range(count - 1)] + ["year"]
    duration = draw(st.sampled_from(DURATIONS))
    moments = st.integers(0, duration)
    level_docs: list[Json] = []
    for i, level_id in enumerate(levels):
        level: Json = {"id": level_id, "label": level_id, "plural": f"{level_id}s"}
        if i < count - 1:
            level["default_template"] = _ids(i, 1)[0]
            numbering = draw(st.sampled_from([None, 0, 1, 1]))
            if numbering is not None:
                level["numbering_start"] = numbering
        level_docs.append(level)
    document: Json = {
        "definition": {"schema_version": 1, "levels": level_docs, "regimes": []},
        "context": {"base_unit": BASE_UNIT, "dimension_duration": str(duration), "resolved": {}},
    }
    definition = document["definition"]
    regime_count = draw(st.integers(1, 2))
    starts = sorted(draw(st.lists(moments, min_size=regime_count, max_size=regime_count)))
    for r in range(regime_count):
        regime = draw(_regime(r, levels))
        if r > 0 and draw(st.integers(0, 2)) == 0:
            regime["starts_at"] = draw(_local(levels[-1], [f"r{i}" for i in range(r + 1)]))
        elif r > 0:
            regime["starts_at"] = _absolute(starts[r])
            _resolve_absolute(document, f"/regimes/{r}/starts_at", starts[r])
        definition["regimes"].append(regime)
        _resolve_absolute(document, f"/regimes/{r}/alignment/at", draw(moments))
    era_count = draw(st.sampled_from([0, 0, 2, 3]))
    if era_count:
        era_starts = sorted(draw(st.lists(moments, min_size=era_count - 1, max_size=era_count - 1)))
        eras: list[Json] = []
        for e in range(era_count):
            backward = e == 0 or (e < era_count - 1 and draw(st.booleans()))
            era: Json = {
                "id": f"e{e}",
                "name": f"Era {e}",
                "abbr": f"E{e}",
                "numbering": {
                    "direction": "backward" if backward else "forward",
                    "first": str(draw(st.sampled_from([0, 1, 1, 100]))),
                },
                "abbr_position": draw(st.sampled_from(["prefix", "suffix"])),
            }
            regimes = [regime["id"] for regime in definition["regimes"]]
            if e > 0 and draw(st.integers(0, 2)) == 0:
                era["start"] = draw(_local(levels[-1], regimes))
            elif e > 0:
                era["start"] = _absolute(era_starts[e - 1])
                _resolve_absolute(document, f"/eras/{e}/start", era_starts[e - 1])
            eras.append(era)
        definition["eras"] = eras
    if draw(st.booleans()):
        num = draw(st.integers(1, 10**7))
        den = draw(st.sampled_from([1, 1, 3, 100]))
        froms = sorted(draw(st.sets(st.integers(1, 15), max_size=3)))
        phases = [{"name": "Zero", "from": {"num": "0", "den": "1"}}] + [
            {"name": f"P{f}", "from": _rational(f, 16)} for f in froms
        ]
        definition["overlays"] = [
            {
                "id": "moon",
                "name": "Moon",
                "period": _rational(num, den),
                "epoch": _absolute(0),
                "phases": phases,
            }
        ]
        _resolve_absolute(document, "/overlays/0/epoch", draw(moments))
    return document


def _rational(num: int, den: int) -> Json:
    divisor = math.gcd(num, den)
    return {"num": str(num // divisor), "den": str(den // divisor)}


# --- cycles ------------------------------------------------------------------------------------


def compile_document(document: Json) -> CompiledCalendar | None:
    result = validate_calendar(document["definition"], document["context"])
    return result if isinstance(result, CompiledCalendar) else None


def _field_value(level: Json) -> str:
    """A ``to_fields`` level as a date field: the slot id, else the regular number."""
    value = level.get("id") or level["n"]
    assert isinstance(value, str)
    return value


def fields_of(document: Json, t: int, precision: str) -> Json | None:
    """The date fields (top level down to ``precision``) of the unit containing ``t``."""
    found = run_op("to_fields", document, {"t": str(t)})
    if "error" in found:
        return None
    fields: Json = {}
    for level_id, level in found["levels"].items():
        fields[level_id] = _field_value(level)
        if level_id == precision:
            break
    return fields


@st.composite
def _cycle(draw: st.DrawFn, document: Json, r: int, cycle_id: str) -> Json:
    levels = [level["id"] for level in document["definition"]["levels"]]
    position = draw(st.integers(0, len(levels) - 2))
    length = draw(st.integers(1, 7))
    cycle: Json = {"id": cycle_id, "level": levels[position], "length": length}
    if draw(st.booleans()):
        cycle["names"] = [f"N{i}" for i in range(length)]
    if draw(st.booleans()):
        cycle["ids"] = [f"v{i}" for i in range(length)]
    if draw(st.booleans()):
        cycle["number_start"] = draw(st.sampled_from([0, 1]))
    index = draw(st.integers(0, length - 1))
    if draw(st.integers(0, 2)) == 0:
        cycle["mode"] = {"reset": draw(st.sampled_from(levels[position + 1 :]))}
        cycle["anchor"] = {"index": index}
        return cycle
    duration = int(document["context"]["dimension_duration"])
    anchor = fields_of(document, draw(st.integers(0, duration)), levels[position])
    if anchor is not None:
        cycle["anchor"] = {"fields": anchor, "index": index}
    if r > 0 and draw(st.booleans()):
        cycle["continue_from_previous_regime"] = True
    return cycle


@st.composite
def _format(draw: st.DrawFn, definition: Json, cycles: Sequence[str]) -> str:
    """A format pattern of valid tokens and literal text (§3.11)."""
    levels = [level["id"] for level in definition["levels"]]
    tokens = [f"{{{level}}}" for level in levels]
    tokens += [f"{{{level}:{m}}}" for level in levels for m in ("pad2", "pad3", "ordinal")]
    tokens += [f"{{{level}.{part}}}" for level in levels for part in ("name", "abbr", "id")]
    tokens += ["{year}", "{era_year}", "{era}", "{era.name}", "{base}", "{base:pad3}"]
    tokens += [f"{{cycle.{c}{part}}}" for c in cycles for part in ("", ".abbr", ".n")]
    if definition.get("overlays"):
        tokens += ["{overlay.moon}", "{overlay.moon.fraction}"]
    pieces = st.one_of(st.sampled_from(tokens), st.sampled_from([" ", ", ", "/", "{{", "}}", "x"]))
    return "".join(draw(st.lists(pieces, min_size=1, max_size=6)))


@st.composite
def _presentation(draw: st.DrawFn, document: Json) -> Json:
    """``document`` with random ``formats`` and ``display`` options (each half the time)."""
    definition = document["definition"]
    cycles = sorted(
        {cycle["id"] for regime in definition["regimes"] for cycle in regime.get("cycles", [])}
    )
    levels = [level["id"] for level in definition["levels"]]
    if draw(st.booleans()):
        formats: Json = {
            level: draw(_format(definition, cycles))
            for level in draw(st.lists(st.sampled_from(levels), unique=True, max_size=3))
        }
        if draw(st.booleans()):
            level = draw(st.sampled_from(levels))
            formats["intercalary"] = {level: draw(_format(definition, cycles))}
        definition["formats"] = formats
    if draw(st.booleans()):
        definition["display"] = draw(
            st.fixed_dictionaries(
                {},
                optional={
                    "circa": st.sampled_from(["", "~", "c. "]),
                    "digit_group": st.sampled_from(["", ",", " ", "."]),
                    "scientific_threshold": st.integers(1, 30),
                    "significant_digits": st.integers(1, 8),
                    "range_separator": st.sampled_from([" - ", "..", ""]),
                },
            )
        )
    return document


@st.composite
def calendars(draw: st.DrawFn) -> Json:
    """A calendar document ``{definition, context}``, usually (not always) valid."""
    document = draw(_presentation(draw(_structure())))
    if compile_document(document) is None or not draw(st.integers(0, 3)):
        return document
    with_cycles = copy.deepcopy(document)
    for r, regime in enumerate(with_cycles["definition"]["regimes"]):
        ids = draw(st.lists(st.sampled_from(["week", "tide"]), max_size=2, unique=True))
        regime["cycles"] = [draw(_cycle(document, r, cycle_id)) for cycle_id in ids]
        named = [
            child
            for template in regime["templates"].values()
            for child in template.get("sequence", [])
            if "id" in child
        ]
        exclude = draw(st.booleans())
        if ids and named and exclude:
            draw(st.sampled_from(named))["cycle_excluded"] = [draw(st.sampled_from(ids))]
    if draw(st.booleans()):  # formats with cycle tokens
        with_cycles = draw(_presentation(with_cycles))
    # A cycle can still be invalid (an excluded anchor, a previous regime without that cycle):
    # both engines must agree on that too, but most examples should exercise valid cycles.
    if compile_document(with_cycles) is None and draw(st.integers(0, 3)):
        return document
    return with_cycles


# --- corrupted documents (for `validate`) -----------------------------------------------------

_JUNK: tuple[Any, ...] = ("", "0", "-1", "1", "zz", "year", "l0", "t0_0", 0, -1, None, [], {})


def _paths(value: Any, path: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
    """Every member and element path in a JSON document."""
    found = [path] if path else []
    if isinstance(value, dict):
        for key, child in value.items():
            found += _paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += _paths(child, (*path, index))
    return found


@st.composite
def corrupted(draw: st.DrawFn, document: Json) -> Json:
    """``document`` with one to three random edits: a member or element removed, a value
    replaced by junk, or an element duplicated (both engines must report the same errors)."""
    result = copy.deepcopy(document)
    for _ in range(draw(st.integers(1, 3))):
        # Inside the definition and context: the op input itself keeps its shape.
        path = draw(st.sampled_from([p for p in _paths(result) if len(p) > 1]))
        parent: Any = result
        for key in path[:-1]:
            parent = parent[key]
        last = path[-1]
        edit = draw(st.sampled_from(["delete", "replace", "replace", "duplicate"]))
        if edit == "delete":
            del parent[last]
        elif edit == "duplicate" and isinstance(parent, list) and isinstance(last, int):
            parent.insert(last, copy.deepcopy(parent[last]))
        else:
            parent[last] = copy.deepcopy(draw(st.sampled_from(_JUNK)))
        if not any(len(p) > 1 for p in _paths(result)):
            break
    return result


# --- ops on a calendar -------------------------------------------------------------------------


class Calendar:
    """What the op strategies need to know about a valid calendar document."""

    def __init__(self, document: Json) -> None:
        self.document = document
        definition = document["definition"]
        context = document["context"]
        self.duration = int(context["dimension_duration"])
        self.levels: list[str] = [level["id"] for level in definition["levels"]]
        self.cycles = sorted(
            {cycle["id"] for regime in definition["regimes"] for cycle in regime.get("cycles", [])}
        )
        self.eras = [era["id"] for era in definition.get("eras", [])]
        self.regimes = [regime["id"] for regime in definition["regimes"]]
        self.overlays = definition.get("overlays", [])
        self.slots = sorted(
            {
                child["id"]
                for regime in definition["regimes"]
                for template in regime["templates"].values()
                for child in template.get("sequence", [])
                if "id" in child
            }
        )
        # Moments where things change: regime and era starts, alignments, overlay epochs.
        self.special = sorted({int(t) for t in context["resolved"].values()} | {0, self.duration})

    def moments(self) -> st.SearchStrategy[int]:
        near = st.builds(
            lambda t, delta: min(max(t + delta, 0), self.duration),
            st.sampled_from(self.special),
            st.integers(-(10**4), 10**4),
        )
        return st.one_of(st.integers(0, self.duration), near)

    def precisions(self) -> st.SearchStrategy[str]:
        return st.sampled_from(self.levels)


@st.composite
def _perturbed(draw: st.DrawFn, calendar: Calendar, fields: Json) -> Json:
    """Mostly valid fields; sometimes a number moved or a slot swapped (errors, constrain)."""
    if not draw(st.integers(0, 2)):
        return fields
    changed = dict(fields)
    level = draw(st.sampled_from(sorted(changed)))
    value = changed[level]
    if value.lstrip("-").isdigit() and draw(st.booleans()):
        changed[level] = str(int(value) + draw(st.sampled_from([-1, 1, 2, 40, -(10**30)])))
    elif calendar.slots:
        changed[level] = draw(st.sampled_from([*calendar.slots, "zz"]))
    return changed


@st.composite
def _fields(draw: st.DrawFn, calendar: Calendar, precision: str) -> Json:
    fields = fields_of(calendar.document, draw(calendar.moments()), precision)
    if fields is None:
        return {calendar.levels[-1]: str(draw(st.integers(-(10**6), 10**6)))}
    return draw(_perturbed(calendar, fields))


def _case(op: str, data: Json) -> Json:
    return {"op": op, "input": data}


@st.composite
def _from_fields(draw: st.DrawFn, calendar: Calendar) -> Json:
    precision = draw(calendar.precisions())
    data: Json = {"fields": draw(_fields(calendar, precision)), "precision": precision}
    with_era = draw(st.booleans())
    if calendar.eras and with_era:
        data["era"] = draw(st.sampled_from(calendar.eras))
        found = run_op("to_fields", calendar.document, {"t": str(draw(calendar.moments()))})
        era = found.get("era") if isinstance(found, dict) else None
        if era is not None and draw(st.booleans()):
            data["era"] = era["id"]
            data["fields"][calendar.levels[-1]] = era["year"]
    if len(calendar.regimes) > 1 and draw(st.integers(0, 2)) == 0:
        data["regime"] = draw(st.sampled_from(calendar.regimes))
    overflow = draw(st.sampled_from([None, "reject", "constrain"]))
    if overflow is not None:
        data["overflow"] = overflow
    return _case("from_fields", data)


@st.composite
def _options(draw: st.DrawFn, calendar: Calendar) -> Json:
    position = draw(st.integers(0, len(calendar.levels) - 1))
    level = calendar.levels[position]
    fields: Json = {}
    if position < len(calendar.levels) - 1:
        fields = draw(_fields(calendar, calendar.levels[position + 1]))
    return _case("options", {"fields": fields, "level": level})


@st.composite
def _ordinals(draw: st.DrawFn, calendar: Calendar) -> Json:
    level = draw(calendar.precisions())
    t = draw(calendar.moments())
    if draw(st.booleans()):
        return _case("ordinal", {"t": str(t), "level": level})
    found = run_op("ordinal", calendar.document, {"t": str(t), "level": level})
    base = int(found["ordinal"]) if "ordinal" in found else 0
    value = base + draw(st.integers(-3, 3))
    return _case("from_ordinal", {"level": level, "ordinal": str(value)})


@st.composite
def _duration(draw: st.DrawFn, calendar: Calendar) -> Json:
    if draw(st.integers(0, 3)) == 0:
        return {"kind": "base", "units": str(draw(st.integers(-(10**9), 10**9)))}
    levels = draw(st.lists(calendar.precisions(), min_size=1, max_size=3, unique=True))
    amounts = st.one_of(st.integers(0, 40), st.integers(0, 10**12))
    return {
        "kind": "calendar",
        "calendar_id": "cal",
        "amounts": {level: str(draw(amounts)) for level in levels},
        "sign": draw(st.sampled_from([1, -1])),
    }


@st.composite
def _add(draw: st.DrawFn, calendar: Calendar) -> Json:
    data: Json = {"t": str(draw(calendar.moments())), "duration": draw(_duration(calendar))}
    overflow = draw(st.sampled_from([None, "reject", "constrain"]))
    if overflow is not None:
        data["overflow"] = overflow
    return _case("add", data)


@st.composite
def _diff(draw: st.DrawFn, calendar: Calendar) -> Json:
    largest, smallest = sorted(
        draw(st.lists(st.integers(0, len(calendar.levels) - 1), min_size=2, max_size=2)),
        reverse=not draw(st.integers(0, 9)),  # occasionally inverted: invalid_date
    )
    return _case(
        "diff",
        {
            "t1": str(draw(calendar.moments())),
            "t2": str(draw(calendar.moments())),
            "largest": calendar.levels[largest],
            "smallest": calendar.levels[smallest],
        },
    )


@st.composite
def _display_point(draw: st.DrawFn, calendar: Calendar) -> Json | None:
    if draw(st.integers(0, 4)) == 0:
        return None
    return {
        "t": str(draw(calendar.moments())),
        "precision": draw(st.sampled_from([*calendar.levels, "base"])),
        "approximate": draw(st.booleans()),
    }


@st.composite
def _overlay(draw: st.DrawFn, calendar: Calendar) -> Json:
    overlay = draw(st.sampled_from(["moon", "moon", "nope"]))
    t = str(draw(calendar.moments()))
    if draw(st.booleans()):
        return _case("overlay_phase", {"t": t, "overlay": overlay})
    num = draw(st.integers(0, 15))
    return _case("next_phase_at", {"t": t, "overlay": overlay, "phase": _rational(num, 16)})


@st.composite
def calendar_ops(draw: st.DrawFn, calendar: Calendar) -> Json:
    """One op on ``calendar``."""
    t = st.builds(str, calendar.moments())
    choices: list[st.SearchStrategy[Json]] = [
        st.builds(lambda t: _case("to_fields", {"t": t}), t),
        _from_fields(calendar),
        st.builds(
            lambda t, level: _case("unit_bounds", {"t": t, "level": level}),
            t,
            calendar.precisions(),
        ),
        _ordinals(calendar),
        _options(calendar),
        _add(calendar),
        _diff(calendar),
        st.builds(
            lambda t, precision, approximate: _case(
                "format", {"t": t, "precision": precision, "approximate": approximate}
            ),
            t,
            st.sampled_from([*calendar.levels, "base"]),
            st.booleans(),
        ),
        st.builds(
            lambda start, end: _case("format_span", {"start": start, "end": end}),
            _display_point(calendar),
            _display_point(calendar),
        ),
        _recurrence(calendar),
    ]
    if calendar.cycles:
        choices.append(
            st.builds(
                lambda t, cycle: _case("cycle_value", {"t": t, "cycle": cycle}),
                t,
                st.sampled_from([*calendar.cycles, "nope"]),
            )
        )
    if calendar.eras:
        choices.append(st.builds(lambda t: _case("era_of", {"t": t}), t))
    if calendar.overlays:
        choices.append(_overlay(calendar))
    return draw(draw(st.sampled_from(choices)))


# --- recurrence --------------------------------------------------------------------------------


@st.composite
def _limit(draw: st.DrawFn, moments: st.SearchStrategy[int], resolved: Json) -> Json:
    kind = draw(st.sampled_from(["never", "count", "until"]))
    if kind == "count":
        count = draw(st.one_of(st.integers(1, 20), st.integers(1, 10**12)))
        return {"kind": "count", "count": str(count)}
    if kind == "until":
        resolved["/limit/until"] = str(draw(moments))
        return {"kind": "until", "until": _absolute(0)}
    return {"kind": "never"}


@st.composite
def _exclusions(draw: st.DrawFn, moments: st.SearchStrategy[int], resolved: Json) -> list[Json]:
    exclusions = []
    for i in range(draw(st.integers(0, 2) if draw(st.integers(0, 3)) == 0 else st.just(0))):
        start = draw(moments)
        end = start + draw(st.integers(-10, 10**8))  # `to < from` is rule.bad_exclusion
        resolved[f"/exclusions/{i}/from"] = str(start)
        resolved[f"/exclusions/{i}/to"] = str(max(end, 0))
        exclusions.append({"from": _absolute(0), "to": _absolute(0)})
    return exclusions


@st.composite
def _end(draw: st.DrawFn) -> Json:
    kind = draw(st.sampled_from(["instant", "duration", "unknown"]))
    if kind == "duration":
        units = str(draw(st.integers(0, 10**6)))
        return {"kind": "duration", "duration": {"kind": "base", "units": units}}
    return {"kind": kind}


@st.composite
def _values(draw: st.DrawFn, calendar: Calendar, cycle: bool = False) -> list[str]:
    pool = [str(n) for n in range(-2, 13) if n != 0]
    if cycle:
        pool += [f"v{i}" for i in range(7)]
    else:
        pool += [*calendar.slots, "0"]
    return draw(st.lists(st.sampled_from(pool), min_size=1, max_size=3, unique=True))


@st.composite
def _filter(draw: st.DrawFn, calendar: Calendar, depth: int = 0) -> Json:
    kinds = ["mod", "in"] + (["cycle"] if calendar.cycles else [])
    kind = draw(st.sampled_from(kinds + (["all", "any", "not"] if depth < 1 else [])))
    if kind == "mod":
        mod = draw(st.sampled_from(MODS))
        found: Json = {"mod": str(mod), "eq": str(draw(st.integers(0, mod)))}  # eq = mod: error
        if draw(st.booleans()):
            found["of"] = draw(st.sampled_from(["number", "ordinal"]))
        return found
    if kind == "in":
        return {"in": draw(_values(calendar))}
    if kind == "cycle":
        cycle = draw(st.sampled_from(calendar.cycles))
        return {"cycle": cycle, "in": draw(_values(calendar, cycle=True))}
    if kind == "not":
        return {"not": draw(_filter(calendar, depth + 1))}
    return {kind: draw(st.lists(_filter(calendar, depth + 1), min_size=1, max_size=2))}


@st.composite
def _selector(draw: st.DrawFn, calendar: Calendar, below: int) -> Json | None:
    """A selector path inside a period at level index ``below`` (``None``: no selector)."""
    if below == 0 or draw(st.booleans()):
        return None
    positions = sorted(
        draw(st.lists(st.integers(0, below - 1), min_size=1, max_size=2, unique=True)),
        reverse=True,
    )
    path = []
    for position in positions:
        level = calendar.levels[position]
        kind = draw(
            st.sampled_from(["values", "values", "all"] + (["cycle"] * bool(calendar.cycles)))
        )
        if kind == "all":
            path.append({"level": level, "all": True})
        elif kind == "cycle":
            match: Json = {
                "id": draw(st.sampled_from(calendar.cycles)),
                "values": draw(_values(calendar, cycle=True)),
            }
            if draw(st.booleans()):
                match["nth"] = draw(
                    st.lists(st.sampled_from(["1", "2", "-1", "0"]), min_size=1, max_size=2)
                )
            path.append({"level": level, "cycle": match})
        else:
            path.append({"level": level, "values": draw(_values(calendar))})
    return {"path": path}


@st.composite
def _calendar_rule(draw: st.DrawFn, calendar: Calendar, resolved: Json) -> Json:
    moments = calendar.moments()
    rule: Json = {"kind": "calendar", "calendar_id": "cal"}
    if calendar.cycles and draw(st.integers(0, 4)) == 0:
        rule["freq"] = {"cycle": draw(st.sampled_from(calendar.cycles))}
        below = len(calendar.levels) - 1
    else:
        below = draw(st.integers(0, len(calendar.levels) - 1))
        rule["freq"] = {"level": calendar.levels[below]}
    if draw(st.booleans()):
        rule["interval"] = str(draw(st.sampled_from([1, 2, 3, 7, 10**9])))
    if draw(st.integers(0, 2)) == 0:
        rule["filters"] = draw(st.lists(_filter(calendar), min_size=1, max_size=2))
    selector = draw(_selector(calendar, below))
    if selector is not None:
        rule["select"] = selector
    if draw(st.booleans()):
        rule["missing"] = draw(st.sampled_from(["skip", "constrain"]))
    if below > 0 and draw(st.integers(0, 3)) == 0:
        rule["time"] = {"fields": {calendar.levels[0]: str(draw(st.integers(0, 3)))}}
    rule["limit"] = draw(_limit(moments, resolved))
    exclusions = draw(_exclusions(moments, resolved))
    if exclusions:
        rule["exclusions"] = exclusions
    return rule


@st.composite
def _recurrence(draw: st.DrawFn, calendar: Calendar) -> Json:
    resolved: Json = {}
    rule = draw(_calendar_rule(calendar, resolved))
    context: Json = {
        "rule": rule,
        "series_start": str(draw(calendar.moments())),
        "end": draw(_end()),
        "resolved": resolved,
    }
    return draw(_recurrence_op(context, calendar.document, calendar.moments(), calendar.duration))


@st.composite
def _recurrence_op(
    draw: st.DrawFn,
    context: Json,
    calendar: Json | None,
    moments: st.SearchStrategy[int],
    duration: int,
) -> Json:
    op = draw(
        st.sampled_from(
            [
                "expand",
                "expand",
                "series_bounds",
                "occurrence",
                "count_in_window",
                "occurrence_number",
                "occurrence_at",
            ]
        )
    )
    data = dict(context)
    start = int(context["series_start"])
    if op in ("expand", "count_in_window"):
        w0 = draw(st.one_of(moments, st.integers(start, min(start + 10**6, duration))))
        width = draw(st.one_of(st.integers(0, 10**6), st.integers(0, duration)))
        data["window"] = [str(w0), str(min(w0 + width, duration))]
        if op == "expand":
            data["max_items"] = draw(st.sampled_from([1, 10, 100]))
    elif op == "occurrence_at":
        data["t"] = str(draw(moments))
    elif op in ("occurrence", "occurrence_number"):
        found = run_op("occurrence_at", calendar, {**context, "t": str(draw(moments))})
        key = found.get("key") if isinstance(found, dict) else None
        if key is None or draw(st.integers(0, 3)) == 0:
            key = str(draw(st.integers(0, 10**6)))
        data["key"] = key
    return _case(op, data)


# --- calendar-free ops -------------------------------------------------------------------------


@st.composite
def interval_ops(draw: st.DrawFn) -> Json:
    """A recurrence op on a fixed-interval rule (no calendar)."""
    duration = draw(st.sampled_from(DURATIONS))
    moments = st.integers(0, duration)
    resolved: Json = {}
    rule: Json = {
        "kind": "interval",
        "every": str(draw(st.one_of(st.integers(1, 1000), st.integers(1, duration)))),
        "limit": draw(_limit(moments, resolved)),
    }
    exclusions = draw(_exclusions(moments, resolved))
    if exclusions:
        rule["exclusions"] = exclusions
    context: Json = {
        "rule": rule,
        "series_start": str(draw(moments)),
        "end": draw(_end()),
        "resolved": resolved,
        "dimension_duration": str(duration),
    }
    return draw(_recurrence_op(context, None, moments, duration))


@st.composite
def _correspondence(draw: st.DrawFn) -> Json:
    count = draw(st.integers(1, 4))
    a = sorted(draw(st.lists(st.integers(0, 10**15), min_size=count, max_size=count)))
    b = sorted(draw(st.lists(st.integers(0, 10**15), min_size=count, max_size=count)))
    if draw(st.integers(0, 4)) == 0:
        b.reverse()  # non-monotonic
    rates = st.one_of(
        st.none(),
        st.builds(
            lambda n, d: {"num": str(n), "den": str(d)},
            st.integers(-2, 10**6),  # ≤ 0: correspondence.bad_rate
            st.integers(1, 10**6),
        ),
    )
    return {
        "extrapolation": draw(st.sampled_from(["none", "rate"])),
        "rate_before": draw(rates),
        "rate_after": draw(rates),
        "points": [{"a": str(x), "b": str(y)} for x, y in zip(a, b, strict=True)],
    }


@st.composite
def correspondence_ops(draw: st.DrawFn) -> Json:
    """A ``map`` or ``compose`` op."""
    t = str(draw(st.integers(0, 10**16)))
    durations = st.builds(str, st.sampled_from([10**15, 10**16, 10**40]))
    step = st.fixed_dictionaries(
        {
            "correspondence": _correspondence(),
            "direction": st.sampled_from(["ab", "ba"]),
            "target_duration": durations,
        }
    )
    if draw(st.booleans()):
        return _case("map", {**draw(step), "t": t})
    return _case("compose", {"path": draw(st.lists(step, max_size=3)), "t": t})


@st.composite
def number_ops(draw: st.DrawFn) -> Json:
    """Numeric utilities: integers of any size, rationals and display."""
    big = st.one_of(st.integers(-(10**6), 10**6), st.integers(-(10**80), 10**80))
    rationals = st.builds(
        lambda n, d: {"num": str(n), "den": str(d)},
        big,
        big.filter(lambda d: d != 0),
    )
    op = draw(
        st.sampled_from(
            [
                "sortable_key",
                "floor_div",
                "floor_mod",
                "rational_add",
                "rational_mul",
                "rational_div",
                "rational_compare",
                "rational_floor",
                "rational_frac",
                "format_integer",
            ]
        )
    )
    if op == "sortable_key":
        return _case(op, {"n": str(abs(draw(big)))})
    if op in ("floor_div", "floor_mod"):
        return _case(op, {"a": str(draw(big)), "b": str(draw(big))})
    if op in ("rational_floor", "rational_frac"):
        return _case(op, {"a": draw(rationals)})
    if op == "format_integer":
        data: Json = {"n": str(draw(big))}
        if draw(st.booleans()):
            data["digit_group"] = draw(st.sampled_from(["", ",", " ", "'"]))
        if draw(st.booleans()):
            data["scientific_threshold"] = draw(st.integers(1, 40))
        if draw(st.booleans()):
            data["significant_digits"] = draw(st.integers(1, 10))
        if draw(st.booleans()):
            data["plain"] = draw(st.booleans())
        return _case(op, data)
    return _case(op, {"a": draw(rationals), "b": draw(rationals)})
