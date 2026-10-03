"""The rich-text node schema v1 (``frontend.md`` §6) and its validator.

Documents are TipTap/ProseMirror JSON: ``{type, attrs?, content?, marks?, text?}``. The validator
checks every node and mark type, where each may appear, and their attributes, and returns a
normalized copy:

- unknown node or mark types are rejected (``422``, path into the document);
- unknown attributes are rejected too (decided 2026-10-04: an editor feature the server schema
  doesn't know must surface in tests, not be silently lost); the only exceptions are editor
  defaults deliberately not stored, ``IGNORED_MARK_ATTRS`` (the link mark's ``target``, ``rel``,
  ``class``); module nodes check their attributes in their handler;
- ``link`` marks whose ``href`` isn't ``http(s)``/``mailto`` are **removed, keeping the text**
  (decided 2026-10-04: a pasted unsafe link must not make autosave fail);
- nesting deeper than ``MAX_DEPTH`` is rejected.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from lore.chronology.schema import SlotRef, TimePoint
from lore.core.errors import ErrorItem, InvalidInputError
from lore.core.richtext.handlers import Node, RichTextNodeHandler

MAX_DEPTH = 64
MAX_LABEL = 200
MAX_HREF = 2048
SAFE_SCHEMES = frozenset({"http", "https", "mailto"})
CALLOUT_TONES = frozenset({"note", "warning", "quote"})
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_LANGUAGE = re.compile(r"[A-Za-z0-9_+#.-]{1,40}")

BLOCK = "block"
INLINE = "inline"

# node type -> (group, content group or None for leaves, or a specific child type)
_CORE_NODES: dict[str, tuple[str | None, str | None]] = {
    "doc": (None, BLOCK),
    "paragraph": (BLOCK, INLINE),
    "heading": (BLOCK, INLINE),
    "blockquote": (BLOCK, BLOCK),
    "bulletList": (BLOCK, "listItem"),
    "orderedList": (BLOCK, "listItem"),
    "listItem": (None, BLOCK),
    "codeBlock": (BLOCK, "text"),
    "horizontalRule": (BLOCK, None),
    "table": (BLOCK, "tableRow"),
    "tableRow": (None, "cell"),
    "tableCell": (None, BLOCK),
    "tableHeader": (None, BLOCK),
    "visibilityBlock": (BLOCK, BLOCK),
    "callout": (BLOCK, BLOCK),
    "text": (INLINE, None),
    "hardBreak": (INLINE, None),
    "timeRef": (INLINE, None),
}
CORE_NODE_TYPES = frozenset(_CORE_NODES)
CORE_MARK_TYPES = frozenset({"bold", "italic", "strike", "code", "link", "entityLink"})
_CELLS = frozenset({"tableCell", "tableHeader"})


class _InvalidNodeError(Exception):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path, self.message = path, message


def _int(value: Any, path: str, *, minimum: int, maximum: int | None = None) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise _InvalidNodeError(path, f"must be an integer {bound}")
    return value


def _label(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_LABEL:
        raise _InvalidNodeError(path, f"must be text of at most {MAX_LABEL} characters")
    return value


def _heading_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    return {"level": _int(attrs.get("level"), f"{path}.level", minimum=1, maximum=4)}


def _ordered_list_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    return {"start": _int(attrs.get("start", 1), f"{path}.start", minimum=0)}


def _code_block_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    language = attrs.get("language")
    if language is not None and (
        not isinstance(language, str) or _LANGUAGE.fullmatch(language) is None
    ):
        raise _InvalidNodeError(f"{path}.language", "must be a language name")
    return {"language": language}


def _cell_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    widths = attrs.get("colwidth")
    if widths is not None:
        if not isinstance(widths, list):
            raise _InvalidNodeError(f"{path}.colwidth", "must be a list of widths")
        widths = [_int(w, f"{path}.colwidth", minimum=1, maximum=10000) for w in widths]
    return {
        "colspan": _int(attrs.get("colspan", 1), f"{path}.colspan", minimum=1, maximum=100),
        "rowspan": _int(attrs.get("rowspan", 1), f"{path}.rowspan", minimum=1, maximum=100),
        "colwidth": widths,
    }


def _visibility_block_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    level = attrs.get("level")
    if level not in {"spoiler", "private"}:
        raise _InvalidNodeError(f"{path}.level", "must be spoiler or private")
    return {"level": level, "label": _label(attrs.get("label"), f"{path}.label")}


def _callout_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    tone = attrs.get("tone", "note")
    if tone not in CALLOUT_TONES:
        raise _InvalidNodeError(
            f"{path}.tone", f"must be one of {', '.join(sorted(CALLOUT_TONES))}"
        )
    return {"tone": tone}


def _time_ref_attrs(attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    point, ref = attrs.get("timePoint"), attrs.get("ref")
    if (point is None) == (ref is None):
        raise _InvalidNodeError(path, "a timeRef needs exactly one of timePoint and ref")
    try:
        if point is not None:
            return {"timePoint": TimePoint.model_validate(point).model_dump(mode="json")}
        return {"ref": SlotRef.model_validate(ref).model_dump(mode="json", exclude_none=True)}
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        name = "timePoint" if point is not None else "ref"
        raise _InvalidNodeError(
            f"{path}.{name}{'.' + where if where else ''}", first["msg"]
        ) from exc


_ATTRS: dict[str, Callable[[Mapping[str, Any], str], dict[str, Any]]] = {
    "heading": _heading_attrs,
    "orderedList": _ordered_list_attrs,
    "codeBlock": _code_block_attrs,
    "tableCell": _cell_attrs,
    "tableHeader": _cell_attrs,
    "visibilityBlock": _visibility_block_attrs,
    "callout": _callout_attrs,
    "timeRef": _time_ref_attrs,
}


_ATTR_KEYS: dict[str, frozenset[str]] = {
    "heading": frozenset({"level"}),
    "orderedList": frozenset({"start"}),
    "codeBlock": frozenset({"language"}),
    "tableCell": frozenset({"colspan", "rowspan", "colwidth"}),
    "tableHeader": frozenset({"colspan", "rowspan", "colwidth"}),
    "visibilityBlock": frozenset({"level", "label"}),
    "callout": frozenset({"tone"}),
    "timeRef": frozenset({"timePoint", "ref"}),
}
_MARK_KEYS: dict[str, frozenset[str]] = {
    "link": frozenset({"href"}),
    "entityLink": frozenset({"entityId"}),
}
# Editor defaults that are deliberately not stored (the app sets them when rendering).
IGNORED_MARK_ATTRS: dict[str, frozenset[str]] = {"link": frozenset({"target", "rel", "class"})}


def _reject_unknown(attrs: Mapping[str, Any], known: frozenset[str], path: str) -> None:
    """Unknown attributes fail the save (decided 2026-10-04): an editor feature the server
    schema doesn't know must surface, not be silently lost."""
    for key in attrs:
        if key not in known:
            raise _InvalidNodeError(f"{path}.{key}", f"unknown attribute {key!r}")


def _core_attrs(node_type: str, attrs: Mapping[str, Any], path: str) -> dict[str, Any]:
    """Validated attributes of a core node."""
    _reject_unknown(attrs, _ATTR_KEYS.get(node_type, frozenset()), path)
    validate = _ATTRS.get(node_type)
    return validate(attrs, path) if validate else {}


def safe_href(href: Any) -> bool:
    if not isinstance(href, str) or len(href) > MAX_HREF or any(c.isspace() for c in href):
        return False
    try:
        parts = urlsplit(href)
    except ValueError:
        return False
    if parts.scheme.lower() not in SAFE_SCHEMES:
        return False
    return parts.scheme.lower() == "mailto" or bool(parts.hostname)


class _Validator:
    def __init__(self, handlers: Mapping[str, RichTextNodeHandler]) -> None:
        self.handlers = handlers

    def group_of(self, node_type: str) -> str | None:
        if node_type in _CORE_NODES:
            return _CORE_NODES[node_type][0]
        return self.handlers[node_type].group

    def node(self, node: Any, path: str, allowed: str, depth: int) -> Node:
        if depth > MAX_DEPTH:
            raise _InvalidNodeError(path, f"nesting deeper than {MAX_DEPTH} levels")
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            raise _InvalidNodeError(path, "must be a node object with a type")
        node_type = node["type"]
        if node_type not in _CORE_NODES and node_type not in self.handlers:
            raise _InvalidNodeError(f"{path}.type", f"unknown node type {node_type!r}")
        fits = (
            node_type == allowed
            or (allowed == "cell" and node_type in _CELLS)
            or self.group_of(node_type) == allowed
        )
        if not fits:
            raise _InvalidNodeError(f"{path}.type", f"a {node_type!r} node isn't allowed here")
        attrs = node.get("attrs") or {}
        if not isinstance(attrs, dict):
            raise _InvalidNodeError(f"{path}.attrs", "must be an object")
        result: Node = {"type": node_type}
        clean, content_group = self.attrs_and_content(node_type, attrs, path)
        if clean:
            result["attrs"] = clean
        if node_type == "text":
            return self.text(node, result, path, in_code=allowed == "text")
        if node.get("marks"):
            raise _InvalidNodeError(f"{path}.marks", "only text nodes carry marks")
        content = node.get("content")
        if content_group is None:
            if content:
                raise _InvalidNodeError(f"{path}.content", f"a {node_type!r} node has no content")
            return result
        if not isinstance(content or [], list):
            raise _InvalidNodeError(f"{path}.content", "must be a list of nodes")
        result["content"] = [
            self.node(child, f"{path}.content.{index}", content_group, depth + 1)
            for index, child in enumerate(content or [])
        ]
        return result

    def attrs_and_content(
        self, node_type: str, attrs: dict[str, Any], path: str
    ) -> tuple[dict[str, Any], str | None]:
        if node_type in _CORE_NODES:
            return _core_attrs(node_type, attrs, f"{path}.attrs"), _CORE_NODES[node_type][1]
        handler = self.handlers[node_type]
        try:
            clean = handler.validate_attrs(dict(attrs))
        except ValueError as exc:
            raise _InvalidNodeError(f"{path}.attrs", str(exc)) from exc
        return clean, handler.group if handler.has_content else None

    def text(self, node: Node, result: Node, path: str, *, in_code: bool) -> Node:
        text = node.get("text")
        if not isinstance(text, str) or not text:
            raise _InvalidNodeError(f"{path}.text", "a text node needs non-empty text")
        result["text"] = text
        marks = self.marks(node.get("marks"), f"{path}.marks", in_code=in_code)
        if marks:
            result["marks"] = marks
        return result

    def marks(self, marks: Any, path: str, *, in_code: bool) -> list[Node]:
        if marks is None:
            return []
        if not isinstance(marks, list):
            raise _InvalidNodeError(path, "must be a list of marks")
        if in_code and marks:
            raise _InvalidNodeError(path, "code blocks hold plain text")
        result: list[Node] = []
        for index, mark in enumerate(marks):
            where = f"{path}.{index}"
            if not isinstance(mark, dict) or mark.get("type") not in CORE_MARK_TYPES:
                kind = mark.get("type") if isinstance(mark, dict) else None
                raise _InvalidNodeError(f"{where}.type", f"unknown mark type {kind!r}")
            attrs = mark.get("attrs") or {}
            if not isinstance(attrs, dict):
                raise _InvalidNodeError(f"{where}.attrs", "must be an object")
            ignored = IGNORED_MARK_ATTRS.get(mark["type"], frozenset())
            _reject_unknown(
                {k: v for k, v in attrs.items() if k not in ignored},
                _MARK_KEYS.get(mark["type"], frozenset()),
                f"{where}.attrs",
            )
            if mark["type"] == "link":
                if not safe_href(attrs.get("href")):
                    continue  # unsafe or invalid: drop the mark, keep the text (decided)
                result.append({"type": "link", "attrs": {"href": attrs["href"]}})
            elif mark["type"] == "entityLink":
                entity_id = attrs.get("entityId")
                if not isinstance(entity_id, str) or _ID.fullmatch(entity_id) is None:
                    raise _InvalidNodeError(f"{where}.attrs.entityId", "must be an entity id")
                result.append({"type": "entityLink", "attrs": {"entityId": entity_id}})
            else:
                result.append({"type": mark["type"]})
        return result


def validate_document(
    doc: Any,
    handlers: Mapping[str, RichTextNodeHandler] | None = None,
    *,
    path: str = "body",
) -> Node:
    """The normalized document; ``InvalidInputError`` with the path of the first problem."""
    try:
        if not isinstance(doc, dict) or doc.get("type") != "doc":
            raise _InvalidNodeError(path, "must be a rich-text document (type doc)")
        return _Validator(handlers or {}).node(doc, path, "doc", 0)
    except _InvalidNodeError as exc:
        error: ErrorItem = {"path": exc.path, "code": "invalid_value", "message": exc.message}
        raise InvalidInputError(f"Invalid rich text: {exc.message}", errors=[error]) from exc


def handler_map(handlers: Sequence[RichTextNodeHandler]) -> dict[str, RichTextNodeHandler]:
    return {handler.type: handler for handler in handlers}
