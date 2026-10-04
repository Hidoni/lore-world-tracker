"""Search expressions: what users type into search, translated to safe FTS5 queries.

Grammar (keywords are upper case; lower-case ``or``/``not`` are ordinary words)::

    expression := any ( "OR" any )*
    any        := unary+                      # every part must match (implicit AND)
    unary      := ( "-" | "NOT" ) atom | atom # "-" / NOT: must not match
    atom       := word | "phrase" | "phrase"* | "(" expression ")"

- A **word** matches words that start with it ("dra" finds "Dragon"); a trailing ``*`` is allowed
  and means the same.
- A **"quoted phrase"** matches those words in that order, each one exactly (a ``*`` after the
  closing quote makes its last word a prefix).
- ``AND`` between parts is accepted and changes nothing.
- A group needs at least one part that isn't excluded (``-dragon`` alone finds nothing to exclude
  from and is rejected). Matching ignores case and accents.

Every user-supplied text ends up inside an FTS5 string, so FTS5 syntax characters in the input are
never interpreted. Invalid input raises ``ExpressionError`` with a message for the user.
"""

import re
from dataclasses import dataclass

from lore.core.search.highlight import Term

MAX_DEPTH = 8
MAX_TERMS = 32
_WORD = re.compile(r"\w", re.UNICODE)
_TOKEN = re.compile(r'\s+|\(|\)|"[^"]*"?\*?|[^\s()"]+')


class ExpressionError(ValueError):
    """The search text can't be understood (unbalanced quotes or parentheses, nothing to
    search for, …)."""


@dataclass(frozen=True)
class Expression:
    fts: str  # the FTS5 MATCH expression
    terms: tuple[Term, ...]  # the words and phrases to find (not excluded ones), for snippets


def _quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = [t for t in _TOKEN.findall(text) if not t.isspace()]
        self.position = 0
        self.terms: list[Term] = []

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token: str = self.tokens[self.position]
        self.position += 1
        return token

    def parse(self) -> Expression:
        if not self.tokens:
            raise ExpressionError("Type something to search for.")
        fts = self.expression(0)
        if self.peek() is not None:
            raise ExpressionError("A closing parenthesis has no opening one.")
        if fts is None:
            raise ExpressionError("Nothing to search for: use words or letters.")
        if len(self.terms) > MAX_TERMS:
            raise ExpressionError(f"Use at most {MAX_TERMS} words or phrases.")
        return Expression(fts=fts, terms=tuple(self.terms))

    def expression(self, depth: int) -> str | None:
        if depth > MAX_DEPTH:
            raise ExpressionError("Too many nested parentheses.")
        alternatives = [self.all_of(depth)]
        while self.peek() == "OR":
            self.take()
            alternatives.append(self.all_of(depth))
        kept = [a for a in alternatives if a is not None]
        if not kept:
            return None
        return kept[0] if len(kept) == 1 else "(" + " OR ".join(kept) + ")"

    def all_of(self, depth: int) -> str | None:
        included: list[str] = []
        excluded: list[str] = []
        parts = 0
        while (token := self.peek()) is not None and token not in ("OR", ")"):
            if token == "AND":
                self.take()
                continue
            negated = False
            if token in ("-", "NOT"):
                self.take()
                negated = True
            elif token.startswith("-") and len(token) > 1:
                self.tokens[self.position] = token[1:]
                negated = True
            atom = self.atom(depth, negated)
            parts += 1
            if atom is not None:
                (excluded if negated else included).append(atom)
        if parts == 0:
            raise ExpressionError("OR needs something to search for on both sides.")
        if not included:
            if excluded:
                raise ExpressionError("Say what to search for, not only what to leave out.")
            return None
        positive = included[0] if len(included) == 1 else "(" + " AND ".join(included) + ")"
        return positive + "".join(f" NOT {atom}" for atom in excluded)

    def atom(self, depth: int, negated: bool) -> str | None:
        token = self.peek()
        if token is None or token in ("OR", ")"):
            raise ExpressionError("Leave out what? Put a word after - or NOT.")
        self.take()
        if token == "(":
            inner = self.expression(depth + 1)
            if self.peek() != ")":
                raise ExpressionError("A parenthesis isn't closed.")
            self.take()
            return inner if inner is None else f"({inner})"
        if token.startswith('"'):
            prefix = token.endswith("*")
            body = token.rstrip("*")
            if len(body) < len('""') or not body.endswith('"'):
                raise ExpressionError("A quote isn't closed.")
            phrase = body[1:-1]
            if not _WORD.search(phrase):
                return None
            if not negated:
                self.terms.append(Term.of(phrase, prefix=prefix))
            return _quote(phrase) + ("*" if prefix else "")
        word = token.rstrip("*")
        if not _WORD.search(word):
            return None
        if not negated:
            self.terms.append(Term.of(word, prefix=True))
        return _quote(word) + "*"


def parse(text: str) -> Expression:
    return _Parser(text).parse()
