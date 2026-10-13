"""Sorting a lexicon by the language's own alphabet (``docs/modules/languages.md``,
``alphabet_order``).

The order is a space-separated list of letters, which may be multigraphs ("a b c ch d …"). A
headword is split into letters by longest match ("chat" → ch, a, t when "ch" is a letter) and
each letter becomes a fixed-width key part: its position for letters of the order, after them
(by code point) for anything else. Keys compare as text, so ``ORDER BY collation_key`` sorts by
the alphabet. Matching ignores case and Unicode composition; an empty order means Unicode order
(of the case-folded headword).
"""

import unicodedata
from dataclasses import dataclass, field


def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


@dataclass(frozen=True)
class Alphabet:
    """A parsed ``alphabet_order``."""

    letters: tuple[str, ...]
    _rank: dict[str, int] = field(init=False, repr=False, compare=False)
    _longest: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rank: dict[str, int] = {}
        for index, letter in enumerate(self.letters):
            rank.setdefault(letter, index)
        object.__setattr__(self, "_rank", rank)
        object.__setattr__(self, "_longest", max((len(letter) for letter in rank), default=0))

    @classmethod
    def parse(cls, order: str | None) -> Alphabet:
        return cls(tuple(_norm(token) for token in (order or "").split()))

    def tokens(self, headword: str) -> list[str]:
        """The headword's letters, by longest match against the alphabet."""
        text = _norm(headword)
        found: list[str] = []
        i = 0
        while i < len(text):
            for size in range(min(self._longest, len(text) - i), 0, -1):
                if text[i : i + size] in self._rank:
                    found.append(text[i : i + size])
                    i += size
                    break
            else:
                found.append(text[i])
                i += 1
        return found

    def key(self, headword: str) -> str:
        """The collation key: 8 hex digits per letter, alphabet letters (``0…``) before every
        other character (``1`` + its code point)."""
        parts = []
        for token in self.tokens(headword):
            rank = self._rank.get(token)
            parts.append(f"0{rank:07x}" if rank is not None else f"1{ord(token[0]):07x}")
        return "".join(parts)
