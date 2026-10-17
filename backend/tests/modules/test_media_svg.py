"""SVG sanitization (``lore.modules.media.svg``, ``security.md`` §3): what draws is kept, what
runs, loads or navigates is not."""

import pytest

from lore.modules.media.svg import SvgRejectedError, sanitize

OPEN = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'


def clean(body: str, root: str = OPEN) -> str:
    return sanitize(f"{root}{body}</svg>".encode()).decode()


def inner(body: str) -> str:
    """The sanitized content of an ``svg`` root."""
    out = clean(body)
    prefix = '<svg xmlns="http://www.w3.org/2000/svg">'
    if out == '<svg xmlns="http://www.w3.org/2000/svg" />':
        return ""
    assert out.startswith(prefix), out
    return out.removeprefix(prefix).removesuffix("</svg>")


def test_drawings_are_kept() -> None:
    body = (
        '<defs><linearGradient id="g"><stop offset="0" stop-color="gold" /></linearGradient>'
        '<filter id="f"><feGaussianBlur stdDeviation="2" /></filter></defs>'
        '<g transform="translate(1 2)"><path d="M0 0L5 5" fill="url(#g)" filter="url(#f)" />'
        '<text x="1" y="2" font-family="Curlz">Aetheria<tspan dx="1">!</tspan></text></g>'
        '<use href="#g" /><style>.a { fill: url("#g") } a &gt; b {}</style>'
    )
    assert inner(body) == body


def test_the_root_keeps_its_drawing_attributes_and_gains_its_namespace() -> None:
    assert sanitize(b'<svg viewBox="0 0 4 4" width="4"><rect width="1" /></svg>') == (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4" width="4">'
        b'<rect width="1" /></svg>'
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<script>alert(1)</script><rect />", "<rect />"),
        ('<rect onclick="alert(1)" onload="x" />', "<rect />"),
        ("<foreignObject><div>hi</div></foreignObject>", ""),
        ('<animate attributeName="href" to="javascript:alert(1)" /><set to="x" />', ""),
        ('<a href="javascript:alert(1)"><rect />after</a>', "<rect />after"),
        ('<a xlink:href="https://example.com">text</a>', "text"),
        ('<use xlink:href="#sigil" />', '<use href="#sigil" />'),
        ('<use href="https://example.com/x.svg#sigil" />', "<use />"),
        ('<use href="  javascript:alert(1)" />', "<use />"),
        (
            '<image href="data:image/png;base64,iVBORw0KGgo=" />',
            '<image href="data:image/png;base64,iVBORw0KGgo=" />',
        ),
        ('<image href="data:image/svg+xml;base64,PHN2Zz4=" />', "<image />"),
        ('<image href="https://example.com/tracker.png" />', "<image />"),
        ('<use href="data:image/png;base64,iVBORw0KGgo=" />', "<use />"),
        ('<rect fill="url(https://example.com/x)" stroke="red" />', '<rect stroke="red" />'),
        ('<rect style="fill: url(//example.com/x)" />', "<rect />"),
        ("<rect style=\"background: image-set('x.png' 1x)\" />", "<rect />"),
        ('<rect style="fill: u\\72l(x)" />', "<rect />"),
        ('<rect style="fill: red" />', '<rect style="fill: red" />'),
        ("<style>@import url(https://example.com/a.css);</style>", ""),
        ("<style>@font-face { src: url(https://example.com/f.woff) }</style>", ""),
        (
            '<rect xml:base="https://example.com/" xml:space="preserve" />',
            '<rect xml:space="preserve" />',
        ),
        (
            '<rect xmlns:x="urn:x" x:evil="1" width="2" /><x:thing xmlns:x="urn:x" />',
            '<rect width="2" />',
        ),
        ("<unknown><rect /></unknown>tail", "tail"),
        ("<!-- comment --><?pi data?><rect />", "<rect />"),
    ],
)
def test_what_runs_loads_or_navigates_is_dropped(body: str, expected: str) -> None:
    assert inner(body) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"not xml",
        b"<svg><g></svg>",
        b'<html xmlns="http://www.w3.org/1999/xhtml"><svg /></html>',
        b'<svg xmlns="urn:other" />',
        # Entities (billion laughs, external files) are refused outright.
        b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>',
        b'<!DOCTYPE svg [<!ENTITY a SYSTEM "file:///etc/passwd">]><svg>&a;</svg>',
    ],
)
def test_files_that_cant_be_read_are_refused(data: bytes) -> None:
    with pytest.raises(SvgRejectedError):
        sanitize(data)
