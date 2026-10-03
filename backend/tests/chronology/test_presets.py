"""Preset calendars (chronology-engine.md §13); vectors: cases/presets/."""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from lore.chronology.calendar import CompiledCalendar, compile_calendar
from lore.chronology.presets import (
    PresetError,
    absolute_moments,
    instantiate_preset,
    load_presets,
)
from lore.chronology.schema import BaseUnit, CompileContext, Preset
from lore.config import Settings

REQUIRED = {
    "alternating-years",
    "gregorian",
    "julian",
    "julian-gregorian",
    "lunisolar-metonic",
    "mayan",
    "shire-reckoning",
    "simple-360",
}


def _spec_dir() -> Path:
    """``LORE_SPEC_DIR`` (auto-detected in the repository), where the runtime reads presets."""
    spec_dir = Settings().spec_dir
    assert spec_dir is not None
    return spec_dir


SPEC_DIR = _spec_dir()
PRESETS = load_presets(SPEC_DIR)
CALENDARS = SPEC_DIR / "chronology" / "conformance" / "calendars"
BASE_UNITS = [Fraction(1, 1000), Fraction(1), Fraction(60), Fraction(3600), Fraction(86400)]


def compile_preset(preset: Preset, seconds: Fraction, origin: int = 0) -> CompiledCalendar:
    definition = instantiate_preset(preset, seconds, origin=origin)
    context = CompileContext(
        base_unit=BaseUnit(singular="unit", plural="units", abbr="u"),
        dimension_duration=str(10**120),
        resolved=absolute_moments(definition),
    )
    result = compile_calendar(definition, context)
    assert isinstance(result, CompiledCalendar), result
    return result


def test_the_required_presets_load_from_the_spec_dir() -> None:
    assert set(PRESETS) == REQUIRED
    for preset_id, preset in PRESETS.items():
        assert preset.id == preset_id
        level0 = preset.definition.levels[0]
        assert level0.id == "second"
        for regime in preset.definition.regimes:
            template = regime.templates[level0.default_template or ""]
            assert template.model_dump(exclude_unset=True) == {
                "level": "second",
                "uniform": {"count": "1"},
            }


@pytest.mark.parametrize("preset_id", sorted(REQUIRED))
@pytest.mark.parametrize("seconds", BASE_UNITS, ids=str)
def test_every_preset_compiles_for_common_base_units(preset_id: str, seconds: Fraction) -> None:
    compile_preset(PRESETS[preset_id], seconds, origin=10**12)


@pytest.mark.parametrize("preset_id", sorted(REQUIRED))
def test_requires_covers_the_absolute_anchors(preset_id: str) -> None:
    preset = PRESETS[preset_id]
    moments = absolute_moments(instantiate_preset(preset, Fraction(1)))
    assert preset.requires.duration_seconds == max(moments.values(), key=int)


@pytest.mark.parametrize("preset_id", sorted(REQUIRED))
def test_conformance_calendar_files_match_the_presets(preset_id: str) -> None:
    document = json.loads((CALENDARS / f"preset-{preset_id}.json").read_text(encoding="utf-8"))
    definition = instantiate_preset(PRESETS[preset_id], Fraction(1), origin=10**14)
    assert document["definition"] == definition.model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )
    assert document["context"]["resolved"] == absolute_moments(definition)


def test_dropping_a_level_a_date_needs_is_incompatible() -> None:
    document = PRESETS["simple-360"].model_dump(mode="json", by_alias=True, exclude_unset=True)
    document["definition"]["regimes"][0]["alignment"]["fields"]["hour"] = "6"
    preset = Preset.model_validate(document)
    assert compile_preset(preset, Fraction(1)) is not None
    with pytest.raises(PresetError) as error:
        instantiate_preset(preset, Fraction(86400))
    assert error.value.code == "preset.incompatible_base_unit"


def test_load_presets_reads_a_given_directory(tmp_path: Path) -> None:
    (tmp_path / "chronology" / "presets").mkdir(parents=True)
    source = SPEC_DIR / "chronology" / "presets" / "julian.json"
    (tmp_path / "chronology" / "presets" / "julian.json").write_text(source.read_text("utf-8"))
    assert list(load_presets(tmp_path)) == ["julian"]
