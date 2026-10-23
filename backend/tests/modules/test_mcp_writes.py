"""The mcp module's write tools (``docs/modules/mcp.md``, Writing; ``mcp.md`` §5): offered only
with ``access = author`` and ``writes = on``, each call one undoable changeset with ``origin =
"mcp"``, consistency refusals as tool errors, and Markdown bodies stored as rich text."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lore.modules.mcp.markdown import to_rich_text
from tests.entity_api import Api, make_client, problem
from tests.mcp_api import Mcp
from tests.modules.test_mcp import MODULES, YEAR

WRITE_TOOLS = {
    "describe_schema",
    "create_entity",
    "update_entity",
    "add_link",
    "remove_link",
    "set_fact",
    "create_event",
    "undo_last",
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path, MODULES) as client:
        yield client


@pytest.fixture
def api(client: TestClient) -> Api:
    api = Api(client)
    settings = {"access": "author", "writes": "on"}
    assert api.modules("mcp", enabled=True, settings=settings).status_code == 200
    return api


@pytest.fixture
def mcp(api: Api) -> Mcp:
    return Mcp(api.client, api.vault)


@pytest.fixture
def world(api: Api) -> dict[str, Any]:
    varn = api.make("dimension", "Varn")
    calendar = api.calendar(varn["id"], "Reckoning")
    varn = api.get(varn["id"]).json()
    return {"varn": varn, "calendar": calendar, "prime": varn["ext"]["prime_timeline_id"]}


def _tools(mcp: Mcp) -> set[str]:
    return {tool["name"] for tool in mcp.result("tools/list")["tools"]}


def _changes(api: Api, **params: Any) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/changes", params=params)
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _links(api: Api, entity_id: str) -> list[dict[str, Any]]:
    response = api.client.get(f"{api.base}/entities/{entity_id}/links")
    assert response.status_code == 200, response.json()
    items: list[dict[str, Any]] = response.json()["items"]
    return items


# --- offered only when allowed -------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings", [{"writes": "off"}, {"writes": "off", "access": "readers"}], ids=["off", "readers"]
)
def test_writes_off_refuses_every_write_tool(
    api: Api, mcp: Mcp, world: dict[str, Any], settings: dict[str, str]
) -> None:
    assert _tools(mcp) >= WRITE_TOOLS
    assert api.modules("mcp", settings=settings).status_code == 200
    assert not WRITE_TOOLS & _tools(mcp)
    arguments: dict[str, dict[str, Any]] = {
        "describe_schema": {},
        "create_entity": {"kind": "misc", "name": "Mira"},
        "update_entity": {"entity": "Varn", "revision": 1, "summary": "x"},
        "add_link": {"link_type": "core.related", "source": "Varn", "target": "Reckoning"},
        "remove_link": {"link_type": "core.related", "source": "Varn", "target": "Reckoning"},
        "set_fact": {"entity": "Varn", "field": "core.exists"},
        "create_event": {"name": "Feast", "start": "5", "dimension": world["varn"]["id"]},
        "undo_last": {},
    }
    assert set(arguments) == WRITE_TOOLS
    for name, args in arguments.items():
        mcp.failed(name, "writes_off", **args)
    assert _changes(api, origin="mcp") == []


def test_a_read_only_server_never_writes(tmp_path: Path) -> None:
    with make_client(tmp_path, MODULES) as client:
        api = Api(client)
        settings = {"access": "author", "writes": "on"}
        assert api.modules("mcp", enabled=True, settings=settings).status_code == 200
        vault = api.vault
    with make_client(tmp_path, MODULES, read_only=True) as client:
        client.headers.pop("X-Lore-Client", None)
        mcp = Mcp(client, vault)
        assert not WRITE_TOOLS & _tools(mcp)
        mcp.failed("create_entity", "writes_off", kind="misc", name="Mira")


# --- each write: one changeset, undoable ---------------------------------------------------------


def test_create_entity_with_a_markdown_body(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    queen = mcp.ok("create_entity", kind="misc", name="Queen Ilsa", dimension="Varn")
    body = f"Rules **Varn**, see [the realm](lore://{api.vault}/entities/{world['varn']['id']})."
    mira = mcp.ok(
        "create_entity",
        kind="misc",
        name="Mira",
        dimension=world["varn"]["id"],
        parent="Queen Ilsa",
        summary="A healer",
        body=body,
        tags=["healers"],
        aliases=["The Healer"],
    )
    assert mira["uri"] == f"lore://{api.vault}/entities/{mira['id']}"
    assert mira["parent_id"] == queen["id"]
    stored = api.get(mira["id"]).json()
    assert stored["body"] == to_rich_text(body, api.vault)
    assert stored["summary"] == "A healer"
    assert [tag["name"] for tag in stored["tags"]] == ["healers"]
    assert [alias["alias"] for alias in stored["aliases"]] == ["The Healer"]
    marks = [m for n in stored["body"]["content"][0]["content"] for m in n.get("marks", [])]
    assert {"type": "entityLink", "attrs": {"entityId": world["varn"]["id"]}} in marks
    # The entity link is a mention: the realm's backlinks list Mira.
    backlinks = api.client.get(f"{api.base}/entities/{world['varn']['id']}/backlinks").json()
    assert mira["id"] in {item["entity"]["id"] for item in backlinks["items"]}
    changes = _changes(api, origin="mcp")
    assert [c["summary"] for c in changes] == [
        "Created misc “Mira” (MCP create_entity, testclient)",
        "Created misc “Queen Ilsa” (MCP create_entity, testclient)",
    ]
    mcp.failed("create_entity", "validation_error", kind="nope", name="X")
    mcp.failed("create_entity", "validation_error", kind="event", name="X")


def test_every_call_is_its_own_changeset(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    """Two quick edits of one entity would merge for the app; the tools' never do."""
    mira = mcp.ok("create_entity", kind="misc", name="Mira", dimension="Varn")
    first = mcp.ok("update_entity", entity="Mira", revision=mira["revision"], summary="One")
    second = mcp.ok("update_entity", entity=mira["id"], revision=first["revision"], summary="Two")
    assert second["revision"] == first["revision"] + 1
    assert len(_changes(api, origin="mcp")) == 3
    stale = mcp.failed("update_entity", "revision_conflict", entity="Mira", revision=1, name="X")
    assert "current" in stale["context"]
    undone = mcp.ok("undo_last")
    assert undone["undone"].startswith("Edited “Mira”")
    assert api.get(mira["id"]).json()["summary"] == "One"
    mcp.ok("undo_last")
    assert api.get(mira["id"]).json()["summary"] == ""
    mcp.ok("undo_last")
    assert api.get(mira["id"]).status_code == 404
    mcp.failed("undo_last", "not_found")
    undos = _changes(api, origin="undo")
    assert len(undos) == 3
    assert all(c["summary"].endswith("(MCP undo_last, testclient)") for c in undos)


def test_undo_last_refuses_changed_rows(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    mira = mcp.ok("create_entity", kind="misc", name="Mira", dimension="Varn")
    stored = api.get(mira["id"]).json()
    assert api.patch(stored, summary="Edited in the app").status_code == 200
    mcp.failed("undo_last", "revert_conflict")
    assert api.get(mira["id"]).json()["summary"] == "Edited in the app"


def test_links(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    for name in ("Mira", "Tomas"):
        mcp.ok("create_entity", kind="misc", name=name, dimension="Varn")
    link = mcp.ok("add_link", link_type="core.related", source="Mira", target="Tomas")
    assert link["link_type"] == "core.related"
    timed = mcp.ok(
        "add_link",
        link_type="core.related",
        source="Tomas",
        target="Mira",
        role="friend",
        valid_from={"calendar": "Reckoning", "fields": {"year": "1020"}},
        valid_to=str(1030 * YEAR),
    )
    stored = next(
        item["link"]
        for item in _links(api, timed["source_id"])
        if item["link"]["id"] == timed["id"]
    )
    assert stored["timeline_id"] == world["prime"]
    assert stored["valid_from"]["anchor"]["kind"] == "calendar"  # the typed date is kept
    assert stored["valid_to"]["anchor"] == {"kind": "absolute", "t": str(1030 * YEAR)}
    ambiguous = mcp.failed(
        "remove_link", "conflict", link_type="core.related", source="Mira", target="Tomas"
    )
    assert set(ambiguous["context"]["ids"]) == {link["id"], timed["id"]}
    assert mcp.ok("remove_link", link=link["id"]) == {"id": link["id"], "removed": True}
    mcp.ok("remove_link", link_type="core.related", source="Mira", target="Tomas")
    mcp.failed("remove_link", "not_found", link_type="core.related", source="Mira", target="Tomas")
    mcp.failed("remove_link", "validation_error", link_type="core.related")
    mcp.failed("add_link", "not_found", link_type="no.such", source="Mira", target="Tomas")
    assert _links(api, link["source_id"]) == []
    assert [c["summary"] for c in _changes(api, origin="mcp")][:2] == [
        "Removed 1 link (MCP remove_link, testclient)",
        "Removed 1 link (MCP remove_link, testclient)",
    ]


def test_set_fact(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    mcp.ok("create_entity", kind="misc", name="Mira", dimension="Varn")
    fact = mcp.ok(
        "set_fact",
        entity="Mira",
        field="core.exists",
        valid_from={"calendar": "Reckoning", "fields": {"year": "1000"}},
        valid_to={"calendar": "Reckoning", "fields": {"year": "1060"}},
    )
    assert fact["timeline_id"] == world["prime"]
    assert fact["valid_from"]["date"] is not None
    state = mcp.ok("get_entity", entity="Mira", at=str(1022 * YEAR))["state"]
    assert state["existence"] == "exists"
    named = mcp.ok("set_fact", entity="Mira", field="core.name", value="Old Mira", valid_from="0")
    assert named["field"] == "core.name"
    mcp.failed("set_fact", "validation_error", entity="Mira", field="summary", value="x")


def test_create_event(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    war = mcp.ok(
        "create_event",
        name="The War",
        start={"calendar": "Reckoning", "fields": {"year": "1021"}},
        end={"calendar": "Reckoning", "fields": {"year": "1025"}},
        importance=5,
        category="war",
        body="A *long* war.",
    )
    assert war["dimension_id"] == world["varn"]["id"]
    assert war["timeline_id"] == world["prime"]
    assert war["start"]["t"] == str(1020 * YEAR)  # year 1 starts at 0
    stored = api.get(war["id"]).json()
    assert stored["ext"]["start"]["anchor"]["kind"] == "calendar"
    assert stored["ext"]["importance"] == 5
    battle = mcp.ok(
        "create_event",
        name="First battle",
        parent="The War",
        start={"event": "The War", "offset": str(30 * 86_400)},
        duration=str(86_400),
    )
    assert battle["start"]["t"] == str(1020 * YEAR + 30 * 86_400)
    assert battle["end"]["t"] == str(1020 * YEAR + 31 * 86_400)
    assert battle["parent_id"] == war["id"]
    # Moving the war moves the battle (the relative anchor stays linked).
    war_row = api.get(war["id"]).json()
    moved = {"anchor": {"kind": "absolute", "t": str(1022 * YEAR)}, "precision": "year"}
    assert api.patch(war_row, ext={"start": moved}).status_code == 200
    events = mcp.ok(
        "events_between", timeline=world["prime"], limit=100, **{"from": "0", "to": "9" * 12}
    )["items"]
    assert {e["name"]: e["start"]["t"] for e in events} == {"The War": str(1022 * YEAR)}
    assert api.get(battle["id"]).json()["ext"]["start_t"] == str(1022 * YEAR + 30 * 86_400)
    instant = mcp.ok("create_event", name="Feast", start="0", dimension="Varn")
    assert instant["end"] is None or instant["end"]["t"] == instant["start"]["t"]
    mcp.failed("create_event", "validation_error", name="Lost", start="5")
    mcp.failed(
        "create_event",
        "validation_error",
        name="Both",
        start="5",
        dimension="Varn",
        end="9",
        duration="4",
    )


def test_consistency_refusals_are_tool_errors(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    """An error-severity finding refuses the write; the tool error lists the findings."""
    rule = "core.event.subevent_outside_parent"
    url = f"{api.base}/consistency/rules/{rule}"
    assert api.client.patch(url, json={"severity": "error"}).status_code == 200
    mcp.ok("create_event", name="War", start="100", end="200", dimension="Varn")
    before = _changes(api, origin="mcp")
    refused = mcp.failed("create_event", "consistency_error", name="Raid", start="50", parent="War")
    assert [f["rule_id"] for f in refused["context"]["findings"]] == [rule], refused
    assert _changes(api, origin="mcp") == before


def test_describe_schema(mcp: Mcp, world: dict[str, Any]) -> None:
    schema = mcp.ok("describe_schema")
    kinds = {kind["key"]: kind for kind in schema["kinds"]}
    assert {"misc", "event"} <= set(kinds)
    assert not {"dimension", "calendar", "timeline"} & set(kinds)  # system kinds are left out
    link_types = {t["key"]: t for t in schema["link_types"]}
    assert link_types["core.related"]["label"] == "related to"


def test_the_history_filter_knows_the_origin(api: Api, mcp: Mcp, world: dict[str, Any]) -> None:
    mcp.ok("create_entity", kind="misc", name="Mira", dimension="Varn")
    assert len(_changes(api, origin="mcp")) == 1
    assert all(c["origin"] != "mcp" for c in _changes(api, origin="ui"))


# --- the token routes (Settings → AI access) -----------------------------------------------------


def test_the_token_routes(api: Api, mcp: Mcp) -> None:
    url = f"{api.base}/m/mcp/token"
    shown = api.client.get(url).json()
    assert shown == {"token": mcp.token, "source": "file"}
    renewed = api.client.post(f"{url}/regenerate")
    assert renewed.status_code == 200, renewed.json()
    token = renewed.json()["token"]
    assert token != mcp.token
    assert api.client.get(url).json()["token"] == token
    old = mcp.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert old.status_code == 401
    assert Mcp(api.client, api.vault, token=token).result("tools/list")["tools"]
    assert problem(api.client.get(url, params={"as_reader": True}), 404, "not_found")
    assert api.modules("mcp", enabled=False).status_code == 200
    assert problem(api.client.get(url), 404, "module_disabled")


def test_the_token_routes_with_a_token_from_the_environment(tmp_path: Path) -> None:
    with make_client(tmp_path, MODULES, mcp_token="from-env-token") as client:
        api = Api(client)
        assert api.modules("mcp", enabled=True).status_code == 200
        url = f"{api.base}/m/mcp/token"
        assert client.get(url).json() == {"token": "from-env-token", "source": "environment"}
        assert problem(client.post(f"{url}/regenerate"), 409, "token_from_environment")


def test_the_token_routes_on_a_read_only_server(tmp_path: Path) -> None:
    with make_client(tmp_path, MODULES) as client:
        api = Api(client)
        assert api.modules("mcp", enabled=True).status_code == 200
        vault = api.vault
    with make_client(tmp_path, MODULES, read_only=True) as client:
        url = f"/api/v1/vaults/{vault}/m/mcp/token"
        assert client.get(url).status_code == 404
        assert client.post(f"{url}/regenerate").status_code == 403
