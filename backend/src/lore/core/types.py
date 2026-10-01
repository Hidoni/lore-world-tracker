"""Wire types shared by API schemas (``docs/architecture/api.md`` §1)."""

import re
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

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
