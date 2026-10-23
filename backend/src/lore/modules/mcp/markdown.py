"""Markdown in, rich text stored (``docs/modules/mcp.md``, Writing): the bodies the write tools
take, as rich-text documents (``frontend.md`` §6), which the entity service then validates.

The common Markdown an assistant writes: ATX headings, paragraphs (a line ending in two spaces or
a backslash is a hard break), bullet and ordered lists (nested by indentation), block quotes,
fenced code blocks, horizontal rules; inline ``**bold**``, ``*italic*``, ``~~strike~~``,
``code`` and ``[links](https://…)``. A link to ``lore://{vault}/entities/{id}`` (the URIs the read
tools give) becomes an entity link. Anything else is kept as text.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lore.core.entities.schemas import ID_PATTERN
from lore.core.richtext.schema import safe_href

type Node = dict[str, Any]
type Mark = dict[str, Any]

MAX_HEADING = 4  # the schema's deepest heading

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([A-Za-z0-9_+#.-]{1,40})?.*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:\s+(.*?))?\s*#*\s*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_ITEM = re.compile(r"^( {0,3})([-*+]|(\d{1,9})[.)])(?:\s+(.*))?$")
_LINK = re.compile(r"\[((?:\\.|[^\]\\])*)\]\(\s*<?([^\s>)]*)>?(?:\s+\"[^\"]*\")?\s*\)")
_ID = re.compile(ID_PATTERN)
_ESCAPABLE = frozenset("\\`*_{}[]()#+-.!~>|")


@dataclass(frozen=True)
class _Item:
    ordered: bool
    start: int
    indent: int  # the item's content starts this many columns in


def to_rich_text(text: str, vault_id: str) -> Node:
    """The document of a Markdown text."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")
    return {
        "type": "doc",
        "content": _Blocks(vault_id).parse(lines) or [{"type": "paragraph", "content": []}],
    }


def _item(line: str) -> _Item | None:
    match = _ITEM.match(line)
    if match is None:
        return None
    number = match.group(3)
    indent = match.start(4) if match.group(4) is not None else match.end(2) + 1
    return _Item(number is not None, int(number or 1), indent)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _starts_block(line: str) -> bool:
    """Whether ``line`` interrupts a paragraph (an empty list item doesn't)."""
    if any(pattern.match(line) for pattern in (_FENCE, _HEADING, _RULE, _QUOTE)):
        return True
    item = _ITEM.match(line)
    return item is not None and item.group(4) is not None


class _Blocks:
    def __init__(self, vault_id: str) -> None:
        self.inline = _Inline(vault_id)

    def parse(self, lines: Sequence[str]) -> list[Node]:
        nodes: list[Node] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
            elif fence := _FENCE.match(line):
                i = self._code(lines, i, fence, nodes)
            elif heading := _HEADING.match(line):
                level = min(len(heading.group(1)), MAX_HEADING)
                nodes.append(self._textblock("heading", heading.group(2) or "", {"level": level}))
                i += 1
            elif _RULE.match(line):
                nodes.append({"type": "horizontalRule"})
                i += 1
            elif _QUOTE.match(line):
                i = self._quote(lines, i, nodes)
            elif (item := _item(line)) is not None:
                i = self._list(lines, i, item, nodes)
            else:
                i = self._paragraph(lines, i, nodes)
        return nodes

    def _code(self, lines: Sequence[str], i: int, fence: re.Match[str], nodes: list[Node]) -> int:
        marker = fence.group(1)
        body: list[str] = []
        i += 1
        while i < len(lines) and not lines[i].strip().startswith(marker):
            body.append(lines[i])
            i += 1
        text = "\n".join(body)
        content = [{"type": "text", "text": text}] if text else []
        nodes.append(
            {"type": "codeBlock", "attrs": {"language": fence.group(2)}, "content": content}
        )
        return i + 1

    def _quote(self, lines: Sequence[str], i: int, nodes: list[Node]) -> int:
        inner: list[str] = []
        while i < len(lines) and (quoted := _QUOTE.match(lines[i])):
            inner.append(quoted.group(1))
            i += 1
        nodes.append(
            {
                "type": "blockquote",
                "content": self.parse(inner) or [{"type": "paragraph", "content": []}],
            }
        )
        return i

    def _list(self, lines: Sequence[str], i: int, first: _Item, nodes: list[Node]) -> int:
        items: list[Node] = []
        while i < len(lines):
            item = _item(lines[i])
            if item is None or item.ordered != first.ordered:
                break
            content = [lines[i][item.indent :] if len(lines[i]) > item.indent else ""]
            i += 1
            while i < len(lines):
                line = lines[i]
                indented = _indent(line) >= item.indent
                if line.strip() and indented:
                    content.append(line[item.indent :])
                elif not line.strip():
                    following = next((n for n in lines[i + 1 :] if n.strip()), None)
                    if (
                        following is None
                        or len(following) - len(following.lstrip(" ")) < item.indent
                    ):
                        break
                    content.append("")
                elif content[-1].strip() and not _starts_block(line) and _item(line) is None:
                    content.append(line.strip())  # a lazy continuation of the paragraph
                else:
                    break
                i += 1
            items.append(
                {
                    "type": "listItem",
                    "content": self.parse(content) or [{"type": "paragraph", "content": []}],
                }
            )
            if i < len(lines) and not lines[i].strip():
                resume = next((j for j in range(i, len(lines)) if lines[j].strip()), None)
                if resume is None or _item(lines[resume]) is None:
                    break
                i = resume
        if first.ordered:
            nodes.append({"type": "orderedList", "attrs": {"start": first.start}, "content": items})
        else:
            nodes.append({"type": "bulletList", "content": items})
        return i

    def _paragraph(self, lines: Sequence[str], i: int, nodes: list[Node]) -> int:
        parts: list[str] = []
        while i < len(lines) and lines[i].strip() and (not parts or not _starts_block(lines[i])):
            parts.append(lines[i])
            i += 1
        nodes.append(self._paragraph_node(parts))
        return i

    def _paragraph_node(self, parts: Sequence[str]) -> Node:
        content: list[Node] = []
        for index, part in enumerate(parts):
            hard = part.endswith(("  ", "\\")) and index < len(parts) - 1
            text = part.strip().removesuffix("\\").rstrip() if hard else part.strip()
            if index > 0 and not (content and content[-1]["type"] == "hardBreak"):
                text = " " + text
            content.extend(self.inline.parse(text))
            if hard:
                content.append({"type": "hardBreak"})
        return _with_content({"type": "paragraph"}, _merged(content))

    def _textblock(self, kind: str, text: str, attrs: dict[str, Any]) -> Node:
        return _with_content({"type": kind, "attrs": attrs}, self.inline.parse(text.strip()))


class _Inline:
    def __init__(self, vault_id: str) -> None:
        self.entity_prefix = f"lore://{vault_id}/entities/"

    def parse(self, text: str, marks: tuple[Mark, ...] = ()) -> list[Node]:
        nodes: list[Node] = []
        plain: list[str] = []

        def flush() -> None:
            if plain:
                nodes.append(_text("".join(plain), marks))
                plain.clear()

        i = 0
        while i < len(text):
            char = text[i]
            if char == "\\" and i + 1 < len(text) and text[i + 1] in _ESCAPABLE:
                plain.append(text[i + 1])
                i += 2
                continue
            found = self._span(text, i, marks)
            if found is None:
                plain.append(char)
                i += 1
                continue
            inner, end = found
            flush()
            nodes.extend(inner)
            i = end
        flush()
        return _merged(nodes)

    def _span(self, text: str, i: int, marks: tuple[Mark, ...]) -> tuple[list[Node], int] | None:
        """The marked span starting at ``i`` (its nodes and where it ends), if one does."""
        char = text[i]
        if char == "`":
            return self._code(text, i, marks)
        if char == "[" and (link := _LINK.match(text, i)):
            found = self._link(link.group(2))
            return self.parse(link.group(1), (*marks, found) if found else marks), link.end()
        for delimiter, mark in (("**", "bold"), ("__", "bold"), ("~~", "strike")):
            if text.startswith(delimiter, i):
                close = text.find(delimiter, i + 2)
                if close > i + 2:
                    inner = self.parse(text[i + 2 : close], (*marks, {"type": mark}))
                    return inner, close + 2
        if char in "*_" and i + 1 < len(text) and not text[i + 1].isspace():
            return self._italic(text, i, marks)
        return None

    @staticmethod
    def _code(text: str, i: int, marks: tuple[Mark, ...]) -> tuple[list[Node], int] | None:
        ticks = len(text[i:]) - len(text[i:].lstrip("`"))
        close = text.find("`" * ticks, i + ticks)
        if close == -1:
            return None
        code = text[i + ticks : close].strip(" ") or text[i + ticks : close]
        return [_text(code, (*marks, {"type": "code"}))], close + ticks

    def _italic(self, text: str, i: int, marks: tuple[Mark, ...]) -> tuple[list[Node], int] | None:
        char = text[i]
        if char == "_" and i > 0 and text[i - 1].isalnum():
            return None  # snake_case
        close = i + 2  # not empty
        while (close := text.find(char, close)) != -1:
            doubled = text.startswith(char * 2, close)
            if not doubled and not text[close - 1].isspace():
                break
            close += 2 if doubled else 1
        if close == -1:
            return None
        return self.parse(text[i + 1 : close], (*marks, {"type": "italic"})), close + 1

    def _link(self, href: str) -> Mark | None:
        """An entity link for this vault's entity URIs, a link for safe URLs, else no mark (the
        text stays)."""
        if href.startswith(self.entity_prefix):
            entity_id = href.removeprefix(self.entity_prefix).strip("/")
            if _ID.fullmatch(entity_id):
                return {"type": "entityLink", "attrs": {"entityId": entity_id}}
        return {"type": "link", "attrs": {"href": href}} if safe_href(href) else None


def _text(text: str, marks: tuple[Mark, ...]) -> Node:
    node: Node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(_unique(marks))
    return node


def _unique(marks: Sequence[Mark]) -> list[Mark]:
    out: list[Mark] = []
    for mark in marks:
        if all(existing["type"] != mark["type"] for existing in out):
            out.append(mark)
    return out


def _merged(nodes: Sequence[Node]) -> list[Node]:
    """Adjacent text nodes with the same marks as one; empty ones dropped."""
    out: list[Node] = []
    for node in nodes:
        if node["type"] == "text" and not node["text"]:
            continue
        previous = out[-1] if out else None
        if (
            previous is not None
            and node["type"] == previous["type"] == "text"
            and node.get("marks") == previous.get("marks")
        ):
            out[-1] = {**previous, "text": previous["text"] + node["text"]}
        else:
            out.append(node)
    return out


def _with_content(node: Node, content: list[Node]) -> Node:
    node["content"] = content
    return node
