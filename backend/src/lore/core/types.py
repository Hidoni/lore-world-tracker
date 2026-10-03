"""Wire types shared by API schemas (``docs/architecture/api.md`` §1)."""

import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, PlainSerializer, WithJsonSchema

from lore.chronology.numbers import MAX_DIGITS, NumberError, parse_moment
from lore.chronology.schema import MOMENT_PATTERN

# Canonical decimal integers: no sign on zero, no leading zeros, no "+", no whitespace.
BIGINT_PATTERN = r"^(0|-?[1-9][0-9]*)$"
_BIGINT_RE = re.compile(BIGINT_PATTERN)


def _parse_bigint(value: Any) -> int:
    if isinstance(value, str):
        if _BIGINT_RE.fullmatch(value) is None:
            raise ValueError("must be a canonical decimal integer string")
        return int(value)
    # Python callers pass ints. JSON integers are tolerated too (Python parses them exactly), but
    # the schema only advertises strings: a JavaScript `number` above 2**53 is already rounded.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError("must be a decimal integer string")


BigIntStr = Annotated[
    int,
    BeforeValidator(_parse_bigint),
    PlainSerializer(str, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "bigint",
            "pattern": BIGINT_PATTERN,
            "examples": ["0", "-42", "31557600000"],
        }
    ),
]
"""An arbitrary-precision integer (moments, durations, counts, integer field values).

A Python ``int`` in the backend; a decimal string in JSON and in the OpenAPI document
(``type: string``, ``format: bigint``), which the frontend data layer turns into ``bigint``.
"""


def _parse_moment(value: Any) -> int:
    if isinstance(value, str):
        try:
            return parse_moment(value)
        except NumberError as exc:
            raise ValueError("must be a canonical non-negative decimal integer string") from exc
    if isinstance(value, int) and not isinstance(value, bool):
        if not 0 <= value < 10**MAX_DIGITS:
            raise ValueError(f"must be between 0 and 10^{MAX_DIGITS} - 1")
        return value
    raise ValueError("must be a decimal integer string")


MomentStr = Annotated[
    int,
    BeforeValidator(_parse_moment),
    PlainSerializer(str, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "bigint",
            "pattern": MOMENT_PATTERN,
            "maxLength": MAX_DIGITS,
            "examples": ["0", "435000000000000000"],
        }
    ),
]
"""An in-world moment (``time-model.md`` §2): a non-negative integer of at most 1000 digits.

An ``int`` in the backend (stored with ``SortableBigInt``); a canonical decimal string on the
wire. Unlike ``lore.chronology.schema.MomentStr`` (a ``str`` inside chronology documents), API
models get the parsed integer.
"""


class Affected(BaseModel):
    """What a write changed, for client cache invalidation (``frontend.md`` §5)."""

    entities: list[str]
    dimensions: list[str]
    time_changed: bool
    search_changed: bool
