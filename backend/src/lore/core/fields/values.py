"""JSON encodings and validators of the core field types (``data-model.md`` §4.2).

A validator takes one JSON value and the field's definition, and returns the value to store
(normalized: canonical integer strings, lowercase colors, re-serialized time specs). It raises
``ValueError`` with a message for the client when the value is invalid.
"""

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from lore.chronology.numbers import MAX_DIGITS
from lore.chronology.schema import Duration, TimePoint
from lore.core.registry.types import FieldDef

type Validator = Callable[[Any, FieldDef], Any]

_INTEGER = re.compile(r"(0|-?[1-9][0-9]*)")
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")
_NEGATIVE_ZERO = re.compile(r"-0(\.0+)?")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
MAX_URL_LENGTH = 2048
MAX_UNIT_LENGTH = 100

_DURATION: TypeAdapter[Any] = TypeAdapter(Duration)


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a string")
    return value


def validate_text(value: Any, _field: FieldDef) -> str:
    text = _string(value)
    if "\n" in text or "\r" in text:
        raise ValueError("must be a single line")
    return text


def validate_long_text(value: Any, _field: FieldDef) -> str:
    return _string(value)


def validate_rich_text(value: Any, _field: FieldDef) -> dict[str, Any]:
    # The node schema is validated by lore.core.richtext (#38); until then any JSON object.
    if not isinstance(value, dict):
        raise ValueError("must be a rich-text document (a JSON object)")
    return value


def validate_integer(value: Any, _field: FieldDef) -> str:
    """A decimal string (JSON integers are tolerated and converted)."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    text = _string(value)
    if _INTEGER.fullmatch(text) is None:
        raise ValueError("must be a canonical decimal integer string")
    if len(text.lstrip("-")) > MAX_DIGITS:
        raise ValueError(f"must have at most {MAX_DIGITS} digits")
    return text


def validate_decimal(value: Any, _field: FieldDef) -> str:
    """An exact decimal string such as ``"1.75"``, kept as typed (``"1.50"`` stays ``"1.50"``).
    Floats are rejected: they are not exact."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    text = _string(value)
    if _DECIMAL.fullmatch(text) is None or _NEGATIVE_ZERO.fullmatch(text) is not None:
        raise ValueError('must be a decimal string such as "1.75"')
    if sum(character.isdigit() for character in text) > MAX_DIGITS:
        raise ValueError(f"must have at most {MAX_DIGITS} digits")
    return text


def validate_boolean(value: Any, _field: FieldDef) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def _option_keys(field: FieldDef) -> list[str]:
    return [option.key for option in field.options]


def validate_enum(value: Any, field: FieldDef) -> str:
    key = _string(value)
    if key not in _option_keys(field):
        raise ValueError(f"must be one of {', '.join(_option_keys(field))}")
    return key


def validate_multi_enum(value: Any, field: FieldDef) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("must be a list of option keys")
    keys = [validate_enum(item, field) for item in value]
    if len(set(keys)) != len(keys):
        raise ValueError("must not repeat an option")
    return keys


def validate_url(value: Any, _field: FieldDef) -> str:
    url = _string(value)
    if len(url) > MAX_URL_LENGTH or any(character.isspace() for character in url):
        raise ValueError(f"must be a URL without spaces, at most {MAX_URL_LENGTH} characters")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ValueError("must be a valid URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("must be an http(s) URL")
    return url


def validate_color(value: Any, _field: FieldDef | None = None) -> str:
    color = _string(value)
    if _COLOR.fullmatch(color) is None:
        raise ValueError("must be a color #rrggbb")
    return color.lower()


def validate_measurement(value: Any, field: FieldDef) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"value", "unit"}:
        raise ValueError("must be an object {value, unit}")
    unit = _string(value["unit"]).strip()
    if not unit or len(unit) > MAX_UNIT_LENGTH:
        raise ValueError(f"unit must be 1 to {MAX_UNIT_LENGTH} characters")
    return {"value": validate_decimal(value["value"], field), "unit": unit}


def _pydantic_message(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    return f"{location}: {first['msg']}" if location else str(first["msg"])


def validate_duration(value: Any, _field: FieldDef) -> Any:
    """Duration JSON (``time-model.md`` §5.1), checked structurally. Wired to time in M3."""
    try:
        return _DURATION.dump_python(_DURATION.validate_python(value), mode="json")
    except ValidationError as exc:
        raise ValueError(f"must be a duration ({_pydantic_message(exc)})") from exc


def validate_time_point(value: Any, _field: FieldDef) -> Any:
    """TimePoint JSON (``time-model.md`` §5.1), checked structurally. Resolution and propagation
    (``entity_time_fields``) arrive with M3/M7."""
    try:
        return TimePoint.model_validate(value).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError(f"must be a time point ({_pydantic_message(exc)})") from exc


CORE_VALIDATORS: Mapping[str, Validator] = {
    "text": validate_text,
    "long_text": validate_long_text,
    "rich_text": validate_rich_text,
    "integer": validate_integer,
    "decimal": validate_decimal,
    "boolean": validate_boolean,
    "enum": validate_enum,
    "multi_enum": validate_multi_enum,
    "url": validate_url,
    "color": validate_color,
    "duration": validate_duration,
    "time_point": validate_time_point,
    "measurement": validate_measurement,
}
