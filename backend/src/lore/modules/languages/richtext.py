"""The ``lexiconRef`` rich-text node (``docs/modules/languages.md``, UI): an inline reference to
a lexicon entry, rendered as its headword with a gloss tooltip.

Its attributes are ids only (``entryId``, ``languageId``), so a document never carries an
entry's words: readers who may not see the language lose the node, and an entry they may not see
renders as a placeholder (``GET /m/languages/lexicon/{id}`` answers 404)."""

import re
from typing import Any

from lore.core.richtext.handlers import Node, RichTextNodeHandler

_ID = re.compile(r"^[0-9a-zA-Z][0-9a-zA-Z_-]{0,99}$")


def _validate(attrs: dict[str, Any]) -> dict[str, Any]:
    unknown = set(attrs) - {"entryId", "languageId"}
    if unknown:
        raise ValueError(f"unknown attributes: {', '.join(sorted(unknown))}")
    for name in ("entryId", "languageId"):
        value = attrs.get(name)
        if not isinstance(value, str) or not _ID.match(value):
            raise ValueError(f"{name} must be an id")
    return {"entryId": attrs["entryId"], "languageId": attrs["languageId"]}


def _filter(node: Node, visible: frozenset[str]) -> Node | None:
    return node if node.get("attrs", {}).get("languageId") in visible else None


LEXICON_REF = RichTextNodeHandler(
    type="lexiconRef",
    group="inline",
    validate_attrs=_validate,
    filter_for_reader=_filter,
    ref_kind="lexicon_entry",
    extract_refs=lambda node: [str(node.get("attrs", {}).get("entryId", ""))],
)
