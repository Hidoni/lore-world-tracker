"""JSON Schema export of the chronology models into ``spec/chronology/schema/``.

One file per top-level type plus ``bundle.json`` (every type under ``$defs``), from which the
TypeScript types are generated (``chronology-engine.md`` §1). Output is deterministic so a drift
check can compare it byte for byte.
"""

import json
from typing import Any

from pydantic import TypeAdapter
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode

from lore.chronology import schema

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

TOP_LEVEL_TYPES: dict[str, tuple[str, Any]] = {
    "rational.json": ("Rational", schema.Rational),
    "anchor.json": ("Anchor", schema.Anchor),
    "time-point.json": ("TimePoint", schema.TimePoint),
    "duration.json": ("Duration", schema.Duration),
    "end-spec.json": ("EndSpec", schema.EndSpec),
    "calendar-definition.json": ("CalendarDefinition", schema.CalendarDefinition),
    "compile-context.json": ("CompileContext", schema.CompileContext),
    "recurrence-rule.json": ("RecurrenceRule", schema.RecurrenceRule),
    "correspondence.json": ("CorrespondenceDef", schema.CorrespondenceDef),
}
"""File name → (type name, type). Adding a type here adds it to the files and the TS types."""

BUNDLE_FILE = "bundle.json"


class _SchemaGenerator(GenerateJsonSchema):
    """Pydantic's generator without per-field titles (they become junk aliases in TypeScript)."""

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _single(name: str, type_: Any) -> dict[str, Any]:
    body = TypeAdapter(type_).json_schema(schema_generator=_SchemaGenerator)
    defs = body.pop("$defs", {})
    body.setdefault("title", name)  # named unions (PEP 695 aliases) come without one
    document: dict[str, Any] = {"$schema": JSON_SCHEMA_DIALECT, **body}
    if defs:
        document["$defs"] = defs
    return document


def _bundle() -> dict[str, Any]:
    adapters: list[tuple[str, JsonSchemaMode, TypeAdapter[Any]]] = [
        (name, "validation", TypeAdapter(type_)) for name, type_ in TOP_LEVEL_TYPES.values()
    ]
    refs, top = TypeAdapter.json_schemas(adapters, schema_generator=_SchemaGenerator)
    defs: dict[str, Any] = top.get("$defs", {})
    properties = {name: refs[(name, "validation")] for name, _ in TOP_LEVEL_TYPES.values()}
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "title": "ChronologySchemas",
        "description": "Index of the top-level chronology types (generated; see spec/README.md).",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "$defs": dict(sorted(defs.items())),
    }


def export_schemas() -> dict[str, str]:
    """Return ``{file name: JSON text}`` for every schema file."""
    files = {file: _dump(_single(name, type_)) for file, (name, type_) in TOP_LEVEL_TYPES.items()}
    files[BUNDLE_FILE] = _dump(_bundle())
    return files
