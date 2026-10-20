"""Refining a dimension's base unit (``time-model.md`` §3): every quantity stored in base units,
multiplied by an integer ``factor`` (seconds → milliseconds: 1000).

Pure functions on JSON documents (as stored: integers are decimal strings). Moments and base
durations are multiplied; calendar quantities (dates, calendar durations, cycles) don't change,
since each calendar's finest level becomes ``factor`` times as many base units long.
"""

from fractions import Fraction
from typing import Any

type Json = Any

TIME_POINT_ANCHORS = frozenset({"absolute", "calendar", "relative", "local"})


class RefineError(ValueError):
    """A document the refinement can't rewrite. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _times(value: str, factor: int) -> str:
    return str(int(value) * factor)


def is_time_point(value: Json) -> bool:
    anchor = value.get("anchor") if isinstance(value, dict) else None
    return (
        isinstance(anchor, dict)
        and anchor.get("kind") in TIME_POINT_ANCHORS
        and "precision" in value
    )


def is_base_duration(value: Json) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") == "base"
        and isinstance(value.get("units"), str)
        and set(value) == {"kind", "units"}
    )


def refine_point(point: Json, factor: int) -> Json:
    """A time point (``range`` ends and ``frozen_from`` included): absolute moments and base
    offsets times ``factor``. Calendar and local anchors don't change."""
    out = dict(point)
    anchor = dict(point["anchor"])
    if anchor["kind"] == "absolute":
        anchor["t"] = _times(anchor["t"], factor)
    elif anchor["kind"] == "relative":
        anchor["offset"] = refine_json(anchor["offset"], factor)
    out["anchor"] = anchor
    if isinstance(point.get("range"), dict):
        out["range"] = {
            name: refine_point(end, factor) if is_time_point(end) else end
            for name, end in point["range"].items()
        }
    if is_time_point(point.get("frozen_from")):
        out["frozen_from"] = refine_point(point["frozen_from"], factor)
    return out


def refine_json(value: Json, factor: int) -> Json:
    """Any document: its time points and base durations rewritten (end specs, field values,
    rich text with ``timeRef`` nodes), everything else as it was."""
    if is_time_point(value):
        return refine_point(value, factor)
    if is_base_duration(value):
        return {"kind": "base", "units": _times(value["units"], factor)}
    if isinstance(value, dict):
        return {key: refine_json(item, factor) for key, item in value.items()}
    if isinstance(value, list):
        return [refine_json(item, factor) for item in value]
    return value


def refine_rule(rule: Json, factor: int) -> Json:
    """A recurrence rule: an interval rule's ``every``, and the time points of its limit and
    exclusions."""
    out = refine_json(rule, factor)
    if out.get("kind") == "interval":
        out["every"] = _times(out["every"], factor)
    return out


def refine_moments(moments: Json, factor: int) -> Json:
    """A ``{pointer: moment}`` map (resolved anchors of calendars and rules)."""
    return {key: _times(t, factor) for key, t in moments.items()}


def refine_rate(rate: Json, numerator: int = 1, denominator: int = 1) -> Json:
    """A ``{num, den}`` rational times ``numerator / denominator``, normalized."""
    value = Fraction(int(rate["num"]), int(rate["den"])) * numerator / denominator
    return {"num": str(value.numerator), "den": str(value.denominator)}


def refine_definition(definition: Json, factor: int) -> Json:
    """A calendar definition: the finest level's templates (their counts are base units),
    absolute and base-offset anchors, and overlay periods (in base units)."""
    out: Json = refine_json(definition, factor)
    levels = [level["id"] for level in out["levels"]]
    finest = levels[0]
    for regime in out["regimes"]:
        for template_id, template in regime["templates"].items():
            if template["level"] != finest:
                continue
            regime["templates"][template_id] = _refine_template(template_id, template, factor)
    for overlay in out.get("overlays", []):
        overlay["period"] = refine_rate(overlay["period"], factor)
    return out


def _refine_template(template_id: str, template: Json, factor: int) -> Json:
    if "uniform" in template:
        uniform = dict(template["uniform"])
        uniform["count"] = _times(uniform["count"], factor)
        return {**template, "uniform": uniform}
    sequence = []
    for child in template["sequence"]:
        if "run" not in child:
            raise RefineError(
                "refine.named_base_units",
                f"template {template_id!r} names its base units one by one",
            )
        run = dict(child["run"])
        run["count"] = _times(run["count"], factor)
        sequence.append({**child, "run": run})
    return {**template, "sequence": sequence}


__all__ = [
    "RefineError",
    "is_base_duration",
    "is_time_point",
    "refine_definition",
    "refine_json",
    "refine_moments",
    "refine_point",
    "refine_rate",
    "refine_rule",
]
