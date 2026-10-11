"""Renaming an entity relabels the links to it (decided 2026-10-11, #70): in a document, a run of
text carrying ``entityLink`` to the entity whose text is exactly the old name becomes the new
name. Other link text (custom labels, aliases) is the author's and stays."""

from collections.abc import Iterable
from typing import Any

from lore.core.richtext.handlers import Node


def _links_to(node: Node, target_id: str) -> bool:
    return node.get("type") == "text" and any(
        mark.get("type") == "entityLink" and (mark.get("attrs") or {}).get("entityId") == target_id
        for mark in node.get("marks") or []
    )


def _relabel_content(
    content: list[Node], target_id: str, old: str, new: str
) -> tuple[list[Node], bool]:
    """A content list with link runs relabeled. A run is consecutive text nodes linking to the
    target (formatting may split it); a matching run becomes one node with the first's marks."""
    result: list[Node] = []
    changed = False
    index = 0
    while index < len(content):
        node = content[index]
        if _links_to(node, target_id):
            end = index
            while end < len(content) and _links_to(content[end], target_id):
                end += 1
            run = content[index:end]
            if "".join(str(part.get("text", "")) for part in run) == old:
                result.append({**run[0], "text": new})
                changed = True
            else:
                result.extend(run)
            index = end
            continue
        children = node.get("content")
        if isinstance(children, list):
            relabeled, child_changed = _relabel_content(children, target_id, old, new)
            if child_changed:
                node = {**node, "content": relabeled}
                changed = True
        result.append(node)
        index += 1
    return result, changed


def relabel_links(doc: Any, target_id: str, old: str, new: str) -> tuple[Any, bool]:
    """``doc`` with its links to ``target_id`` reading ``old`` relabeled ``new``, and whether
    anything changed. Not a document: returned as it is."""
    if not isinstance(doc, dict) or not isinstance(doc.get("content"), list) or old == new:
        return doc, False
    content, changed = _relabel_content(doc["content"], target_id, old, new)
    return ({**doc, "content": content} if changed else doc), changed


def relabel_values(
    values: Iterable[Any], target_id: str, old: str, new: str
) -> tuple[list[Any], bool]:
    """A list of documents (a multiple ``rich_text`` field) relabeled."""
    out: list[Any] = []
    changed = False
    for value in values:
        relabeled, one = relabel_links(value, target_id, old, new)
        out.append(relabeled)
        changed = changed or one
    return out, changed
