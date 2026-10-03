"""What the backend reads out of a (validated) rich-text document: plain text split by
visibility, entity mentions counted by the visibility of their containing block, and references
(time refs; module refs such as media), plus ``filter_for_reader``.

Visibility of a position = the most restrictive of the document's base visibility (the field's
visibility for ``rich_text`` fields, ``public`` for bodies) and every enclosing
``visibilityBlock``. "Public" text holds public and spoiler content (search's public columns,
``data-model.md`` §9); "restricted" text holds private content.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lore.core.db.base import Visibility
from lore.core.richtext.handlers import Node, RichTextNodeHandler

_RANK: dict[str, int] = {"public": 0, "spoiler": 1, "private": 2}
_BLOCKS_WITH_BREAKS = frozenset(
    {"paragraph", "heading", "codeBlock", "listItem", "tableCell", "tableHeader", "blockquote"}
)


def stricter(a: Visibility, b: Visibility) -> Visibility:
    return a if _RANK[a] >= _RANK[b] else b


@dataclass
class MentionCounts:
    public: int = 0
    spoiler: int = 0
    private: int = 0

    def add(self, level: Visibility) -> None:
        setattr(self, level, getattr(self, level) + 1)


@dataclass
class Extraction:
    public_text: str = ""
    restricted_text: str = ""
    mentions: dict[str, MentionCounts] = field(default_factory=dict)
    refs: dict[str, list[Any]] = field(default_factory=lambda: defaultdict(list))


def extract(
    doc: Node | None,
    handlers: Mapping[str, RichTextNodeHandler] | None = None,
    *,
    visibility: Visibility = "public",
) -> Extraction:
    result = Extraction()
    if doc is None:
        return result
    public: list[str] = []
    restricted: list[str] = []
    handlers = handlers or {}

    def text_out(level: Visibility, text: str) -> None:
        (restricted if level == "private" else public).append(text)

    def walk(node: Node, level: Visibility) -> None:
        node_type = str(node.get("type"))
        attrs = node.get("attrs") or {}
        if node_type == "visibilityBlock":
            level = stricter(level, attrs["level"])
        if node_type == "text":
            text_out(level, node["text"])
            for mark in node.get("marks") or ():
                if mark["type"] == "entityLink":
                    target = mark["attrs"]["entityId"]
                    result.mentions.setdefault(target, MentionCounts()).add(level)
            return
        if node_type == "hardBreak":
            text_out(level, "\n")
        elif node_type == "timeRef":
            result.refs["time"].append(attrs)
        elif node_type in handlers:
            handler = handlers[node_type]
            text = handler.extract_text(node)
            if text:
                text_out(level, text)
            if handler.ref_kind:
                result.refs[handler.ref_kind].extend(handler.extract_refs(node))
        for child in node.get("content") or ():
            walk(child, level)
        if node_type in _BLOCKS_WITH_BREAKS:
            text_out(level, "\n")

    walk(doc, visibility)
    result.public_text = _tidy("".join(public))
    result.restricted_text = _tidy("".join(restricted))
    result.refs = dict(result.refs)
    return result


def _tidy(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def filter_for_reader(
    doc: Node | None,
    visible_entity_ids: frozenset[str],
    handlers: Mapping[str, RichTextNodeHandler] | None = None,
) -> Node | None:
    """The document as readers may see it (``visibility-and-sharing.md`` §3): private
    ``visibilityBlock``s removed, spoilers kept (flagged by their ``level``), ``entityLink`` marks
    to entities outside ``visible_entity_ids`` stripped (the text stays), ``timeRef`` references
    to hidden records reduced to nothing that names them, module nodes filtered by their
    handlers."""
    if doc is None:
        return None
    handlers = handlers or {}

    def node_out(node: Node) -> Node | None:
        node_type = str(node.get("type"))
        attrs = node.get("attrs") or {}
        if node_type == "visibilityBlock" and attrs.get("level") == "private":
            return None
        if node_type in handlers:
            filtered = handlers[node_type].filter_for_reader(node, visible_entity_ids)
            if filtered is None:
                return None
            node = filtered
        result = dict(node)
        if (
            node_type == "timeRef"
            and "ref" in attrs
            and attrs["ref"]["id"] not in visible_entity_ids
        ):
            # The reader sees the resolved date (M3) but not what it is relative to.
            result["attrs"] = {"hidden_ref": True}
        if node_type == "text" and node.get("marks"):
            marks = [
                mark
                for mark in node["marks"]
                if mark["type"] != "entityLink" or mark["attrs"]["entityId"] in visible_entity_ids
            ]
            if marks:
                result["marks"] = marks
            else:
                result.pop("marks")
        if "content" in node:
            result["content"] = [kept for child in node["content"] if (kept := node_out(child))]
        return result

    return node_out(doc)
