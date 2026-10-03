"""Format pattern tokens (``chronology-engine.md`` §3.11): parsing and validation.

Compilation checks that every token is known; :mod:`~lore.chronology.calendar.formatting`
renders parsed patterns.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, cast

_TOKEN = re.compile(
    r"(?P<level>[a-z][a-z0-9_]*)(?:\.(?P<attr>name|abbr|id))?(?::(?P<modifier>pad2|pad3|ordinal))?"
)
_SPECIAL = re.compile(
    r"(?P<era>era)(\.(?P<era_attr>name))?"
    r"|(?P<cycle>cycle)\.(?P<cycle_id>[a-z][a-z0-9_]*)(\.(?P<cycle_attr>abbr|n))?"
    r"|(?P<overlay>overlay)\.(?P<overlay_id>[a-z][a-z0-9_]*)(\.(?P<overlay_attr>fraction))?"
)
type TokenKind = Literal["level", "year", "era_year", "base", "era", "cycle", "overlay"]
type Modifier = Literal["pad2", "pad3", "ordinal"]

_NUMERIC_KINDS: dict[str, TokenKind] = {"year": "year", "era_year": "era_year", "base": "base"}


class PatternError(ValueError):
    """A pattern with unbalanced braces."""


@dataclass(frozen=True, slots=True)
class Token:
    """A parsed token: ``{<id>.<attr>:<modifier>}`` of some ``kind``."""

    kind: TokenKind
    id: str | None = None
    """The level, cycle or overlay id (``None`` for ``year``, ``era_year``, ``base``, ``era``)."""
    attr: str | None = None
    """``name``/``abbr``/``id`` (levels), ``name`` (era), ``abbr``/``n`` (cycles), ``fraction``."""
    modifier: Modifier | None = None


type Piece = str | Token
"""A literal text (braces unescaped) or a token."""


def _split(pattern: str) -> Iterator[tuple[bool, str]]:
    """(is_token, text) pieces; ``{{``/``}}`` become literal braces."""
    literal: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char in "{}" and pattern[i : i + 2] in ("{{", "}}"):
            literal.append(char)
            i += 2
        elif char == "{":
            end = pattern.find("}", i)
            if end < 0:
                raise PatternError("unclosed '{'")
            if literal:
                yield False, "".join(literal)
                literal = []
            yield True, pattern[i + 1 : end]
            i = end + 1
        elif char == "}":
            raise PatternError("unmatched '}'")
        else:
            literal.append(char)
            i += 1
    if literal:
        yield False, "".join(literal)


def tokens(pattern: str) -> Iterator[str]:
    """Yield the tokens (text between single braces) of a pattern; ``{{``/``}}`` are literals."""
    return (text for is_token, text in _split(pattern) if is_token)


def parse_token(token: str) -> Token | None:
    """The structure of a token, or ``None`` if it has no valid syntax (ids are not checked)."""
    special = _SPECIAL.fullmatch(token)
    if special is not None:
        kind: TokenKind = "era" if special["era"] else "cycle" if special["cycle"] else "overlay"
        attr = special["era_attr"] or special["cycle_attr"] or special["overlay_attr"]
        return Token(kind, special["cycle_id"] or special["overlay_id"], attr)
    match = _TOKEN.fullmatch(token)
    if match is None:
        return None
    level, attr = match["level"], match["attr"]
    modifier = cast(Modifier | None, match["modifier"])  # the regex only matches modifiers
    numeric = _NUMERIC_KINDS.get(level)
    if attr is not None and (modifier is not None or numeric is not None):
        return None  # modifiers apply to numbers, and the numeric tokens have no attributes
    if numeric is not None:
        return Token(numeric, modifier=modifier)
    return Token("level", level, attr, modifier)


def parse(pattern: str) -> list[Piece]:
    """The pieces of a valid pattern. Raises :class:`PatternError` for bad braces or tokens."""
    pieces: list[Piece] = []
    for is_token, text in _split(pattern):
        if not is_token:
            pieces.append(text)
            continue
        token = parse_token(text)
        if token is None:
            raise PatternError(f"unknown token {text!r}")
        pieces.append(token)
    return pieces


def unknown_tokens(
    pattern: str, *, levels: frozenset[str], cycles: frozenset[str], overlays: frozenset[str]
) -> list[str]:
    """Tokens of ``pattern`` that are not valid for this calendar (``["{"]`` for bad braces)."""
    try:
        found = list(tokens(pattern))
    except PatternError:
        return ["{"]
    return [token for token in found if not _known(parse_token(token), levels, cycles, overlays)]


def _known(
    token: Token | None, levels: frozenset[str], cycles: frozenset[str], overlays: frozenset[str]
) -> bool:
    if token is None:
        return False
    if token.kind == "cycle":
        return token.id in cycles
    if token.kind == "overlay":
        return token.id in overlays
    if token.kind == "level":
        return token.id in levels
    return True
