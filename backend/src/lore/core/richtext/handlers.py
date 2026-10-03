"""``RichTextNodeHandler``: how a module's own node types (e.g. the media module's ``image``) are
validated, filtered for readers and mined for text and references (``modules.md`` §2.1).

Handlers of **every** module are used for validation and filtering, enabled or not: documents
keep their module nodes while a module is disabled, and saving such a document must still work.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

type Node = dict[str, Any]


def _keep(node: Node, _visible: frozenset[str]) -> Node | None:
    return node


def _no_text(_node: Node) -> str:
    return ""


def _no_refs(_node: Node) -> list[str]:
    return []


@dataclass(frozen=True)
class RichTextNodeHandler:
    type: str  # the node's ``type``; must not clash with core's nodes
    group: Literal["block", "inline"]
    # attrs -> normalized attrs; raise ValueError (its message is reported) for bad attrs
    validate_attrs: Callable[[dict[str, Any]], dict[str, Any]]
    # (node, visible entity ids) -> the node for readers, or None to drop it
    filter_for_reader: Callable[[Node, frozenset[str]], Node | None] = _keep
    extract_text: Callable[[Node], str] = _no_text
    ref_kind: str | None = None  # e.g. "media": extract_refs results are grouped under it
    extract_refs: Callable[[Node], list[str]] = _no_refs
    has_content: bool = False  # True: holds child nodes of its group's content
