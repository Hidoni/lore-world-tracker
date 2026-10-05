"""Search (``data-model.md`` §9, ``api.md`` §2): indexing in the write transaction, expressions,
ranking, snippets, the quick switcher, reader restrictions, module documents and reindexing."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lore import cli
from lore.app import create_app
from lore.config import Settings
from lore.core.modules import ModuleRegistry, ModuleSpec, RegistryError, VaultContext
from lore.core.registry import KindDef
from lore.core.search import SearchContributor, SearchDocument, highlight
from lore.core.search.expression import ExpressionError, parse
from lore.core.search.highlight import Term
from lore.core.search.indexer import INDEX_META_KEY, SearchIndexer
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, invalid, problem
from tests.entity_modules import ENTITY_MODULES

# --- a module contributing documents ---------------------------------------------------------

LEXICON: dict[str, SearchDocument] = {}


def _lexicon(_context: VaultContext, ids: Sequence[str] | None) -> list[SearchDocument]:
    return [doc for key, doc in LEXICON.items() if ids is None or key in ids]


LEXI = ModuleSpec(
    id="lexi",
    name="Lexi",
    description="Contributes lexicon-like search documents.",
    kinds=(
        KindDef(
            "tongue",
            "Tongue",
            "Tongues",
            icon="languages",
            color="#123456",
            allowed_parents=("misc",),
        ),
    ),
    search_contributors=(SearchContributor("lexi.entry", _lexicon, "Entry", "book"),),
)
MODULES = (*ENTITY_MODULES, LEXI)


def doc(*paragraphs: Any) -> dict[str, Any]:
    return {"type": "doc", "content": list(paragraphs)}


def p(value: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [{"type": "text", "text": value}]}


def private(*content: Any) -> dict[str, Any]:
    return {
        "type": "visibilityBlock",
        "attrs": {"level": "private", "label": None},
        "content": list(content),
    }


def new_app(path: Path, **settings: Any) -> FastAPI:
    LEXICON.clear()
    return create_app(Settings(data_dir=path, **settings), modules=MODULES)


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return new_app(tmp_path)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with local_client(app, headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)


def search(api: Api, q: str, **params: Any) -> dict[str, Any]:
    response = api.client.get(f"{api.base}/search", params={"q": q, **params})
    assert response.status_code == 200, response.json()
    page: dict[str, Any] = response.json()
    return page


def found(api: Api, q: str, **params: Any) -> list[str]:
    return [hit["name"] for hit in search(api, q, **params)["items"]]


def quick(api: Api, q: str, **params: Any) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/search/quick", params={"q": q, **params})
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def in_vault(app: FastAPI, vault_id: str) -> Iterator[VaultContext]:
    opened = app.state.vaults.open(vault_id)
    with opened.write_sessions.begin() as session:
        yield VaultContext(opened, session, app.state.registry)


def index_rows(app: FastAPI, vault_id: str) -> list[tuple[Any, ...]]:
    """The index content without rowids, plus FTS5's own consistency verdicts."""
    opened = app.state.vaults.open(vault_id)
    with opened.engine.connect() as connection:
        for table in ("search_fts", "search_trigram"):
            # Raises if the FTS index doesn't match search_docs.
            connection.exec_driver_sql(
                f"INSERT INTO {table}({table}, rank) VALUES ('integrity-check', 1)"
            )
        rows = connection.exec_driver_sql(
            "SELECT * FROM search_docs ORDER BY doc_type, doc_id"
        ).all()
    return [tuple(row)[1:] for row in rows]


# --- expressions ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "fts"),
    [
        ("dragon", '"dragon"*'),
        ("red dragon", '("red"* AND "dragon"*)'),
        ('"red dragon"', '"red dragon"'),
        ('"red dra"*', '"red dra"*'),
        ("dragon*", '"dragon"*'),
        ("dragon OR wyrm", '("dragon"* OR "wyrm"*)'),
        ("dragon -red", '"dragon"* NOT "red"*'),
        ("dragon NOT red", '"dragon"* NOT "red"*'),
        ('dragon -"red wing"', '"dragon"* NOT "red wing"'),
        ("dragon AND red", '("dragon"* AND "red"*)'),
        ("(dragon OR wyrm) -red", '(("dragon"* OR "wyrm"*)) NOT "red"*'),
        ("dragon -(red OR blue)", '"dragon"* NOT (("red"* OR "blue"*))'),
        ("dragon or wyrm", '("dragon"* AND "or"* AND "wyrm"*)'),
        ('say:"hi"', '("say:"* AND "hi")'),
        ("don't", '"don\'t"*'),
        ("dragon !!!", '"dragon"*'),
        ('"quo""te"', '("quo" AND "te")'),
    ],
)
def test_expressions(typed: str, fts: str) -> None:
    assert parse(typed).fts == fts


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "-dragon",
        "NOT dragon",
        "dragon OR",
        "OR dragon",
        "(dragon",
        "dragon)",
        '"dragon',
        "!!!",
        "dragon -",
        "(-dragon)",
        " ".join(["w"] * 33),
        "(" * 10 + "x" + ")" * 10,
    ],
)
def test_invalid_expressions(typed: str) -> None:
    with pytest.raises(ExpressionError):
        parse(typed)


def test_expression_terms() -> None:
    assert parse('red "Big wing"* -blue (fire OR ice)').terms == (
        Term(("red",), prefix=True),
        Term(("big", "wing"), prefix=True),
        Term(("fire",), prefix=True),
        Term(("ice",), prefix=True),
    )
    assert parse('"Élan vital"').terms == (Term(("elan", "vital"), prefix=False),)


# --- indexing and matching --------------------------------------------------------------------


def test_indexing_follows_create_update_trash_restore_purge(api: Api) -> None:
    gadget = api.make("gadget", "Brass Astrolabe", summary="Shows the stars")
    assert found(api, "astro") == ["Brass Astrolabe"]
    assert found(api, "stars") == ["Brass Astrolabe"]

    renamed = api.patch(gadget, name="Copper Orrery", aliases=[{"alias": "Planet clock"}])
    assert renamed.status_code == 200
    assert found(api, "astro") == []
    assert found(api, "orrery") == ["Copper Orrery"]
    assert found(api, "planet") == ["Copper Orrery"]

    assert api.delete(gadget["id"]).status_code == 200
    assert found(api, "orrery") == []
    assert api.restore(gadget["id"]).status_code == 200
    assert found(api, "orrery") == ["Copper Orrery"]
    api.delete(gadget["id"])
    assert api.delete(gadget["id"], purge=True).status_code == 200
    assert index_rows(api.client.app, api.vault) == []  # type: ignore[arg-type]


def test_body_and_field_text(api: Api) -> None:
    api.make(
        "gadget",
        "Kettle",
        body=doc(p("Whistles when the tea is ready")),
        fields={
            "text": "copper spout",
            "long_text": "line one\nline two",
            "rich_text": doc(p("enamel handle")),
            "integer": "1234567890123456789",
            "decimal": "1.50",
            "boolean": True,
            "enum": "red",
            "multi_enum": ["blue"],
            "url": "https://example.com/kettle",
            "color": "#ff0000",
            "measurement": {"value": "2", "unit": "litres"},
            "nicknames": ["Old Faithful", "Steamer"],
        },
    )
    for q in (
        "whistles",
        "copper",
        "two",
        "enamel",
        "1234567890123456789",
        "1.5",
        "Red",
        "Blue",
        "example",
        "litres",
        "faithful",
        "steamer",
    ):
        assert found(api, q) == ["Kettle"], q
    assert found(api, "true") == found(api, "ff0000") == []


def test_unsearchable_fields_and_disabled_contributions(api: Api) -> None:
    gadget = api.make("gadget", "Glider", fields={"extra.stars": 4, "text": "balsa"})
    assert found(api, "balsa") == ["Glider"]
    api.make("beast", "Griffin")
    assert found(api, "griffin") == ["Griffin"]
    assert api.modules("extra", enabled=False).status_code == 200
    assert found(api, "griffin") == []  # the kind's module is disabled
    assert found(api, "glider") == ["Glider"]
    assert api.modules("extra", enabled=True).status_code == 200
    assert found(api, "griffin") == ["Griffin"]
    assert api.get(gadget["id"]).status_code == 200


def test_diacritics_and_case(api: Api) -> None:
    api.make("misc", "Éowyn of Rohan", aliases=[{"alias": "Dernhelm"}])
    api.make("misc", "Zoë")
    assert found(api, "eowyn") == found(api, "ÉOWYN") == ["Éowyn of Rohan"]
    assert found(api, "zoe") == ["Zoë"]
    assert [hit["name"] for hit in quick(api, "OWYN")] == ["Éowyn of Rohan"]


def test_expressions_against_the_index(api: Api) -> None:
    api.make("misc", "Red Dragon")
    api.make("misc", "Blue Dragon")
    api.make("misc", "Red Wyrm", summary="A dragon kin")
    api.make("misc", "Dragonfly")
    assert sorted(found(api, "dragon")) == ["Blue Dragon", "Dragonfly", "Red Dragon", "Red Wyrm"]
    assert found(api, '"red dragon"') == ["Red Dragon"]
    assert sorted(found(api, "dragon -red")) == ["Blue Dragon", "Dragonfly"]
    assert sorted(found(api, "dragon NOT (red OR blue)")) == ["Dragonfly"]
    assert sorted(found(api, "wyrm OR dragonf")) == ["Dragonfly", "Red Wyrm"]
    assert found(api, "fly") == []  # words match word beginnings, not inside words
    assert sorted(found(api, '"dragon"')) == ["Blue Dragon", "Red Dragon", "Red Wyrm"]
    assert sorted(found(api, "(blue OR wyrm) dragon")) == ["Blue Dragon", "Red Wyrm"]
    paths = invalid(api.client.get(f"{api.base}/search", params={"q": "-dragon"}))
    assert paths == ["q"]
    invalid(api.client.get(f"{api.base}/search", params={"q": "(dragon"}))
    invalid(api.client.get(f"{api.base}/search", params={"q": ""}))


def test_ranking(api: Api) -> None:
    api.make("gadget", "Field", fields={"text": "zephyr"})
    api.make("gadget", "Body", body=doc(p("zephyr")))
    api.make("gadget", "Summary", summary="zephyr")
    api.make("gadget", "Alias", aliases=[{"alias": "Zephyr"}])
    api.make("gadget", "Zephyr")
    assert found(api, "zephyr") == ["Zephyr", "Alias", "Summary", "Body", "Field"]


def test_snippets(api: Api) -> None:
    long_text = " ".join(["filler"] * 40 + ["the", "ancient", "lighthouse", "beam"] + ["more"] * 40)
    api.make("misc", "Cape", body=doc(p(long_text)), summary="A windy cape")
    hit = search(api, "lighthouse")["items"][0]
    assert hit["snippet"]["source"] == "body"
    parts = hit["snippet"]["parts"]
    assert {"text": "lighthouse", "match": True} in parts
    assert "".join(part["text"] for part in parts).startswith("…")
    assert search(api, "windy")["items"][0]["snippet"] == {
        "source": "summary",
        "parts": [
            {"text": "A ", "match": False},
            {"text": "windy", "match": True},
            {"text": " cape", "match": False},
        ],
    }
    assert search(api, "cape")["items"][0]["snippet"]["source"] == "summary"
    api.make("misc", "Plain")
    assert search(api, "plain")["items"][0]["snippet"] is None  # the name matched


def test_hit_members_filters_and_pagination(api: Api) -> None:
    world, other = api.make("dimension", "World"), api.make("dimension", "Other")
    icon = api.make("misc", "Torch 1", dimension_id=world["id"], icon="flame", color="#ABCDEF")
    api.make("gadget", "Torch 2", dimension_id=other["id"])
    api.make("misc", "Torch 3")  # multiversal
    hit = search(api, "torch", kind="misc", dimension=world["id"])["items"][0]
    assert hit == {
        "doc_type": "entity",
        "doc_id": icon["id"],
        "entity_id": icon["id"],
        "kind": "misc",
        "name": "Torch 1",
        "icon": "flame",
        "color": "#abcdef",
        "dimension_id": world["id"],
        "visibility": "public",
        "snippet": None,
    }
    assert sorted(found(api, "torch", dimension=world["id"])) == ["Torch 1", "Torch 3"]
    assert found(api, "torch", dimension=world["id"], include_multiversal="false") == ["Torch 1"]
    assert found(api, "torch", kind="gadget") == ["Torch 2"]
    assert found(api, "world", kind="dimension", dimension=other["id"]) == []
    gadget = search(api, "torch", kind="gadget")["items"][0]
    assert (gadget["icon"], gadget["color"]) == ("box", "#000000")  # the kind's

    first = search(api, "torch", limit=2)
    assert len(first["items"]) == 2
    rest = search(api, "torch", limit=2, cursor=first["next_cursor"])
    assert rest["next_cursor"] is None
    assert sorted(h["name"] for h in first["items"] + rest["items"]) == [
        "Torch 1",
        "Torch 2",
        "Torch 3",
    ]
    invalid(api.client.get(f"{api.base}/search", params={"q": "x", "cursor": "nope"}))
    invalid(api.client.get(f"{api.base}/search", params={"q": "x", "cursor": "eyJvZmZzZXQiOi0xfQ"}))
    problem(
        api.client.get(f"{api.base}/search", params={"q": "x", "kind": "nope"}),
        422,
        "validation_error",
    )


# --- quick switcher ---------------------------------------------------------------------------


def test_quick_switcher(api: Api) -> None:
    aragorn = api.make(
        "misc",
        "Aragorn",
        aliases=[{"alias": "Strider"}, {"alias": "Elessar", "visibility": "private"}],
    )
    api.make("misc", "Arathorn")
    api.make("misc", "Paragon")
    names = [hit["name"] for hit in quick(api, "ara")]
    assert sorted(names[:2]) == ["Aragorn", "Arathorn"]  # prefixes first, then substrings
    assert names[2:] == ["Paragon"]
    hit = quick(api, "strid")[0]
    assert (hit["name"], hit["alias"], hit["entity_id"]) == ("Aragorn", "Strider", aragorn["id"])
    assert quick(api, "eless")[0]["alias"] == "Elessar"  # authors search private aliases
    assert quick(api, "ara")[0]["alias"] is None
    assert quick(api, "  ") == quick(api, "!!") == []
    assert quick(api, 'ara" (*') != []  # typed text is never an expression
    assert [h["name"] for h in quick(api, "agon")] == ["Paragon"]  # substring, 3+ characters
    assert quick(api, "go") == []
    for index in range(25):
        api.make("misc", f"Bulk {index}")
    assert len(quick(api, "bulk")) == 20


# --- module documents -------------------------------------------------------------------------


def test_contributed_documents(app: FastAPI, api: Api) -> None:
    tongue = api.make("tongue", "Elvish")
    LEXICON["e1"] = SearchDocument(
        doc_id="e1",
        entity_id=tongue["id"],
        dimension_id=None,
        visibility="public",
        name="mellon",
        extra_public="friend",
        extra_restricted="password",
    )
    LEXICON["e2"] = SearchDocument(
        doc_id="e2", entity_id=tongue["id"], dimension_id=None, visibility="private", name="gwaith"
    )
    for context in in_vault(app, api.vault):
        SearchIndexer(context).index_documents("lexi.entry", ["e1", "e2", "gone"])
    hit = search(api, "friend")["items"][0]
    assert {k: hit[k] for k in ("doc_type", "doc_id", "entity_id", "kind", "icon", "color")} == {
        "doc_type": "lexi.entry",
        "doc_id": "e1",
        "entity_id": tongue["id"],
        "kind": "lexi.entry",
        "icon": "book",
        "color": None,
    }
    assert hit["snippet"]["source"] == "extra"
    assert found(api, "password") == ["mellon"]
    assert found(api, "mellon", kind="lexi.entry") == ["mellon"]
    assert found(api, "mellon", kind="tongue") == []
    assert [h["name"] for h in quick(api, "gwa")] == ["gwaith"]

    api.delete(tongue["id"])  # documents of a trashed entity are hidden
    assert found(api, "mellon") == []
    api.restore(tongue["id"])
    assert api.modules("lexi", enabled=False).status_code == 200
    assert found(api, "mellon") == []
    assert api.modules("lexi", enabled=True).status_code == 200
    assert found(api, "mellon") == ["mellon"]

    del LEXICON["e1"]
    for context in in_vault(app, api.vault):
        indexer = SearchIndexer(context)
        indexer.index_documents("lexi.entry", ["e1"])
        indexer.remove_documents("lexi.entry", ["e2"])
        with pytest.raises(ValueError, match="No search contributor"):
            indexer.index_documents("lexi.nope", ["x"])
    assert found(api, "mellon") == found(api, "gwaith") == []


def test_contributor_registration_is_validated() -> None:
    def spec(module_id: str, *doc_types: str) -> ModuleSpec:
        return ModuleSpec(
            id=module_id,
            name="M",
            description="",
            kinds=(KindDef("thing", "T", "Ts", icon="x", color="#000000"),)
            if module_id == "a"
            else (),
            search_contributors=tuple(SearchContributor(t, _lexicon, "L", "x") for t in doc_types),
        )

    with pytest.raises(RegistryError) as caught:
        ModuleRegistry([spec("a", "a.ok", "b.theirs", "a.Bad"), spec("b", "a.ok", "thing")])
    message = str(caught.value)
    assert "'b.theirs' must be 'a.<type>'" in message
    assert "'a.Bad' must be" in message
    assert "'a.ok' is also contributed by a" in message
    assert "'thing' must be 'b.<type>'" in message
    with pytest.raises(RegistryError, match="must be SearchContributor"):
        ModuleRegistry([ModuleSpec(id="c", name="C", description="", search_contributors=(1,))])  # type: ignore[arg-type]


# --- readers ----------------------------------------------------------------------------------


def test_readers_search_public_content_only(tmp_path: Path) -> None:
    with local_client(new_app(tmp_path), headers=HEADERS) as client:
        api = Api(client)
        api.make(
            "gadget",
            "Lantern",
            aliases=[{"alias": "Lamp"}, {"alias": "Secretglow", "visibility": "private"}],
            body=doc(p("A lantern with a public story"), private(p("hidden lantern canary"))),
            fields={"text": "lantern brass", "secret": "lantern canary field"},
        )
        api.make("gadget", "Spoiled", visibility="spoiler")
        api.make("gadget", "Canary Ghost", visibility="private")
        vault = api.vault
        assert found(api, "canary") == ["Canary Ghost", "Lantern"]
        assert found(api, "secretglow") == ["Lantern"]

    with local_client(new_app(tmp_path, read_only=True)) as client:
        reader = Api(client, vault)
        assert found(reader, "canary") == []
        assert found(reader, "secretglow") == []
        assert found(reader, "ghost") == []
        assert found(reader, "spoiled") == ["Spoiled"]
        assert search(reader, "spoiled")["items"][0]["visibility"] == "spoiler"
        assert found(reader, "lamp") == ["Lantern"]
        hits = search(reader, "lantern")["items"]
        assert [h["name"] for h in hits] == ["Lantern"]
        assert "canary" not in str(hits).lower()
        for snippet_query in ("brass", "story", "lamp"):
            assert "canary" not in str(search(reader, snippet_query)).lower()
        assert [h["alias"] for h in quick(reader, "lamp")] == ["Lamp"]
        assert quick(reader, "secret") == quick(reader, "ghost") == []
        assert "secretglow" not in str(quick(reader, "lantern")).lower()


# --- undo and rebuilds ------------------------------------------------------------------------


def test_undo_reindexes(api: Api) -> None:
    gadget = api.make("gadget", "Sextant")
    api.patch(gadget, name="Quadrant", aliases=[{"alias": "Navigator"}])
    assert found(api, "navigator") == ["Quadrant"]
    changeset = api.client.get(f"{api.base}/changes").json()["items"][0]
    assert api.client.post(f"{api.base}/changes/{changeset['id']}/revert").status_code == 200
    assert found(api, "sextant") == ["Sextant"]
    assert found(api, "quadrant") == found(api, "navigator") == []
    creation = api.client.get(f"{api.base}/changes").json()["items"][-1]
    assert api.client.post(f"{api.base}/changes/{creation['id']}/revert").status_code == 200
    assert found(api, "sextant") == []


def test_reindex_equals_the_incremental_index(app: FastAPI, api: Api) -> None:
    world = api.make("dimension", "World")
    tongue = api.make("tongue", "Dwarvish", dimension_id=world["id"])
    first = api.make(
        "gadget",
        "Anvil",
        dimension_id=world["id"],
        summary="heavy",
        body=doc(p("ring"), private(p("secret"))),
        fields={"text": "iron", "secret": "x", "extra.stars": 2},
        aliases=[{"alias": "Hammer friend", "visibility": "private"}],
    )
    second = api.make("misc", "Bellows")
    api.patch(first, name="Great Anvil", fields={"text": "steel"})
    api.delete(second["id"])
    third = api.make("misc", "Forge")
    api.delete(third["id"])
    api.delete(third["id"], purge=True)
    api.modules("extra", enabled=False)
    LEXICON["k"] = SearchDocument(
        doc_id="k",
        entity_id=tongue["id"],
        dimension_id=world["id"],
        visibility="spoiler",
        name="khazad",
    )
    for context in in_vault(app, api.vault):
        SearchIndexer(context).index_documents("lexi.entry", ["k"])

    incremental = index_rows(app, api.vault)
    assert len(incremental) == 5  # 4 entities (one trashed) and a module document
    for context in in_vault(app, api.vault):
        assert SearchIndexer(context).reindex() == 5
    assert index_rows(app, api.vault) == incremental
    assert found(api, "khazad") == ["khazad"]


def test_index_is_built_on_open_when_missing(tmp_path: Path) -> None:
    with local_client(new_app(tmp_path), headers=HEADERS) as client:
        api = Api(client)
        api.make("misc", "Watchtower")
        vault = api.vault
    database = next(tmp_path.glob("vaults/*/lore.db"))
    with closing(sqlite3.connect(database)) as connection, connection:
        # As right after the migration that created the tables: empty, no version recorded.
        connection.execute("DELETE FROM search_docs")
        connection.execute("DELETE FROM vault_meta WHERE key = ?", (INDEX_META_KEY,))
    with local_client(new_app(tmp_path), headers=HEADERS) as client:
        assert found(Api(client, vault), "watch") == ["Watchtower"]


def test_cli_reindex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    created = runner.invoke(cli.app, ["vault", "create", "Aetheria"])
    assert created.exit_code == 0, created.output
    result = runner.invoke(cli.app, ["vault", "reindex", created.output.split()[0]])
    assert result.exit_code == 0, result.output
    assert result.output == "search: rebuilt 0 documents\nmentions: rebuilt 0 entities\n"
    missing = runner.invoke(cli.app, ["vault", "reindex", "nope"])
    assert missing.exit_code == 1


def test_routes_are_in_the_openapi_document(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    base = "/api/v1/vaults/{vault_id}/search"
    assert paths[base]["get"]["operationId"] == "search_search"
    assert paths[f"{base}/quick"]["get"]["operationId"] == "search_quick"


# --- snippets (unit) --------------------------------------------------------------------------


def parts(text: str, *terms: Term) -> list[tuple[str, bool]] | None:
    found = highlight.snippet(text, terms)
    return None if found is None else [(part.text, part.match) for part in found]


def test_snippet_highlighting() -> None:
    word, phrase = Term(("dra",), prefix=True), Term(("red", "wing"), prefix=False)
    assert parts("The Dragon, the drake.", word) == [
        ("The ", False),
        ("Dragon", True),
        (", the ", False),
        ("drake", True),
        (".", False),
    ]
    assert parts("A red wing and a red wingtip", phrase) == [
        ("A ", False),
        ("red wing", True),
        (" and a red wingtip", False),
    ]
    assert parts("Évreux\nÉlan", Term(("elan",), prefix=False)) == [
        ("Évreux ", False),
        ("Élan", True),
    ]
    assert parts("nothing here", word) is None
    assert parts("", word) is None
    words = [f"w{i}" for i in range(40)]
    middle = parts(" ".join(words), Term(("w20",), prefix=False))
    assert middle == [
        ("…w16 w17 w18 w19 ", False),
        ("w20", True),
        (" " + " ".join(words[21:32]) + "…", False),
    ]
    end = parts(" ".join(words), Term(("w39",), prefix=False))
    assert end is not None
    assert end[0] == ("…" + " ".join(words[24:39]) + " ", False)
    assert end[-1] == ("w39", True)
