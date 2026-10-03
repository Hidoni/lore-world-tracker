"""Preset calendars and their instantiation for a dimension (``chronology-engine.md`` §13).

Presets live in ``<spec dir>/chronology/presets/<id>.json``. They are written in seconds (level 0
is ``second`` with ``uniform.count = 1``) and their absolute time points are seconds after the
origin. Instantiating one for a base unit of ``p/q`` seconds keeps the first level whose
templates all last a whole number of base units, turns it into level 0 and drops the finer
levels; absolute moments become ``origin + floor(seconds·q/p)`` and overlay periods are scaled
exactly.
"""

from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from lore.chronology.calendar import formats
from lore.chronology.schema import CalendarDefinition, Preset

type Json = dict[str, Any]
type PresetErrorCode = Literal["preset.incompatible_base_unit"]


class PresetError(ValueError):
    """A preset that can't be instantiated as asked."""

    def __init__(self, code: PresetErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: PresetErrorCode = code


def presets_dir(spec_dir: Path) -> Path:
    return spec_dir / "chronology" / "presets"


def load_presets(spec_dir: Path) -> dict[str, Preset]:
    """Every preset under ``spec_dir`` (``LORE_SPEC_DIR``), by id, in id order."""
    found = [
        Preset.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(presets_dir(spec_dir).glob("*.json"))
    ]
    return {preset.id: preset for preset in sorted(found, key=lambda p: p.id)}


def instantiate_preset(
    preset: Preset, seconds_per_base_unit: Fraction, *, origin: int = 0
) -> CalendarDefinition:
    """The preset's definition for a dimension whose base unit lasts ``seconds_per_base_unit``.

    ``origin`` is the moment (in base units) at which the preset's alignment unit starts, e.g.
    the start of 1 January AD 1 for the Gregorian preset. Raises
    ``preset.incompatible_base_unit`` when no level lasts a whole number of base units in every
    template, or when the levels to drop are needed (a cycle on them, or a date that isn't at the
    start of such a unit).
    """
    if seconds_per_base_unit <= 0:
        raise PresetError("preset.incompatible_base_unit", "a base unit must be longer than 0")
    p, q = seconds_per_base_unit.numerator, seconds_per_base_unit.denominator
    definition: Json = preset.definition.model_dump(mode="json", by_alias=True, exclude_unset=True)
    levels = [level["id"] for level in definition["levels"]]
    lengths = [_template_lengths(definition, regime) for regime in definition["regimes"]]
    keep = next(
        (
            i
            for i, level in enumerate(levels)
            if all(
                length * q % p == 0
                for regime, by_id in zip(definition["regimes"], lengths, strict=True)
                for template_id, length in by_id.items()
                if regime["templates"][template_id]["level"] == level
            )
        ),
        None,
    )
    if keep is None:
        raise PresetError(
            "preset.incompatible_base_unit",
            f"no level of {preset.id!r} lasts a whole number of {seconds_per_base_unit} s units",
        )
    dropped = {level: definition["levels"][i] for i, level in enumerate(levels[:keep])}
    definition["levels"] = definition["levels"][keep:]
    for regime, by_id in zip(definition["regimes"], lengths, strict=True):
        _scale_regime(regime, by_id, levels[keep], dropped, seconds_per_base_unit)
    for fields in _structural_fields(definition):
        _drop_fields(fields, dropped)
    for point in _time_points(definition):
        anchor = point["anchor"]
        if anchor["kind"] == "local":
            _drop_fields(anchor["fields"], dropped)
        elif anchor["kind"] == "absolute":
            anchor["t"] = str(origin + int(anchor["t"]) * q // p)
        if point["precision"] in dropped:
            point["precision"] = levels[keep]
    for overlay in definition.get("overlays", []):
        period = Fraction(int(overlay["period"]["num"]), int(overlay["period"]["den"])) * q / p
        overlay["period"] = {"num": str(period.numerator), "den": str(period.denominator)}
    _drop_formats(definition, set(dropped))
    return CalendarDefinition.model_validate(definition)


def absolute_moments(definition: CalendarDefinition) -> dict[str, str]:
    """``CompileContext.resolved`` for a definition whose non-local anchors are all absolute."""
    document = definition.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return {
        pointer: point["anchor"]["t"]
        for pointer, point in _pointed_time_points(document)
        if point["anchor"]["kind"] == "absolute"
    }


# --- helpers -------------------------------------------------------------------------------------


def _template_lengths(definition: Json, regime: Json) -> dict[str, int]:
    """Length in seconds (level-0 children are one second each) of every template."""
    levels = [level["id"] for level in definition["levels"]]
    defaults = {level["id"]: level.get("default_template") for level in definition["levels"]}
    templates: dict[str, Json] = regime["templates"]
    memo: dict[str, int] = {}

    def length(template_id: str) -> int:
        if template_id not in memo:
            template = templates[template_id]
            index = levels.index(template["level"])

            def child(layout: Json) -> int:
                if index == 0:
                    return 1
                return length(layout.get("template") or defaults[levels[index - 1]])

            if "uniform" in template:
                memo[template_id] = int(template["uniform"]["count"]) * child(template["uniform"])
            else:
                memo[template_id] = sum(
                    int(item["run"]["count"]) * child(item["run"]) if "run" in item else child(item)
                    for item in template["sequence"]
                )
        return memo[template_id]

    return {template_id: length(template_id) for template_id in templates}


def _scale_regime(
    regime: Json, lengths: dict[str, int], level0: str, dropped: dict[str, Json], unit: Fraction
) -> None:
    for cycle in regime.get("cycles", []):
        if cycle["level"] in dropped:
            raise PresetError(
                "preset.incompatible_base_unit", f"cycle {cycle['id']!r} needs {cycle['level']!r}"
            )
    templates: dict[str, Json] = {}
    for template_id, template in regime["templates"].items():
        if template["level"] in dropped:
            continue
        if template["level"] == level0:
            count = lengths[template_id] / unit
            assert count.denominator == 1  # the level was chosen for it
            templates[template_id] = {"level": level0, "uniform": {"count": str(count.numerator)}}
        else:
            templates[template_id] = template
    regime["templates"] = templates


def _drop_fields(fields: Json, dropped: dict[str, Json]) -> None:
    """Remove the dropped levels from date fields; they must name the first unit."""
    for level, value in list(fields.items()):
        if level not in dropped:
            continue
        if value != str(dropped[level].get("numbering_start", 1)):
            raise PresetError(
                "preset.incompatible_base_unit", f"a date needs {level} {value}, finer than a unit"
            )
        del fields[level]


def _structural_fields(definition: Json) -> Iterator[Json]:
    """The date fields of alignments and cycle anchors (time points come separately)."""
    for regime in definition["regimes"]:
        yield regime["alignment"]["fields"]
        for cycle in regime.get("cycles", []):
            anchor = cycle.get("anchor")
            if anchor is not None and "fields" in anchor:
                yield anchor["fields"]


def _pointed_time_points(definition: Json) -> Iterator[tuple[str, Json]]:
    """(JSON pointer, time point) for every time point of a definition (§3.10)."""
    for r, regime in enumerate(definition["regimes"]):
        yield f"/regimes/{r}/alignment/at", regime["alignment"]["at"]
        if regime.get("starts_at") is not None:
            yield f"/regimes/{r}/starts_at", regime["starts_at"]
    for e, era in enumerate(definition.get("eras", [])):
        if era.get("start") is not None:
            yield f"/eras/{e}/start", era["start"]
    for o, overlay in enumerate(definition.get("overlays", [])):
        yield f"/overlays/{o}/epoch", overlay["epoch"]


def _time_points(definition: Json) -> Iterator[Json]:
    return (point for _, point in _pointed_time_points(definition))


def _drop_formats(definition: Json, dropped: set[str]) -> None:
    """Remove the formats of dropped precisions and the patterns using dropped levels."""
    custom: Json | None = definition.get("formats")
    if custom is None:
        return

    def keep(key: str, pattern: str) -> bool:
        return key not in dropped and not any(
            isinstance(piece, formats.Token) and piece.kind == "level" and piece.id in dropped
            for piece in formats.parse(pattern)
        )

    intercalary = {k: v for k, v in custom.get("intercalary", {}).items() if keep(k, v)}
    kept: Json = {k: v for k, v in custom.items() if k != "intercalary" and keep(k, v)}
    if "intercalary" in custom:
        kept["intercalary"] = intercalary
    definition["formats"] = kept
