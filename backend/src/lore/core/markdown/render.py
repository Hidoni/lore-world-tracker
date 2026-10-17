"""Rich text, names and properties as Markdown (``docs/architecture/markdown-export.md`` §3).

Pure functions: what a document refers to (entities, dates, module nodes) is looked up through
the ``Inline`` callbacks the exporter passes, so this module knows nothing of the vault. The
output is CommonMark with the Obsidian extensions the export targets: ``[[wikilinks]]``,
callouts (``> [!note]``) and YAML frontmatter ("properties").
"""

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lore.core.richtext.handlers import Node

# A module's node as Markdown: ``block`` nodes return block text (several lines are fine),
# ``inline`` nodes a piece of a line.
type NodeRenderer = Callable[[Node], str]

# Characters escaped in text: Markdown syntax, plus what Obsidian reads anywhere in a line
# (``#tag``, ``$math$``, ``[[links]]``, ``==highlights==`` need ``=`` only in pairs: left alone).
_ESCAPED = re.compile(r"([\\`*_\[\]<>|#$~&])")
# A line starting like a block (list item, heading, quote, rule, ordered item): escaped.
_BLOCK_START = re.compile(r"^(\s*)([-+=>]|\d{1,9}[.)])(?=\s|$)")
_FENCE = re.compile(r"`{3,}")
# Not allowed in file names on common systems, or meaningful in Obsidian links.
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"{port}{i}" for port in ("com", "lpt") for i in range(1, 10))}
)
MAX_NAME = 120
_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_TAG_UNSAFE = re.compile(r"[^\w/-]")
_CALLOUT_TONES = {"note": "note", "warning": "warning", "quote": "quote"}


def escape(text: str) -> str:
    """Text as Markdown that renders as the text itself."""
    return _ESCAPED.sub(r"\\\1", text)


def file_name(name: str) -> str:
    """A note or folder name for ``name``: safe on Windows, macOS and Linux and in Obsidian
    links (unsafe characters become spaces), at most ``MAX_NAME`` characters, never empty."""
    cleaned = _SPACES.sub(" ", _UNSAFE_NAME.sub(" ", unicodedata.normalize("NFC", name)))
    cleaned = cleaned.strip().strip(".").strip()[:MAX_NAME].strip()
    if not cleaned:
        return "Untitled"
    if cleaned.split(".")[0].casefold() in _RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned


def tag_name(name: str) -> str | None:
    """A Lore tag as an Obsidian tag (letters, digits, ``_``, ``-``, ``/``; not only digits), or
    None when nothing usable is left."""
    tag = _TAG_UNSAFE.sub("", _SPACES.sub("-", name.strip()))
    if not tag:
        return None
    return f"_{tag}" if tag.isdigit() else tag


def wikilink(target: str, label: str | None = None) -> str:
    """``[[target]]``, or ``[[target|label]]`` when the label differs (``]`` and ``|`` can't be
    part of a label)."""
    if label is None:
        return f"[[{target}]]"
    shown = label.replace("|", " ").replace("]", " ").replace("[", " ").strip()
    return f"[[{target}]]" if shown in ("", target) else f"[[{target}|{shown}]]"


# --- frontmatter --------------------------------------------------------------------------------


def frontmatter(properties: Mapping[str, Any]) -> str:
    """A YAML frontmatter block (with its ``---`` lines). Strings are double-quoted (JSON string
    syntax is valid YAML), so values never change type or meaning when read back."""
    lines = ["---", *_mapping(properties, 0), "---"]
    return "\n".join(lines) + "\n"


def _key(key: str) -> str:
    return key if _PLAIN_KEY.match(key) else json.dumps(key, ensure_ascii=False)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _mapping(values: Mapping[str, Any], indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for key, value in values.items():
        if isinstance(value, Mapping) and value:
            lines.append(f"{pad}{_key(key)}:")
            lines.extend(_mapping(value, indent + 2))
        elif isinstance(value, list | tuple) and value:
            lines.append(f"{pad}{_key(key)}:")
            lines.extend(_sequence(value, indent + 2))
        elif isinstance(value, Mapping):
            lines.append(f"{pad}{_key(key)}: {{}}")
        elif isinstance(value, list | tuple):
            lines.append(f"{pad}{_key(key)}: []")
        else:
            lines.append(f"{pad}{_key(key)}: {_scalar(value)}")
    return lines


def _sequence(values: Sequence[Any], indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for value in values:
        if isinstance(value, Mapping) and value:
            nested = _mapping(value, indent + 2)
            lines.append(f"{pad}- {nested[0].lstrip()}")
            lines.extend(nested[1:])
        else:
            lines.append(f"{pad}- {_scalar(value)}")
    return lines


# --- rich text ----------------------------------------------------------------------------------


@dataclass
class Inline:
    """What rendering a document needs from the vault. ``entity_link(id, text)``: the link to
    an entity, or None when it isn't exported (the text stays). ``time_ref(attrs)``: a
    ``timeRef`` as text. ``nodes``: module node renderers; ``fallback_text``: a module node
    without one (its handler's text, e.g. an image's alt text)."""

    entity_link: Callable[[str, str], str | None]
    time_ref: Callable[[Mapping[str, Any]], str]
    nodes: Mapping[str, NodeRenderer] = field(default_factory=dict)
    fallback_text: Callable[[Node], str] = lambda _node: ""


def to_markdown(doc: Node | None, inline: Inline) -> str:
    """A (validated, already filtered) rich-text document as Markdown, without a trailing
    newline (empty for an empty document)."""
    if doc is None:
        return ""
    return "\n\n".join(_blocks(doc.get("content") or (), inline))


def _blocks(nodes: Sequence[Node], inline: Inline) -> list[str]:
    return [text for node in nodes if (text := _block(node, inline))]


def _quoted(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))


def _indented(text: str, marker: str) -> str:
    """A list item: the marker on the first line, the other lines indented under it."""
    pad = " " * len(marker)
    first, *rest = text.split("\n")
    return "\n".join([f"{marker}{first}", *(f"{pad}{line}" if line else "" for line in rest)])


def _block(node: Node, inline: Inline) -> str:  # noqa: PLR0911, PLR0912 (one case per node type)
    node_type = node.get("type")
    attrs = node.get("attrs") or {}
    content: Sequence[Node] = node.get("content") or ()
    match node_type:
        case "paragraph":
            return _line_starts(_inlines(content, inline))
        case "heading":
            text = _inlines(content, inline).replace("\n", " ")
            return f"{'#' * int(attrs.get('level', 1))} {text}" if text else ""
        case "blockquote":
            inner = "\n\n".join(_blocks(content, inline))
            return _quoted(inner) if inner else ""
        case "bulletList" | "orderedList":
            return _list(node_type, attrs, content, inline)
        case "codeBlock":
            code = "".join(str(child.get("text", "")) for child in content)
            fence = "`" * max(3, *(len(run) + 1 for run in _FENCE.findall(code)))
            return f"{fence}{attrs.get('language') or ''}\n{code}\n{fence}"
        case "horizontalRule":
            return "---"
        case "table":
            return _table(content, inline)
        case "visibilityBlock":
            inner = "\n\n".join(_blocks(content, inline))
            label = attrs.get("label") or ""
            if attrs.get("level") == "spoiler":
                head = f"[!spoiler]- {escape(label) or 'Spoiler'}"
            else:
                head = f"[!private] {escape(label) or 'Private'}"
            return _quoted(f"{head}\n{inner}" if inner else head)
        case "callout":
            inner = "\n\n".join(_blocks(content, inline))
            head = f"[!{_CALLOUT_TONES.get(str(attrs.get('tone')), 'note')}]"
            return _quoted(f"{head}\n{inner}" if inner else head)
        case _:
            renderer = inline.nodes.get(str(node_type))
            if renderer is not None:
                return renderer(node)
            if content:  # a module block with content (none yet): keep what it holds
                return "\n\n".join(_blocks(content, inline))
            return _line_starts(escape(inline.fallback_text(node)))


def _list(node_type: str, attrs: Mapping[str, Any], items: Sequence[Node], inline: Inline) -> str:
    start = int(attrs.get("start", 1))
    out: list[str] = []
    for index, item in enumerate(items):
        marker = "- " if node_type == "bulletList" else f"{start + index}. "
        inner = "\n\n".join(_blocks(item.get("content") or (), inline))
        out.append(_indented(inner, marker) if inner else marker.rstrip())
    return "\n".join(out)


def _table(rows: Sequence[Node], inline: Inline) -> str:
    cells = [
        [
            "<br>".join(_blocks(cell.get("content") or (), inline)).replace("\n", "<br>")
            for cell in row.get("content") or ()
        ]
        for row in rows
    ]
    width = max((len(row) for row in cells), default=0)
    if width == 0:
        return ""
    lines = []
    for index, row in enumerate(cells):
        padded = [*row, *([""] * (width - len(row)))]
        lines.append("| " + " | ".join(padded) + " |")
        if index == 0:
            lines.append("|" + " --- |" * width)
    return "\n".join(lines)


def _line_starts(text: str) -> str:
    """Lines that would start a block (``- x``, ``1. x``) escaped, so a paragraph stays one."""

    def escaped(match: re.Match[str]) -> str:
        marker = match.group(2)  # punctuation is escaped: "\\-", "1\\." (a digit can't be)
        return f"{match.group(1)}{marker[:-1]}\\{marker[-1]}"

    return "\n".join(_BLOCK_START.sub(escaped, line) for line in text.split("\n"))


def _inlines(nodes: Sequence[Node], inline: Inline) -> str:
    """Inline nodes in order; neighbouring text nodes with the same marks are merged first, so
    emphasis isn't closed and reopened (``**a****b**``)."""
    out: list[str] = []
    pending: list[str] = []
    pending_marks: list[Node] = []
    pending_key: str | None = None

    def flush() -> None:
        nonlocal pending, pending_marks, pending_key
        if pending:
            out.append(_marked("".join(pending), pending_marks, inline))
        pending, pending_marks, pending_key = [], [], None

    for node in nodes:
        node_type = node.get("type")
        if node_type == "text":
            key = _mark_key(node)
            if key != pending_key:
                flush()
                pending_key, pending_marks = key, list(node.get("marks") or [])
            pending.append(str(node.get("text", "")))
            continue
        flush()
        if node_type == "hardBreak":
            out.append("\\\n")
        elif node_type == "timeRef":
            out.append(escape(inline.time_ref(node.get("attrs") or {})))
        else:
            renderer = inline.nodes.get(str(node_type))
            out.append(renderer(node) if renderer else escape(inline.fallback_text(node)))
    flush()
    return "".join(out)


def _mark_key(node: Node) -> str:
    return json.dumps(node.get("marks") or [], sort_keys=True)


def _marked(text: str, marks: Sequence[Node], inline: Inline) -> str:
    """A text run with its marks: ``code`` is literal, links wrap the (escaped) text, emphasis
    goes around the rest with the run's outer spaces kept outside the delimiters."""
    if not text:
        return ""
    kinds = {str(mark.get("type")): mark.get("attrs") or {} for mark in marks}
    stripped = text.strip()
    if not stripped:
        return text if "code" in kinds else escape(text)
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    if "code" in kinds:
        ticks = "`" * (max((len(run) for run in re.findall(r"`+", stripped)), default=0) + 1)
        pad = " " if stripped.startswith("`") or stripped.endswith("`") else ""
        body = f"{ticks}{pad}{stripped}{pad}{ticks}"
    else:
        body = escape(stripped)
    if "entityLink" in kinds:
        linked = inline.entity_link(str(kinds["entityLink"].get("entityId", "")), stripped)
        if linked is not None:
            body = linked
    elif "link" in kinds and "code" not in kinds:
        href = str(kinds["link"].get("href", ""))
        href = href.replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")
        body = f"[{body}]({href})"
    if "strike" in kinds:
        body = f"~~{body}~~"
    if "italic" in kinds:
        body = f"*{body}*"
    if "bold" in kinds:
        body = f"**{body}**"
    return f"{escape(lead)}{body}{escape(trail)}"
