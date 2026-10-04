"""Snippets: text around the first match of a document column, with the matching words marked.

Built in Python from the stored column text for the hits of one page (FTS5's ``snippet()`` re-reads
the whole match list for every hit, which costs too much for common words). Words are split and
compared like the ``unicode61 remove_diacritics 2`` tokenizer does: runs of letters and digits,
compared ignoring case and accents.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from lore.core.entities.models import fold_text

WINDOW = 16  # words shown
LEAD = 4  # words shown before the first match
ELLIPSIS = "…"
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Term:
    """A positive search term: its words in order; ``prefix``: the last one matches word starts."""

    words: tuple[str, ...]
    prefix: bool

    @classmethod
    def of(cls, text: str, *, prefix: bool) -> Term:
        return cls(tuple(fold_text(word) for word in _WORD.findall(text)), prefix)


@dataclass(frozen=True)
class Part:
    text: str
    match: bool


def _matches(tokens: Sequence[str], at: int, term: Term) -> bool:
    if at + len(term.words) > len(tokens):
        return False
    last = len(term.words) - 1
    for offset, word in enumerate(term.words):
        token = tokens[at + offset]
        if token != word and not (offset == last and term.prefix and token.startswith(word)):
            return False
    return True


def snippet(text: str, terms: Sequence[Term]) -> list[Part] | None:
    """The parts of a snippet of ``text``, or ``None`` when no term matches it."""
    spans = [(m.start(), m.end()) for m in _WORD.finditer(text)]
    tokens = [fold_text(text[start:end]) for start, end in spans]
    matched = [False] * len(tokens)
    for at in range(len(tokens)):
        for term in terms:
            if term.words and _matches(tokens, at, term):
                for offset in range(len(term.words)):
                    matched[at + offset] = True
    if not any(matched):
        return None
    first_match = matched.index(True)
    first = max(0, first_match - LEAD)
    last = min(len(tokens), first + WINDOW) - 1
    first = max(0, min(first, last + 1 - WINDOW))
    start = 0 if first == 0 else spans[first][0]
    end = len(text) if last == len(tokens) - 1 else spans[last][1]

    parts: list[Part] = []

    def add(piece: str, match: bool) -> None:
        piece = piece.replace("\n", " ")
        if not piece:
            return
        if parts and parts[-1].match == match:
            parts[-1] = Part(parts[-1].text + piece, match)
        else:
            parts.append(Part(piece, match))

    if start > 0:
        add(ELLIPSIS, False)
    position = start
    for index in range(first, last + 1):
        token_start, token_end = spans[index]
        if matched[index]:
            # The gap between two matched words (inside a phrase) is highlighted with them.
            joined = index > first and matched[index - 1]
            add(text[position:token_start], joined)
            add(text[token_start:token_end], True)
            position = token_end
    add(text[position:end], False)
    if end < len(text):
        add(ELLIPSIS, False)
    return parts
