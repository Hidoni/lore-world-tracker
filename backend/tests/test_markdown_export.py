"""The Markdown / Obsidian export (``docs/architecture/markdown-export.md``): rich text as
Markdown, notes with properties, dates in every calendar, facts and links, the download (author
only) and the CLI. The readers' export of the canary vault holds no canary (byte scan of every
file); the author's holds them."""

import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lore import cli
from lore.core.markdown.export import MANIFEST_NAME, FolderSink, MarkdownExportError
from lore.core.markdown.render import Inline, file_name, frontmatter, tag_name, to_markdown
from tests.entity_api import LinkApi, make_client, problem
from tests.visibility.canary import Canary, build_canary_vault, leak_client

DAY = 86_400


def absolute(t: int, precision: str = "base") -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": precision}


def doc(*content: Any) -> dict[str, Any]:
    return {"type": "doc", "content": list(content)}


def p(*content: Any) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


def text(value: str, *marks: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def link_to(entity_id: str) -> dict[str, Any]:
    return {"type": "entityLink", "attrs": {"entityId": entity_id}}


INLINE = Inline(
    entity_link=lambda entity_id, label: (
        f"[[Note {entity_id}|{label}]]" if entity_id == "e1" else None
    ),
    time_ref=lambda attrs: "Year 3",
    nodes={"lexiconRef": lambda node: "*word*"},
    fallback_text=lambda node: str((node.get("attrs") or {}).get("alt", "")),
)


def item(*blocks: Any) -> dict[str, Any]:
    return {"type": "listItem", "content": list(blocks)}


def cell(value: str) -> dict[str, Any]:
    return {"type": "tableCell", "content": [p(text(value))]}


def md(*content: Any) -> str:
    return to_markdown(doc(*content), INLINE)


# --- rich text ----------------------------------------------------------------------------------


def test_blocks() -> None:
    assert md(
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Origins")]},
        p(text("One "), text("two", {"type": "bold"}), text(" three")),
        {"type": "horizontalRule"},
        {"type": "codeBlock", "attrs": {"language": "py"}, "content": [text("x = `1`\n```")]},
        {"type": "blockquote", "content": [p(text("said")), p(text("twice"))]},
    ) == (
        "## Origins\n\nOne **two** three\n\n---\n\n````py\nx = `1`\n```\n````\n\n> said\n>\n> twice"
    )


def test_lists_nest_and_number() -> None:
    nested = {"type": "bulletList", "content": [item(p(text("inner")))]}
    assert (
        md(
            {"type": "bulletList", "content": [item(p(text("a")), nested), item(p(text("b")))]},
            {"type": "orderedList", "attrs": {"start": 3}, "content": [item(p(text("c"))), item()]},
        )
        == "- a\n\n  - inner\n- b\n\n3. c\n4."
    )


def test_tables_and_callouts() -> None:
    table = {
        "type": "table",
        "content": [
            {"type": "tableRow", "content": [cell("Name"), cell("Age")]},
            {"type": "tableRow", "content": [cell("a|b")]},
        ],
    }
    spoiler = {"type": "visibilityBlock", "attrs": {"level": "spoiler", "label": "Ending"},
               "content": [p(text("dies"))]}  # fmt: skip
    private = {"type": "visibilityBlock", "attrs": {"level": "private", "label": None},
               "content": [p(text("secret"))]}  # fmt: skip
    callout = {"type": "callout", "attrs": {"tone": "warning"}, "content": [p(text("careful"))]}
    assert md(table, spoiler, private, callout) == (
        "| Name | Age |\n| --- | --- |\n| a\\|b |  |\n\n"
        "> [!spoiler]- Ending\n> dies\n\n> [!private] Private\n> secret\n\n> [!warning]\n> careful"
    )


def test_marks_links_and_escaping() -> None:
    assert md(
        p(
            text("See "),
            text("Ada", link_to("e1"), {"type": "italic"}),
            text(", "),
            text("Bob", link_to("e2")),
            text(" and "),
            text("the site", {"type": "link", "attrs": {"href": "https://x.test/a_(b)"}}),
            text(" "),
            text("a*b", {"type": "code"}),
            text(" on "),
            {"type": "timeRef", "attrs": {"timePoint": absolute(0)}},
            text(" #not-a-tag [x] $5 "),
            text("~~gone~~", {"type": "strike"}),
            {"type": "hardBreak"},
            text("- not a list"),
            {"type": "lexiconRef", "attrs": {"entryId": "x", "languageId": "y"}},
        ),
        p(text("1. not a list either")),
        {"type": "image", "attrs": {"mediaId": "m", "alt": "A map", "caption": "", "width": None}},
    ) == (
        "See *[[Note e1|Ada]]*, Bob and [the site](https://x.test/a_%28b%29) `a*b` on Year 3 "
        "\\#not-a-tag \\[x\\] \\$5 ~~\\~\\~gone\\~\\~~~\\\n\\- not a list*word*\n\n"
        "1\\. not a list either\n\nA map"
    )


def test_bold_runs_merge_and_keep_spaces_outside() -> None:
    bold = {"type": "bold"}
    assert md(p(text("x"), text(" big", bold), text(" bold ", bold), text("y"))) == (
        "x **big bold** y"
    )


def test_names_tags_and_frontmatter() -> None:
    assert file_name('  A/B: "C"?  ') == "A B C"
    assert file_name("...") == "Untitled"
    assert file_name("con") == "con_"
    assert len(file_name("x" * 500)) == 120
    assert tag_name("Old Gods") == "Old-Gods"
    assert tag_name("1999") == "_1999"
    assert tag_name("!!!") is None
    assert frontmatter(
        {
            "id": "x",
            "Two words": ["a", 'b "q"'],
            "n": 3,
            "ok": True,
            "none": [],
            "dates": {"x": {"A": "1"}},
        }
    ) == (
        '---\nid: "x"\n"Two words":\n  - "a"\n  - "b \\"q\\""\nn: 3\nok: true\nnone: []\n'
        'dates:\n  x:\n    A: "1"\n---\n'
    )


# --- a vault ------------------------------------------------------------------------------------


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


class World:
    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Aetheria")
        self.calendar = api.calendar(self.dimension["id"], "Reckoning")
        self.timeline = self.dimension["ext"]["prime_timeline_id"]
        dimension_id = self.dimension["id"]
        self.owner = api.make("misc", "Guild", dimension_id=dimension_id, visibility="public")
        self.hidden = api.make("misc", "Cabal", dimension_id=dimension_id, visibility="private")
        self.twin = api.make("gadget", "Engine", dimension_id=dimension_id)
        self.cosmic = api.make("misc", "Engine")  # multiversal, same name
        self.event = api.make(
            "event", "Forging", dimension_id=dimension_id, ext={"start": absolute(100 * DAY)}
        )
        self.gadget = api.make(
            "gadget",
            "Clock: Mark II",
            dimension_id=dimension_id,
            parent_id=None,
            summary="It ticks.",
            aliases=[{"alias": "The Clock"}, {"alias": "Old Tick", "visibility": "private"}],
            tags=["Old Gods", "brass"],
            body=self.body(),
            fields={
                "text": "Brass",
                "integer": "12",
                "boolean": True,
                "enum": "red",
                "multi_enum": ["red", "blue"],
                "duration": {"kind": "base", "units": "60"},
                "time_point": absolute(400 * DAY, "day"),
                "measurement": {"value": "1.5", "unit": "m"},
                "nicknames": ["Ticker", "Tocker"],
                "secret": "Hidden spring",
                "rich_text": doc(p(text("Very "), text("old", {"type": "bold"}))),
            },
        )
        api.made_link("world.owns", self.owner, self.gadget, role="maker")
        api.made_link("world.owns", self.hidden, self.twin)
        response = api.client.post(
            f"{api.base}/entities/{self.gadget['id']}/facts",
            json={
                "field_key": "rank",
                "value": "7",
                "timeline_id": self.timeline,
                "valid_from": absolute(2 * 365 * DAY, "year"),
                "source_event_id": self.event["id"],
            },
        )
        assert response.status_code == 201, response.json()

    def body(self) -> dict[str, Any]:
        built = p(
            text("Built by "),
            text("the guild", link_to(self.owner["id"])),
            text(" and "),
            text("the cabal", link_to(self.hidden["id"])),
            text(" on "),
            {"type": "timeRef", "attrs": {"timePoint": absolute(400 * DAY, "day")}},
        )
        private = {"level": "private", "label": None}
        spoiler = {"level": "spoiler", "label": None}
        return doc(
            built,
            {"type": "visibilityBlock", "attrs": private, "content": [p(text("Never wound"))]},
            {"type": "visibilityBlock", "attrs": spoiler, "content": [p(text("It stops"))]},
        )

    def export(self, **params: Any) -> dict[str, bytes]:
        response = self.api.client.get(f"{self.api.base}/export/markdown", params=params)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        return unzip(response.content)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with make_client(tmp_path) as client:
        yield World(LinkApi(client))


def test_the_layout(world: World) -> None:
    files = world.export()
    assert sorted(files) == [
        "Aetheria/Aetheria.md",
        "Aetheria/Calendars/Reckoning.md",
        "Aetheria/Events/Forging.md",
        "Aetheria/Gadgets/Clock Mark II.md",
        "Aetheria/Gadgets/Engine (Gadget).md",
        "Aetheria/Misc entries/Guild.md",
        "Aetheria/Timelines/Prime.md",
        "Multiverse/Misc entries/Engine (Misc entry).md",
        MANIFEST_NAME,
    ]
    manifest = json.loads(files[MANIFEST_NAME])
    assert (manifest["format"], manifest["audience"], manifest["notes"]) == (1, "readers", 8)


def test_a_note_for_readers(world: World) -> None:
    note = world.export()["Aetheria/Gadgets/Clock Mark II.md"].decode()
    assert note == (
        "---\n"
        f'lore_id: "{world.gadget["id"]}"\n'
        'kind: "Gadget"\n'
        'dimension: "[[Aetheria]]"\n'
        "aliases:\n"
        '  - "The Clock"\n'
        "tags:\n"
        '  - "brass"\n'
        '  - "Old-Gods"\n'
        'summary: "It ticks."\n'
        'text: "Brass"\n'
        "integer: 12\n"
        "boolean: true\n"
        'enum: "Red"\n'
        "multi_enum:\n"
        '  - "Red"\n'
        '  - "Blue"\n'
        'duration: "60 seconds"\n'
        'time_point: "36 2"\n'
        'measurement: "1.5 m"\n'
        "nicknames:\n"
        '  - "Ticker"\n'
        '  - "Tocker"\n'
        "dates:\n"
        "  time_point:\n"
        '    Reckoning: "36 2"\n'
        '    Absolute: "t = 34,560,000 s"\n'
        "---\n\n"
        "Built by [[Guild|the guild]] and the cabal on 36 2\n\n"
        "> [!spoiler]- Spoiler\n> It stops\n\n"
        "## Rich text\n\nVery **old**\n\n"
        "## Facts\n\n"
        "- **Rank**: 7 · from 3 · caused by [[Forging]]\n\n"
        "## Links\n\n"
        "- **owned by**: [[Guild]] (maker)\n"
    )


def test_the_author_sees_everything(world: World) -> None:
    files = world.export(audience="author")
    note = files["Aetheria/Gadgets/Clock Mark II.md"].decode()
    assert '  - "Old Tick"\n' in note
    assert 'secret: "Hidden spring"\n' in note
    assert "Built by [[Guild|the guild]] and [[Cabal|the cabal]] on" in note
    assert "> [!private] Private\n> Never wound" in note
    assert "Aetheria/Misc entries/Cabal.md" in files
    assert 'visibility: "private"' in files["Aetheria/Misc entries/Cabal.md"].decode()
    assert "- **owned by**: [[Cabal]]" in files["Aetheria/Gadgets/Engine (Gadget).md"].decode()


def test_events_show_their_times(world: World) -> None:
    note = world.export()["Aetheria/Events/Forging.md"].decode()
    assert 'start: "101 1 + 0 s"\nend: "101 1 + 0 s"\nimportance: 3\n' in note
    assert "dates:\n  start:\n    Reckoning:" in note


def test_a_chosen_calendar_comes_first(world: World) -> None:
    other = world.api.calendar(world.dimension["id"], "Almanac")
    note = world.export(calendar=other["id"])["Aetheria/Gadgets/Clock Mark II.md"].decode()
    assert '  time_point:\n    Almanac: "36 2"\n    Reckoning: "36 2"\n' in note


def test_readers_and_as_reader_get_404(world: World) -> None:
    response = world.api.client.get(
        f"{world.api.base}/export/markdown", params={"as_reader": "true"}
    )
    problem(response, 404, "not_found")


def test_a_folder_sink_needs_an_empty_folder(tmp_path: Path) -> None:
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(MarkdownExportError):
        FolderSink(tmp_path / "full")
    FolderSink(tmp_path / "new").write("a/b.md", b"x")
    assert (tmp_path / "new" / "a" / "b.md").read_bytes() == b"x"


def test_cli_export_markdown(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = Path(world.api.client.app.state.vaults.data_dir)  # type: ignore[attr-defined]
    monkeypatch.setenv("LORE_DATA_DIR", str(data_dir))
    out = tmp_path / "md"
    runner = CliRunner()
    command = ["vault", "export-markdown", world.api.vault, "--out", str(out)]
    result = runner.invoke(cli.app, command)
    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"exported: {out}")
    assert (out / "Aetheria" / "Aetheria.md").is_file()
    again = runner.invoke(cli.app, command)
    assert again.exit_code == 1
    assert "is not an empty folder" in again.output


# --- the canary vault ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def canary(tmp_path_factory: pytest.TempPathFactory) -> Canary:
    return build_canary_vault(tmp_path_factory.mktemp("canary"))


def _export(canary: Canary, audience: str) -> dict[str, bytes]:
    with leak_client(canary.data_dir) as client:
        response = client.get(
            f"/api/v1/vaults/{canary.vault}/export/markdown", params={"audience": audience}
        )
    assert response.status_code == 200, response.text
    return unzip(response.content)


def test_the_readers_export_holds_no_canary(canary: Canary) -> None:
    files = _export(canary, "readers")
    found = [
        (name, needle)
        for name, data in files.items()
        for needle in canary.needles
        if needle.encode() in data or needle in name
    ]
    assert found == []
    media = [name for name in files if name.startswith("_media/")]
    assert media  # the visible items' files
    assert any(b"![[_media/" in data for data in files.values())


def test_the_authors_export_holds_the_canaries(canary: Canary) -> None:
    files = _export(canary, "author")
    blob = b"\n".join([*files.values(), *(name.encode() for name in files)])
    missing = [needle for needle in canary.strings if needle.encode() not in blob]
    # Module rows the export doesn't write yet (lexicon entries, map pins, worldline segments,
    # correspondences, timeline notes) carry canaries too: most must still be found.
    assert len(missing) < len(canary.strings) / 2, missing
