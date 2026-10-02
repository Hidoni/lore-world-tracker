"""Format pattern tokens (``chronology-engine.md`` §3.11): parsing and validation.

Rendering arrives with formatting (#17); compilation only checks that every token is known.
"""

import re
from collections.abc import Iterator

_TOKEN = re.compile(
    r"(?P<level>[a-z][a-z0-9_]*)(?:\.(?P<attr>name|abbr|id))?(?::(?P<modifier>pad2|pad3|ordinal))?"
)
_SPECIAL = re.compile(
    r"era(\.name)?"
    r"|(?P<cycle>cycle)\.(?P<cycle_id>[a-z][a-z0-9_]*)(\.(abbr|n))?"
    r"|(?P<overlay>overlay)\.(?P<overlay_id>[a-z][a-z0-9_]*)(\.fraction)?"
)
_NUMERIC_TOKENS = frozenset({"year", "era_year", "base"})


class PatternError(ValueError):
    """A pattern with unbalanced braces."""


def tokens(pattern: str) -> Iterator[str]:
    """Yield the tokens (text between single braces) of a pattern; ``{{``/``}}`` are literals."""
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char in "{}" and pattern[i : i + 2] in ("{{", "}}"):
            i += 2
        elif char == "{":
            end = pattern.find("}", i)
            if end < 0:
                raise PatternError("unclosed '{'")
            yield pattern[i + 1 : end]
            i = end + 1
        elif char == "}":
            raise PatternError("unmatched '}'")
        else:
            i += 1


def unknown_tokens(
    pattern: str, *, levels: frozenset[str], cycles: frozenset[str], overlays: frozenset[str]
) -> list[str]:
    """Tokens of ``pattern`` that are not valid for this calendar (``["{"]`` for bad braces)."""
    try:
        found = list(tokens(pattern))
    except PatternError:
        return ["{"]
    return [token for token in found if not _known(token, levels, cycles, overlays)]


def _known(
    token: str, levels: frozenset[str], cycles: frozenset[str], overlays: frozenset[str]
) -> bool:
    special = _SPECIAL.fullmatch(token)
    if special is not None:
        if special["cycle"]:
            return special["cycle_id"] in cycles
        if special["overlay"]:
            return special["overlay_id"] in overlays
        return True
    match = _TOKEN.fullmatch(token)
    if match is None:
        return False
    if match["level"] in _NUMERIC_TOKENS:
        return match["attr"] is None
    return match["level"] in levels and (match["attr"] is None or match["modifier"] is None)
