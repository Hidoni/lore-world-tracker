"""Markdown in, rich text stored (``lore.modules.mcp.markdown``): every document is valid rich
text, and the common constructs map to their nodes and marks."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.core.richtext.schema import validate_document
from lore.modules.mcp.markdown import to_rich_text

VAULT = "v"
ENTITY = "01a16692-956b-722c-a485-716c56277b32"


def _blocks(text: str) -> list[dict[str, Any]]:
    doc = to_rich_text(text, VAULT)
    assert validate_document(doc) == doc
    content: list[dict[str, Any]] = doc["content"]
    return content


def _text(text: str, *marks: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def _paragraph(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


BOLD, ITALIC, CODE, STRIKE = ({"type": t} for t in ("bold", "italic", "code", "strike"))


@pytest.mark.parametrize(
    ("markdown", "blocks"),
    [
        ("", [_paragraph()]),
        ("Hello", [_paragraph(_text("Hello"))]),
        ("one\ntwo", [_paragraph(_text("one two"))]),
        ("one  \ntwo", [_paragraph(_text("one"), {"type": "hardBreak"}, _text("two"))]),
        ("one\\\ntwo", [_paragraph(_text("one"), {"type": "hardBreak"}, _text("two"))]),
        ("a\n\nb", [_paragraph(_text("a")), _paragraph(_text("b"))]),
        (
            "## Title ##",
            [{"type": "heading", "attrs": {"level": 2}, "content": [_text("Title")]}],
        ),
        ("###### Deep", [{"type": "heading", "attrs": {"level": 4}, "content": [_text("Deep")]}]),
        ("#", [{"type": "heading", "attrs": {"level": 1}, "content": []}]),
        ("---", [{"type": "horizontalRule"}]),
        (
            "**b** *i* _i_ `c` ~~s~~ __b__",
            [
                _paragraph(
                    _text("b", BOLD),
                    _text(" "),
                    _text("i", ITALIC),
                    _text(" "),
                    _text("i", ITALIC),
                    _text(" "),
                    _text("c", CODE),
                    _text(" "),
                    _text("s", STRIKE),
                    _text(" "),
                    _text("b", BOLD),
                )
            ],
        ),
        ("**bold _both_**", [_paragraph(_text("bold ", BOLD), _text("both", BOLD, ITALIC))]),
        ("snake_case_name", [_paragraph(_text("snake_case_name"))]),
        ("2 * 3 * 4", [_paragraph(_text("2 * 3 * 4"))]),
        ("\\*not\\*", [_paragraph(_text("*not*"))]),
        ("`a **b**`", [_paragraph(_text("a **b**", CODE))]),
        ("unclosed **bold", [_paragraph(_text("unclosed **bold"))]),
        (
            f"[web](https://example.org) [Mira](lore://v/entities/{ENTITY})",
            [
                _paragraph(
                    _text("web", {"type": "link", "attrs": {"href": "https://example.org"}}),
                    _text(" "),
                    _text("Mira", {"type": "entityLink", "attrs": {"entityId": ENTITY}}),
                )
            ],
        ),
        # An unsafe link loses its mark, keeping the text (the rich-text validator's rule).
        ("[x](javascript:alert(1))", [_paragraph(_text("x)"))]),
        (
            "> quoted\n> more",
            [{"type": "blockquote", "content": [_paragraph(_text("quoted more"))]}],
        ),
        (
            "```python\nx = 1\n\ny = 2\n```",
            [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "python"},
                    "content": [_text("x = 1\n\ny = 2")],
                }
            ],
        ),
        ("```\n```", [{"type": "codeBlock", "attrs": {"language": None}, "content": []}]),
        ("[not an id](lore://v/entities/x)", [_paragraph(_text("not an id"))]),
    ],
)
def test_blocks_and_marks(markdown: str, blocks: list[dict[str, Any]]) -> None:
    assert _blocks(markdown) == blocks


def _item(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "listItem", "content": list(content)}


def test_lists() -> None:
    text = "- one\n- two\n  - nested\n  continued\n\n- three\n\n3. c\n4. d\n\nafter"
    assert _blocks(text) == [
        {
            "type": "bulletList",
            "content": [
                _item(_paragraph(_text("one"))),
                _item(
                    _paragraph(_text("two")),
                    {
                        "type": "bulletList",
                        "content": [_item(_paragraph(_text("nested continued")))],
                    },
                ),
                _item(_paragraph(_text("three"))),
            ],
        },
        {
            "type": "orderedList",
            "attrs": {"start": 3},
            "content": [_item(_paragraph(_text("c"))), _item(_paragraph(_text("d")))],
        },
        _paragraph(_text("after")),
    ]


def test_a_list_item_with_paragraphs() -> None:
    assert _blocks("1. first\n\n   second\n2. next") == [
        {
            "type": "orderedList",
            "attrs": {"start": 1},
            "content": [
                _item(_paragraph(_text("first")), _paragraph(_text("second"))),
                _item(_paragraph(_text("next"))),
            ],
        }
    ]


def test_blocks_interrupt_paragraphs() -> None:
    assert [b["type"] for b in _blocks("text\n# Heading\ntext\n- item\n> quote")] == [
        "paragraph",
        "heading",
        "paragraph",
        "bulletList",
        "blockquote",
    ]


@given(st.text(alphabet=st.sampled_from(list("ab *_`~[]()#->\\\n 1.!")), max_size=80))
def test_any_text_is_valid_rich_text(text: str) -> None:
    doc = to_rich_text(text, VAULT)
    assert validate_document(doc) == doc
