from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from lore.chronology import schema
from lore.chronology.schema import (
    CalendarDefinition,
    CorrespondenceDef,
    Formats,
    Rational,
    SchemaVersionError,
    TimePoint,
)

ANCHOR = TypeAdapter[Any](schema.Anchor)
DURATION = TypeAdapter[Any](schema.Duration)
END_SPEC = TypeAdapter[Any](schema.EndSpec)
RULE = TypeAdapter[Any](schema.RecurrenceRule)


def absolute(t: str) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": t}, "precision": "base"}


def minimal_definition(**changes: Any) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "schema_version": 1,
        "levels": [
            {"id": "day", "label": "day", "plural": "days"},
            {"id": "year", "label": "year", "plural": "years"},
        ],
        "regimes": [
            {
                "id": "standard",
                "name": "Standard",
                "templates": {
                    "day": {"level": "day", "uniform": {"count": "1"}},
                    "year": {"level": "year", "uniform": {"count": "365", "template": "day"}},
                },
                "top": {"pattern": {"kind": "fixed", "template": "year"}},
                "alignment": {"fields": {"year": "1"}, "at": absolute("0")},
            }
        ],
    }
    definition.update(changes)
    return definition


# --- integer strings ---------------------------------------------------------------------------


@pytest.mark.parametrize("t", ["0", "7", "1023", "9" * 1000])
def test_moment_accepts_canonical_strings(t: str) -> None:
    assert ANCHOR.validate_python({"kind": "absolute", "t": t}).t == t


@pytest.mark.parametrize(
    "t",
    ["", "01", "00", "-1", "+1", " 1", "1 ", "1.0", "1e3", "\u0661", "1" + "0" * 1000],
    ids=["empty", "leading-zero", "double-zero", "negative", "plus", "lead-space",
         "trail-space", "decimal", "exponent", "non-ascii-digit", "1001-digits"],
)  # fmt: skip
def test_moment_rejects_non_canonical_strings(t: str) -> None:
    with pytest.raises(ValidationError):
        ANCHOR.validate_python({"kind": "absolute", "t": t})


def test_moment_rejects_json_numbers() -> None:
    with pytest.raises(ValidationError):
        ANCHOR.validate_python({"kind": "absolute", "t": 5})


@pytest.mark.parametrize("units", ["0", "-1", "86400", "-" + "9" * 1000])
def test_signed_integers(units: str) -> None:
    assert DURATION.validate_python({"kind": "base", "units": units}).units == units


@pytest.mark.parametrize("units", ["-0", "-01", "--1", "-" + "1" * 1001])
def test_signed_integers_reject_non_canonical(units: str) -> None:
    with pytest.raises(ValidationError):
        DURATION.validate_python({"kind": "base", "units": units})


def test_int_of_converts_validated_strings() -> None:
    assert schema.int_of("-" + "9" * 1000) == -(10**1000 - 1)


# --- anchors and time points -------------------------------------------------------------------


def test_anchor_kinds_are_discriminated() -> None:
    calendar = ANCHOR.validate_python(
        {
            "kind": "calendar",
            "calendar_id": "01a0",
            "fields": {"year": "1023", "month": "frostfall"},
        }
    )
    assert isinstance(calendar, schema.CalendarAnchor)
    relative = ANCHOR.validate_python(
        {
            "kind": "relative",
            "ref": {"type": "event", "id": "01a0", "slot": "end", "occurrence": "57"},
            "offset": {"kind": "base", "units": "-86400"},
        }
    )
    assert isinstance(relative, schema.RelativeAnchor)
    assert relative.ref.occurrence == "57"


@pytest.mark.parametrize("kind", ["local", "range", "unknown", None])
def test_unknown_anchor_kinds_are_rejected(kind: str | None) -> None:
    with pytest.raises(ValidationError):
        ANCHOR.validate_python({"kind": kind, "fields": {"year": "1"}})


def test_local_anchor_is_valid_only_inside_definitions() -> None:
    local = {"anchor": {"kind": "local", "fields": {"year": "1"}}, "precision": "year"}
    with pytest.raises(ValidationError):
        TimePoint.model_validate(local)
    era = {
        "id": "af",
        "name": "After Founding",
        "abbr": "AF",
        "start": local,
        "numbering": {"direction": "forward", "first": "1"},
    }
    definition = CalendarDefinition.model_validate(minimal_definition(eras=[era]))
    assert isinstance(definition.eras[0].start, schema.DefinitionTimePoint)


def test_alignment_cannot_use_a_local_anchor() -> None:
    definition = minimal_definition()
    definition["regimes"][0]["alignment"]["at"] = {
        "anchor": {"kind": "local", "fields": {"year": "1"}},
        "precision": "year",
    }
    with pytest.raises(ValidationError):
        CalendarDefinition.model_validate(definition)


@pytest.mark.parametrize("model", [TimePoint, schema.DefinitionTimePoint])
def test_range_is_reserved_and_rejected(model: type[TimePoint]) -> None:
    point = absolute("5") | {"range": {"earliest": absolute("1"), "latest": absolute("9")}}
    with pytest.raises(ValidationError, match="reserved"):
        model.model_validate(point)
    with pytest.raises(ValidationError, match="reserved"):
        model.model_validate(absolute("5") | {"range": None})


def test_time_point_defaults_and_strict_flags() -> None:
    assert TimePoint.model_validate(absolute("5")).approximate is False
    with pytest.raises(ValidationError):
        TimePoint.model_validate(absolute("5") | {"approximate": "yes"})
    with pytest.raises(ValidationError):
        TimePoint.model_validate({"anchor": {"kind": "absolute", "t": "5"}})  # no precision


@pytest.mark.parametrize("value", ["1023", "-5", "0", "frostfall", "mid-year", "a_1"])
def test_field_values(value: str) -> None:
    anchor = {"kind": "calendar", "calendar_id": "c", "fields": {"year": value}}
    assert ANCHOR.validate_python(anchor).fields["year"] == value


@pytest.mark.parametrize("value", ["", "01", "-0", "Frostfall", "1a", "_x", "x y", "-x"])
def test_field_values_reject_other_strings(value: str) -> None:
    with pytest.raises(ValidationError):
        ANCHOR.validate_python({"kind": "calendar", "calendar_id": "c", "fields": {"year": value}})


@pytest.mark.parametrize("key", ["Year", "1year", "year-x", ""])
def test_field_keys_are_level_ids(key: str) -> None:
    with pytest.raises(ValidationError):
        ANCHOR.validate_python({"kind": "calendar", "calendar_id": "c", "fields": {key: "1"}})


def test_calendar_anchor_needs_fields() -> None:
    with pytest.raises(ValidationError):
        ANCHOR.validate_python({"kind": "calendar", "calendar_id": "c", "fields": {}})


@pytest.mark.parametrize("key", ["0", "57", "3.0", "12.4"])
def test_occurrence_keys(key: str) -> None:
    ref = {"type": "event", "id": "e", "slot": "start", "occurrence": key}
    assert schema.SlotRef.model_validate(ref).occurrence == key


@pytest.mark.parametrize("key", ["-1", "01", "1.", "1.2.3", "1.02"])
def test_occurrence_keys_reject_bad_values(key: str) -> None:
    with pytest.raises(ValidationError):
        schema.SlotRef.model_validate({"type": "event", "id": "e", "slot": "s", "occurrence": key})


# --- durations and end specs --------------------------------------------------------------------


def test_calendar_duration_sign_is_an_exact_integer() -> None:
    duration = {"kind": "calendar", "calendar_id": "c", "amounts": {"month": "3", "day": "2"}}
    assert DURATION.validate_python(duration | {"sign": -1}).sign == -1
    for sign in [True, 1.0, "1", 0, 2]:
        with pytest.raises(ValidationError):
            DURATION.validate_python(duration | {"sign": sign})


def test_calendar_duration_amounts_are_non_negative() -> None:
    with pytest.raises(ValidationError):
        DURATION.validate_python(
            {"kind": "calendar", "calendar_id": "c", "amounts": {"day": "-1"}, "sign": 1}
        )


@pytest.mark.parametrize(
    "end",
    [
        {"kind": "time_point", "time_point": absolute("5")},
        {"kind": "duration", "duration": {"kind": "base", "units": "60"}},
        {"kind": "instant"},
        {"kind": "end_of_time"},
        {"kind": "unknown"},
    ],
)
def test_end_specs(end: dict[str, Any]) -> None:
    assert END_SPEC.validate_python(end).kind == end["kind"]


def test_end_spec_forbids_extra_members() -> None:
    with pytest.raises(ValidationError):
        END_SPEC.validate_python({"kind": "instant", "time_point": absolute("5")})


# --- rationals ----------------------------------------------------------------------------------


def test_rationals_are_normalized() -> None:
    assert Rational.model_validate({"num": "-3", "den": "8"}).as_pair() == (-3, 8)
    assert Rational.model_validate({"num": "0", "den": "1"}).as_pair() == (0, 1)
    for bad in [
        {"num": "2", "den": "4"},
        {"num": "0", "den": "2"},
        {"num": "1", "den": "0"},
        {"num": "1", "den": "-2"},
    ]:
        with pytest.raises(ValidationError):
            Rational.model_validate(bad)


# --- calendar definitions -----------------------------------------------------------------------


def test_minimal_definition_round_trips() -> None:
    document = minimal_definition()
    definition = CalendarDefinition.model_validate(document)
    assert definition.regimes[0].cycles == []
    dumped = definition.model_dump(mode="json", exclude_defaults=True)
    assert CalendarDefinition.model_validate(dumped) == definition


def test_definition_schema_version_must_be_1() -> None:
    for version in [2, 0, True, 1.0, "1"]:
        with pytest.raises(ValidationError):
            CalendarDefinition.model_validate(minimal_definition(schema_version=version))


def test_definition_forbids_unknown_members() -> None:
    with pytest.raises(ValidationError):
        CalendarDefinition.model_validate(minimal_definition(timezone="UTC"))


def test_sequence_templates_and_predicates() -> None:
    year = {
        "level": "year",
        "sequence": [
            {"id": "frostfall", "template": "day", "name": "Frostfall", "abbr": "Fro"},
            {"id": "midyear", "template": "day", "name": "Midyear", "intercalary": True,
             "cycle_excluded": ["week"]},
            {"run": {"count": "3", "template": "day"}},
        ],
    }  # fmt: skip
    leap = {"any": [{"all": [{"mod": "4", "eq": "0"}, {"not": {"mod": "100", "eq": "0"}}]},
                    {"mod": "400", "eq": "0"}]}  # fmt: skip
    document = minimal_definition()
    regime = document["regimes"][0]
    regime["templates"]["year"] = year
    regime["templates"]["leap"] = year
    regime["top"] = {
        "pattern": {
            "kind": "rules",
            "default": "year",
            "rules": [{"when": leap, "template": "leap"}],
        },
        "exceptions": [{"year": "-5", "template": "leap"}],
    }
    definition = CalendarDefinition.model_validate(document)
    pattern = definition.regimes[0].top.pattern
    assert isinstance(pattern, schema.RulesPattern)
    assert (
        definition.model_dump(mode="json")["regimes"][0]["top"]["pattern"]["rules"][0]["when"]
        == leap
    )  # aliases ("not") survive serialization


def test_template_needs_exactly_one_layout() -> None:
    document = minimal_definition()
    document["regimes"][0]["templates"]["day"] = {
        "level": "day",
        "uniform": {"count": "1"},
        "sequence": [{"run": {"count": "1"}}],
    }
    with pytest.raises(ValidationError):
        CalendarDefinition.model_validate(document)


def test_cycles_eras_overlays_formats_display() -> None:
    document = minimal_definition(
        eras=[
            {"id": "bc", "name": "Before", "abbr": "BC",
             "numbering": {"direction": "backward", "first": "1"}},
            {"id": "ad", "name": "After", "abbr": "AD", "start": absolute("10"),
             "numbering": {"direction": "forward", "first": "1"}, "abbr_position": "prefix"},
        ],
        overlays=[
            {"id": "moon", "name": "Moon", "period": {"num": "2551443", "den": "1"},
             "epoch": absolute("0"),
             "phases": [{"name": "New", "from": {"num": "0", "den": "1"}},
                        {"name": "Full", "from": {"num": "1", "den": "2"}}]},
        ],
        formats={"year": "{era_year} {era}", "intercalary": {"day": "{day.name}"}},
        display={"circa": "ca. "},
    )  # fmt: skip
    document["regimes"][0]["cycles"] = [
        {"id": "week", "level": "day", "length": 7, "mode": {"reset": "year"}},
        {"id": "tzolkin", "level": "day", "length": 13, "anchor": {"fields": {"year": "1"}}},
    ]
    definition = CalendarDefinition.model_validate(document)
    assert definition.overlays[0].phases[1].from_.as_pair() == (1, 2)
    assert definition.formats is not None
    assert definition.formats.intercalary == {"day": "{day.name}"}
    assert definition.formats.model_extra == {"year": "{era_year} {era}"}
    assert definition.display is not None
    assert definition.display.range_separator == " \u2013 "
    cycle = definition.regimes[0].cycles[1]
    assert (cycle.mode, cycle.number_start, cycle.anchor and cycle.anchor.index) == (
        "continuous",
        1,
        0,
    )


@pytest.mark.parametrize(
    "formats", [{"Day": "{day}"}, {"day": 5}, {"day": ""}, {"intercalary": "x"}]
)
def test_formats_are_validated(formats: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Formats.model_validate(formats)


def test_level_numbering_start_is_a_plain_integer() -> None:
    level = {"id": "day", "label": "day", "plural": "days"}
    assert schema.Level.model_validate(level).numbering_start == 1
    for value in [True, "1", -1, 1.5]:
        with pytest.raises(ValidationError):
            schema.Level.model_validate(level | {"numbering_start": value})


def test_compile_context() -> None:
    context = schema.CompileContext.model_validate(
        {
            "base_unit": {"singular": "second", "plural": "seconds", "abbr": "s"},
            "dimension_duration": "1" + "0" * 110,
            "resolved": {"/regimes/0/alignment/at": "435000000000000000"},
        }
    )
    assert context.resolved["/regimes/0/alignment/at"] == "435000000000000000"
    with pytest.raises(ValidationError):
        schema.CompileContext.model_validate(
            {"base_unit": context.base_unit.model_dump(), "dimension_duration": "0"}
        )
    with pytest.raises(ValidationError):
        schema.CompileContext.model_validate(
            {
                "base_unit": context.base_unit.model_dump(),
                "dimension_duration": "10",
                "resolved": {"no-slash": "1"},
            }
        )


# --- recurrence rules ---------------------------------------------------------------------------


def test_calendar_rule_with_filters_and_selectors() -> None:
    rule = RULE.validate_python(
        {
            "kind": "calendar",
            "calendar_id": "c",
            "freq": {"level": "year"},
            "filters": [
                {"mod": "2", "eq": "1"},
                {"not": {"in": ["3", "frostfall"]}},
                {
                    "any": [
                        {"cycle": "week", "in": ["moonday"]},
                        {"all": [{"mod": "7", "eq": "0", "of": "ordinal"}]},
                    ]
                },
            ],
            "select": {
                "path": [
                    {"level": "month", "values": ["frostfall", "3"]},
                    {
                        "level": "day",
                        "cycle": {"id": "week", "values": ["moonday"], "nth": ["1", "-1"]},
                    },
                    {"level": "hour", "all": True},
                ]
            },
            "time": {"fields": {"minute": "0"}},
            "limit": {"kind": "until", "until": absolute("100")},
            "exclusions": [{"from": absolute("10"), "to": absolute("20"), "note": "war"}],
        }
    )  # fmt: skip
    assert isinstance(rule, schema.CalendarRule)
    assert (rule.schema_version, rule.interval, rule.missing) == (1, "1", "skip")
    filters = rule.filters
    assert isinstance(filters[0], schema.ModFilter)
    assert filters[0].of == "number"
    assert isinstance(filters[1], schema.NotFilter)
    assert isinstance(filters[1].not_, schema.InFilter)
    dumped = rule.model_dump(mode="json")
    assert dumped["filters"][1] == {"not": {"in": ["3", "frostfall"]}}
    assert dumped["exclusions"][0]["from"] == absolute("10") | {"approximate": False}


def test_interval_rule() -> None:
    rule = RULE.validate_python(
        {"kind": "interval", "every": "2397422120", "limit": {"kind": "count", "count": "100"}}
    )
    assert isinstance(rule, schema.IntervalRule)
    for bad in [
        {"kind": "interval", "every": "0", "limit": {"kind": "never"}},
        {"kind": "interval", "every": "5", "limit": {"kind": "count", "count": "0"}},
        {"kind": "interval", "every": "5"},
        {"kind": "interval", "every": "5", "limit": {"kind": "never"}, "schema_version": 2},
        {"kind": "weekly", "every": "5", "limit": {"kind": "never"}},
    ]:
        with pytest.raises(ValidationError):
            RULE.validate_python(bad)


def test_all_selector_requires_true() -> None:
    with pytest.raises(ValidationError):
        schema.Selector.model_validate({"path": [{"level": "day", "all": False}]})


# --- correspondences ----------------------------------------------------------------------------


def test_correspondence() -> None:
    correspondence = CorrespondenceDef.model_validate(
        {
            "extrapolation": "rate",
            "rate_after": {"num": "365", "den": "1"},
            "points": [{"a": absolute("0"), "b": absolute("0")}],
        }
    )
    assert correspondence.rate_before is None
    with pytest.raises(ValidationError):
        CorrespondenceDef.model_validate({"points": []})


# --- versioning ---------------------------------------------------------------------------------


def test_upgrade_calendar_definition() -> None:
    document = minimal_definition()
    assert schema.upgrade_calendar_definition(document) is document
    for version in [None, 0, 2, True, "1"]:
        broken = minimal_definition(schema_version=version)
        with pytest.raises(SchemaVersionError):
            schema.upgrade_calendar_definition(broken)
    no_version = minimal_definition()
    del no_version["schema_version"]
    with pytest.raises(SchemaVersionError):
        schema.upgrade_calendar_definition(no_version)


def test_upgrade_recurrence_rule_defaults_to_version_1() -> None:
    rule = {"kind": "interval", "every": "5", "limit": {"kind": "never"}}
    assert schema.upgrade_recurrence_rule(rule) is rule
    assert schema.upgrade_recurrence_rule(rule | {"schema_version": 1}) == rule | {
        "schema_version": 1
    }
    with pytest.raises(SchemaVersionError):
        schema.upgrade_recurrence_rule(rule | {"schema_version": 2})
