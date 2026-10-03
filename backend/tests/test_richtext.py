from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lore.core.errors import InvalidInputError
from lore.core.modules import ModuleRegistry, ModuleSpec, RegistryError
from lore.core.richtext import SCHEMA_VERSION
from lore.core.richtext.extract import extract, filter_for_reader
from lore.core.richtext.schema import handler_map, validate_document
from lore.core.richtext.upgrade import upgrade
from tests.conftest import local_client
from tests.entity_api import HEADERS, LinkApi, new_app, problem
from tests.sample_modules import STAMP

ANA = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
BO = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5c"
HANDLERS = handler_map([STAMP])
POINT = {"anchor": {"kind": "absolute", "t": "42"}, "precision": "base", "approximate": False}


def doc(*content: Any) -> dict[str, Any]:
    return {"type": "doc", "content": list(content)}


def p(*content: Any) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


def text(value: str, *marks: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def mention(entity_id: str) -> dict[str, Any]:
    return {"type": "entityLink", "attrs": {"entityId": entity_id}}


def block(level: str, *content: Any, label: str | None = None) -> dict[str, Any]:
    return {
        "type": "visibilityBlock",
        "attrs": {"level": level, "label": label},
        "content": list(content),
    }


def error_path(document: Any) -> str:
    with pytest.raises(InvalidInputError) as caught:
        validate_document(document, HANDLERS)
    assert caught.value.errors
    return caught.value.errors[0]["path"]


# --- schema ---------------------------------------------------------------------------------

EVERYTHING = doc(
    {"type": "heading", "attrs": {"level": 2}, "content": [text("Title")]},
    p(
        text("bold", {"type": "bold"}),
        text(" and "),
        text("Ana", mention(ANA)),
        {"type": "hardBreak"},
        {"type": "timeRef", "attrs": {"timePoint": POINT}},
        {"type": "timeRef", "attrs": {"ref": {"type": "event", "id": BO, "slot": "start"}}},
        {"type": "sampleStamp", "attrs": {"seal": "royal"}},
        text("site", {"type": "link", "attrs": {"href": "https://example.com"}}),
    ),
    {"type": "bulletList", "content": [{"type": "listItem", "content": [p(text("item"))]}]},
    {
        "type": "orderedList",
        "attrs": {"start": 3},
        "content": [{"type": "listItem", "content": [p(text("third"))]}],
    },
    {"type": "blockquote", "content": [p(text("quoted", {"type": "italic"}))]},
    {"type": "codeBlock", "attrs": {"language": "python"}, "content": [text("x = 1")]},
    {"type": "horizontalRule"},
    {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableHeader",
                        "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [100]},
                        "content": [p(text("h"))],
                    },
                    {
                        "type": "tableCell",
                        "attrs": {"colspan": 2, "rowspan": 1, "colwidth": None},
                        "content": [p(text("c", {"type": "strike"}, {"type": "code"}))],
                    },
                ],
            }
        ],
    },
    block("spoiler", p(text("twist")), block("private", p(text("secret"))), label="Book 2"),
    {"type": "callout", "attrs": {"tone": "warning"}, "content": [p(text("careful"))]},
)


def test_a_full_document_round_trips() -> None:
    assert validate_document(EVERYTHING, HANDLERS) == EVERYTHING


def test_defaults_are_filled_in() -> None:
    raw = doc(
        {"type": "orderedList", "content": [{"type": "listItem", "content": [p(text("a"))]}]},
        {"type": "codeBlock", "content": [text("x")]},
        {"type": "callout", "content": []},
        {"type": "visibilityBlock", "attrs": {"level": "spoiler"}},
        {"type": "paragraph"},
    )
    clean = validate_document(raw)
    assert clean["content"][0]["attrs"] == {"start": 1}
    assert clean["content"][1]["attrs"] == {"language": None}
    assert clean["content"][2]["attrs"] == {"tone": "note"}
    assert clean["content"][3] == {
        "type": "visibilityBlock",
        "attrs": {"level": "spoiler", "label": None},
        "content": [],
    }
    assert clean["content"][4] == {"type": "paragraph", "content": []}


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,x",
        "vbscript:x",
        "/relative",
        "http://",
        "https://exa mple.com",
        "ftp://example.com",
        5,
        None,
        "https://" + "a" * 2050,
    ],
)
def test_unsafe_links_are_stripped_keeping_the_text(href: Any) -> None:
    link = {"type": "link", "attrs": {"href": href}}
    clean = validate_document(doc(p(text("click", link, {"type": "bold"}))))
    assert clean == doc(p(text("click", {"type": "bold"})))


@pytest.mark.parametrize(
    "href", ["https://example.com/a?b=c#d", "HTTP://EXAMPLE.COM", "mailto:ana@example.com"]
)
def test_safe_links_are_kept(href: str) -> None:
    link = {"type": "link", "attrs": {"href": href}}
    assert validate_document(doc(p(text("x", link)))) == doc(p(text("x", link)))


def test_editor_link_defaults_are_ignored_other_unknown_attributes_rejected() -> None:
    attrs = {"href": "https://a.example", "target": "_blank", "rel": "noopener", "class": None}
    clean = validate_document(doc(p(text("x", {"type": "link", "attrs": attrs}))))
    assert clean == doc(p(text("x", {"type": "link", "attrs": {"href": "https://a.example"}})))
    # decided 2026-10-04: anything else unknown fails the save
    assert error_path(doc({"type": "paragraph", "attrs": {"textAlign": "center"}})) == (
        "body.content.0.attrs.textAlign"
    )
    assert error_path(doc({"type": "heading", "attrs": {"level": 1, "id": "x"}})) == (
        "body.content.0.attrs.id"
    )
    assert error_path(doc(p(text("x", {"type": "bold", "attrs": {"weight": 7}})))) == (
        "body.content.0.content.0.marks.0.attrs.weight"
    )
    assert error_path(
        doc(p(text("x", {"type": "link", "attrs": {"href": "https://a.b", "title": "t"}})))
    ) == ("body.content.0.content.0.marks.0.attrs.title")


@pytest.mark.parametrize(
    ("document", "path"),
    [
        ("text", "body"),
        ({"type": "paragraph"}, "body"),
        (doc({"type": "iframe"}), "body.content.0.type"),
        (doc(p(text("x", {"type": "underline"}))), "body.content.0.content.0.marks.0.type"),
        (
            doc(p({"type": "text", "text": "x", "marks": ["bold"]})),
            "body.content.0.content.0.marks.0.type",
        ),
        (
            doc({"type": "heading", "attrs": {"level": 5}, "content": []}),
            "body.content.0.attrs.level",
        ),
        (doc({"type": "heading", "content": []}), "body.content.0.attrs.level"),
        (doc(p({"type": "text", "text": ""})), "body.content.0.content.0.text"),
        (doc(text("loose")), "body.content.0.type"),
        (doc({"type": "listItem", "content": []}), "body.content.0.type"),
        (doc(p(p(text("x")))), "body.content.0.content.0.type"),
        (doc({"type": "table", "content": [p(text("x"))]}), "body.content.0.content.0.type"),
        (doc({"type": "horizontalRule", "content": [p(text("x"))]}), "body.content.0.content"),
        (doc({"type": "paragraph", "marks": [{"type": "bold"}]}), "body.content.0.marks"),
        (doc({"type": "paragraph", "content": "x"}), "body.content.0.content"),
        (doc({"type": "paragraph", "attrs": "x"}), "body.content.0.attrs"),
        (
            doc({"type": "codeBlock", "content": [text("x", {"type": "bold"})]}),
            "body.content.0.content.0.marks",
        ),
        (doc({"type": "codeBlock", "attrs": {"language": "c c"}}), "body.content.0.attrs.language"),
        (doc({"type": "orderedList", "attrs": {"start": -1}}), "body.content.0.attrs.start"),
        (
            doc(
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [{"type": "tableCell", "attrs": {"colspan": 0}}],
                        }
                    ],
                }
            ),
            "body.content.0.content.0.content.0.attrs.colspan",
        ),
        (
            doc(
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [{"type": "tableCell", "attrs": {"colwidth": "wide"}}],
                        }
                    ],
                }
            ),
            "body.content.0.content.0.content.0.attrs.colwidth",
        ),
        (doc(block("secret")), "body.content.0.attrs.level"),
        (doc(block("private", label="x" * 201)), "body.content.0.attrs.label"),
        (doc({"type": "callout", "attrs": {"tone": "shout"}}), "body.content.0.attrs.tone"),
        (
            doc(p(text("x", {"type": "entityLink", "attrs": {"entityId": "nope"}}))),
            "body.content.0.content.0.marks.0.attrs.entityId",
        ),
        (
            doc(p(text("x", {"type": "link", "attrs": "x"}))),
            "body.content.0.content.0.marks.0.attrs",
        ),
        (doc(p({"type": "timeRef", "attrs": {}})), "body.content.0.content.0.attrs"),
        (
            doc(p({"type": "timeRef", "attrs": {"timePoint": POINT, "ref": {}}})),
            "body.content.0.content.0.attrs",
        ),
        (
            doc(p({"type": "timeRef", "attrs": {"timePoint": {"precision": "base"}}})),
            "body.content.0.content.0.attrs.timePoint.anchor",
        ),
        (doc(p({"type": "sampleStamp", "attrs": {}})), "body.content.0.content.0.attrs"),
        (doc({"type": "sampleStamp", "attrs": {"seal": "x"}}), "body.content.0.type"),
        (doc(p({"type": "text", "text": "x", "marks": "bold"})), "body.content.0.content.0.marks"),
    ],
)
def test_invalid_documents(document: Any, path: str) -> None:
    assert error_path(document) == path


def test_nesting_is_limited() -> None:
    deep: dict[str, Any] = p(text("x"))
    for _ in range(70):
        deep = {"type": "blockquote", "content": [deep]}
    assert error_path(doc(deep)).count("content") == 65


def test_upgrade() -> None:
    assert upgrade(EVERYTHING, SCHEMA_VERSION) is EVERYTHING
    with pytest.raises(ValueError, match="newer"):
        upgrade(EVERYTHING, SCHEMA_VERSION + 1)


def test_module_node_types_must_be_unique() -> None:
    def spec(module_id: str, handler: Any) -> ModuleSpec:
        return ModuleSpec(id=module_id, name=module_id, description="", richtext_nodes=(handler,))

    from dataclasses import replace  # noqa: PLC0415

    with pytest.raises(RegistryError) as caught:
        ModuleRegistry(
            [spec("a", replace(STAMP, type="paragraph")), spec("b", STAMP), spec("c", STAMP)]
        )
    assert caught.value.problems == [
        "a: rich-text node 'paragraph' is already defined by core",
        "c: rich-text node 'sampleStamp' is already defined by b",
    ]


# --- extraction and reader filtering --------------------------------------------------------


def test_extract_text_mentions_and_refs() -> None:
    result = extract(validate_document(EVERYTHING, HANDLERS), HANDLERS)
    assert result.public_text.splitlines() == [
        "Title",
        "bold and Ana",
        "royalsite",
        "item",
        "third",
        "quoted",
        "x = 1",
        "h",
        "c",
        "twist",
        "careful",
    ]
    assert result.restricted_text == "secret"
    assert result.mentions[ANA].public == 1
    assert result.refs["stamp"] == ["royal"]
    assert result.refs["time"] == [
        {"timePoint": POINT},
        {"ref": {"type": "event", "id": BO, "slot": "start"}},
    ]
    assert extract(None).public_text == ""


def test_mentions_count_by_the_strictest_enclosing_visibility() -> None:
    document = doc(
        p(text("a", mention(ANA))),
        block("spoiler", p(text("b", mention(ANA))), block("private", p(text("c", mention(ANA))))),
        block("private", block("spoiler", p(text("d", mention(BO))))),
    )
    counts = extract(document).mentions
    assert (counts[ANA].public, counts[ANA].spoiler, counts[ANA].private) == (1, 1, 1)
    assert (counts[BO].public, counts[BO].spoiler, counts[BO].private) == (0, 0, 1)
    # a private field: everything in it is private
    in_field = extract(document, visibility="private").mentions
    assert (in_field[ANA].public, in_field[ANA].private) == (0, 3)
    spoiler_field = extract(document, visibility="spoiler").mentions
    assert (spoiler_field[ANA].spoiler, spoiler_field[ANA].private) == (2, 1)


def test_filter_for_reader() -> None:
    document = validate_document(
        doc(
            p(text("Ana", mention(ANA)), text(" met "), text("Bo", mention(BO), {"type": "bold"})),
            block("spoiler", p(text("twist")), block("private", p(text("hidden")))),
            block("private", p(text("gone"))),
            p(
                {"type": "timeRef", "attrs": {"ref": {"type": "event", "id": BO, "slot": "start"}}},
                {
                    "type": "timeRef",
                    "attrs": {"ref": {"type": "event", "id": ANA, "slot": "start"}},
                },
                {"type": "sampleStamp", "attrs": {"seal": "secret"}},
                {"type": "sampleStamp", "attrs": {"seal": "open"}},
            ),
        ),
        HANDLERS,
    )
    filtered = filter_for_reader(document, frozenset({ANA}), HANDLERS)
    assert filtered == doc(
        p(text("Ana", mention(ANA)), text(" met "), text("Bo", {"type": "bold"})),
        block("spoiler", p(text("twist"))),
        p(
            {"type": "timeRef", "attrs": {"hidden_ref": True}},
            {"type": "timeRef", "attrs": {"ref": {"type": "event", "id": ANA, "slot": "start"}}},
            {"type": "sampleStamp", "attrs": {"seal": "open"}},
        ),
    )
    plain = filter_for_reader(doc(p(text("Bo", mention(BO)))), frozenset())
    assert plain == doc(p(text("Bo")))
    assert filter_for_reader(None, frozenset()) is None
    assert "CANARY" not in str(
        filter_for_reader(doc(block("private", p(text("CANARY")))), frozenset())
    )


# --- API: bodies, mentions, backlinks -------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with local_client(new_app(tmp_path), headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> LinkApi:
    return LinkApi(client)


def backlinks(api: LinkApi, entity: dict[str, Any], **params: Any) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/entities/{entity['id']}/backlinks", params=params)
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def counts(item: dict[str, Any]) -> tuple[int, int, int]:
    m = item["mentions"]
    return m["public"], m["spoiler"], m["private"]


def test_bodies_are_validated_and_normalized(api: LinkApi) -> None:
    unsafe = {"type": "link", "attrs": {"href": "javascript:alert(1)"}}
    entity = api.make("misc", body=doc(p(text("click", unsafe))))
    assert entity["body"] == doc(p(text("click")))
    response = api.create("misc", body=doc({"type": "script"}))
    assert problem(response, 422, "validation_error")["errors"][0]["path"] == "body.content.0.type"
    bad_field = api.create("gadget", fields={"rich_text": doc({"type": "iframe"})})
    assert problem(bad_field, 422, "validation_error")["errors"][0]["path"] == (
        "fields.rich_text.content.0.type"
    )
    module_node = doc(p({"type": "sampleStamp", "attrs": {"seal": "x"}}))
    problem(api.create("misc", body=module_node), 422, "validation_error")  # module not here


def test_mentions_follow_body_edits(api: LinkApi) -> None:
    ana, bo = api.make("misc", "Ana"), api.make("misc", "Bo")
    writer = api.make(
        "misc",
        "Writer",
        body=doc(
            p(
                text("Ana", mention(ana["id"])),
                text(" and "),
                text("Ana again", mention(ana["id"])),
            ),
            block("spoiler", p(text("Bo", mention(bo["id"])))),
            block("private", p(text("Bo", mention(bo["id"])))),
        ),
    )
    [ana_back] = backlinks(api, ana)
    assert (ana_back["entity"]["name"], counts(ana_back), ana_back["links"]) == (
        "Writer",
        (2, 0, 0),
        [],
    )
    assert counts(backlinks(api, bo)[0]) == (0, 1, 1)
    writer = api.patch(writer, body=doc(p(text("only Bo", mention(bo["id"]))))).json()["entity"]
    assert backlinks(api, ana) == []
    assert counts(backlinks(api, bo)[0]) == (1, 0, 0)
    api.patch(writer, body=None)
    assert backlinks(api, bo) == []


def test_mentions_ignore_self_and_missing_entities(api: LinkApi) -> None:
    writer = api.make("misc", "Writer")
    ghost = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    writer = api.patch(
        writer, body=doc(p(text("me", mention(writer["id"])), text("ghost", mention(ghost))))
    ).json()["entity"]
    assert backlinks(api, writer) == []
    assert writer["body"]["content"][0]["content"][1]["marks"] == [mention(ghost)]  # kept


def test_rich_text_fields_count_with_their_visibility(api: LinkApi) -> None:
    ana = api.make("misc", "Ana")
    body = doc(p(text("Ana", mention(ana["id"]))))
    gadget = api.make("gadget", "Gizmo", fields={"rich_text": body}, body=body)
    assert counts(backlinks(api, ana)[0]) == (2, 0, 0)
    gadget = api.patch(gadget, field_visibility={"rich_text": "private"}).json()["entity"]
    assert counts(backlinks(api, ana)[0]) == (1, 0, 1)
    api.patch(gadget, fields={"rich_text": None})
    assert counts(backlinks(api, ana)[0]) == (1, 0, 0)


def test_backlinks_combine_links_and_mentions_by_name(api: LinkApi) -> None:
    target = api.make("misc", "Target")
    zed = api.make("misc", "Zed", body=doc(p(text("t", mention(target["id"])))))
    api.made_link("core.related", zed, target)
    alpha = api.make("misc", "Alpha 10")
    api.made_link("world.ally", target, alpha)  # symmetric: counts as incoming too
    api.make("misc", "Alpha 9", body=doc(p(text("t", mention(target["id"])))))
    items = backlinks(api, target)
    assert [i["entity"]["name"] for i in items] == ["Alpha 9", "Alpha 10", "Zed"]
    assert [len(i["links"]) for i in items] == [0, 1, 1]
    assert [counts(i) for i in items] == [(1, 0, 0), (0, 0, 0), (1, 0, 0)]
    assert items[1]["links"][0]["direction"] == "both"
    # trashed sources are hidden unless asked for
    api.delete(zed["id"])
    assert [i["entity"]["name"] for i in backlinks(api, target)] == ["Alpha 9", "Alpha 10"]
    shown = backlinks(api, target, include_trashed="true")
    assert [i["entity"]["name"] for i in shown] == ["Alpha 9", "Alpha 10", "Zed"]
    missing = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    problem(api.client.get(f"{api.base}/entities/{missing}/backlinks"), 404, "not_found")


def test_sources_of_disabled_modules_are_hidden(api: LinkApi) -> None:
    target = api.make("misc", "Target")
    api.make("beast", "Wolf", body=doc(p(text("t", mention(target["id"])))))
    assert len(backlinks(api, target)) == 1
    api.modules("extra", enabled=False)
    assert backlinks(api, target) == []


def test_undo_restores_mentions(api: LinkApi) -> None:
    ana = api.make("misc", "Ana")
    writer = api.make("misc", "Writer", body=doc(p(text("Ana", mention(ana["id"])))))
    api.patch(writer, body=doc(p(text("nobody"))))
    assert backlinks(api, ana) == []
    latest = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    assert api.client.post(f"{api.base}/changes/{latest['id']}/revert").status_code == 200
    assert [i["entity"]["name"] for i in backlinks(api, ana)] == ["Writer"]


def test_openapi_operation(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    path = "/api/v1/vaults/{vault_id}/entities/{entity_id}/backlinks"
    assert paths[path]["get"]["operationId"] == "entities_backlinks"
