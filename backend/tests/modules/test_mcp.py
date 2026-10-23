"""The mcp module (``docs/modules/mcp.md``, ``mcp.md`` §2-§8): the endpoint's authentication,
settings, read tools, resources and dates, and a session with the SDK's own client."""

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from lore.core.api.bearer import ServerToken
from lore.modules import ALL_MODULES
from tests.conftest import BASE_URL
from tests.entity_api import Api, invalid, make_client, problem
from tests.entity_modules import ENTITY_MODULES
from tests.mcp_api import Mcp, endpoint

MODULES = tuple({m.id: m for m in (*ALL_MODULES, *ENTITY_MODULES)}.values())
CONFORMANCE = Path(__file__).resolve().parents[3] / "spec/chronology/conformance/calendars"
DAY = 86_400
YEAR = 365 * DAY


def _client(tmp_path: Path, **settings: Any) -> TestClient:
    return make_client(tmp_path, MODULES, **settings)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path) as client:
        yield client


@pytest.fixture
def api(client: TestClient) -> Api:
    api = Api(client)
    assert api.modules("mcp", enabled=True).status_code == 200
    return api


def _anonymous(client: TestClient) -> TestClient:
    """The client without ``X-Lore-Client``: MCP clients don't send it."""
    client.headers.pop("X-Lore-Client", None)
    return client


@pytest.fixture
def mcp(api: Api) -> Mcp:
    return Mcp(api.client, api.vault)


@pytest.fixture
def world(api: Api) -> dict[str, Any]:
    """Varn: a dimension with the Years calendar (its default), a public and a private event."""
    varn = api.make("dimension", "Varn", summary="The northern realm")
    calendar = api.calendar(varn["id"], "Reckoning")
    varn = api.get(varn["id"]).json()
    assert varn["ext"]["default_calendar_id"] == calendar["id"]
    home = {"dimension_id": varn["id"]}
    start = {"anchor": {"kind": "absolute", "t": str(1021 * YEAR)}, "precision": "year"}
    sundering = api.make("event", "The Sundering", ext={"start": start}, **home)
    api.make("event", "Aftershock", parent_id=sundering["id"], ext={"start": start}, **home)
    secret = api.make("event", "Secret pact", visibility="private", ext={"start": start}, **home)
    queen = api.make(
        "misc", "Queen Ilsa", aliases=[{"alias": "The Ice Queen"}], body=_doc("Ruler."), **home
    )
    return {
        "varn": varn,
        "calendar": calendar,
        "sundering": sundering,
        "secret": secret,
        "queen": queen,
        "prime": varn["ext"]["prime_timeline_id"],
    }


def _doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


# --- authentication ------------------------------------------------------------------------------


def _initialize(**headers: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }


def test_the_endpoint_needs_the_token(api: Api, mcp: Mcp) -> None:
    client = _anonymous(api.client)
    url = endpoint(api.vault)
    missing = client.post(url, json=_initialize())
    assert problem(missing, 401, "unauthorized")
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    wrong = client.post(url, json=_initialize(), headers={"Authorization": "Bearer nope"})
    assert problem(wrong, 401, "unauthorized")
    basic = client.post(url, json=_initialize(), headers={"Authorization": f"Basic {mcp.token}"})
    assert problem(basic, 401, "unauthorized")
    assert problem(client.get(url), 401, "unauthorized")
    answer = mcp.result("initialize", _initialize()["params"])
    assert answer["serverInfo"]["name"] == "lore-world-tracker"
    assert "list_dimensions" in answer["instructions"]


def test_origin_must_be_allowed(api: Api, mcp: Mcp) -> None:
    _anonymous(api.client)
    evil = mcp.post(_initialize(), Origin="https://evil.example")
    assert problem(evil, 403, "bad_origin")
    assert mcp.post(_initialize(), Origin="null").status_code == 403
    assert mcp.post(_initialize(), Origin="http://localhost:5173").status_code == 200


def test_the_module_is_off_by_default(client: TestClient) -> None:
    api = Api(client)
    states = {m["id"]: m for m in client.get(f"{api.base}/registry").json()["modules"]}
    assert states["mcp"]["enabled"] is False
    assert states["mcp"]["settings"] == {"access": "readers", "writes": "off"}
    off = Mcp(_anonymous(client), api.vault).post(_initialize())
    assert problem(off, 404, "module_disabled")


def test_the_token_file(tmp_path: Path) -> None:
    token = ServerToken.of_data_dir(tmp_path)
    value = token.value()
    assert value is not None
    assert len(value) >= 43  # 256 bits, URL-safe base64
    path = tmp_path / "secrets" / "mcp-token"
    assert path.read_text().strip() == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert ServerToken.of_data_dir(tmp_path).value() == value  # read back, not replaced
    assert token.matches_header(f"Bearer {value}")
    assert token.matches_header(f"bearer {value}")
    assert not token.matches_header(value)
    assert not token.matches_header(None)
    renewed = token.regenerate()
    assert renewed != value
    assert ServerToken.of_data_dir(tmp_path).value() == renewed
    assert not token.matches(value)


def test_the_token_from_the_environment(tmp_path: Path) -> None:
    with _client(tmp_path, mcp_token="from-env-token") as client:
        api = Api(client)
        assert api.modules("mcp", enabled=True).status_code == 200
        mcp = Mcp(_anonymous(client), api.vault, token="from-env-token")
        assert mcp.result("tools/list")["tools"]
        token: ServerToken = client.app.state.bearer_token  # type: ignore[attr-defined]
        assert token.from_environment
        with pytest.raises(Exception, match="LORE_MCP_TOKEN"):
            token.regenerate()
    assert not (tmp_path / "secrets").exists()


def test_without_a_token_nothing_authenticates(tmp_path: Path) -> None:
    (tmp_path / "secrets").write_text("not a folder")  # the token can't be created
    token = ServerToken.of_data_dir(tmp_path)
    assert token.value() is None
    assert not token.matches_header("Bearer ")
    assert not token.matches_header("Bearer None")


def test_a_read_only_server_serves_the_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        api = Api(client)
        assert api.modules("mcp", enabled=True, settings={"access": "author"}).status_code == 200
        api.make("misc", "Hidden", visibility="private")
        api.make("misc", "Shown")
    with _client(tmp_path, read_only=True) as client:
        mcp = Mcp(_anonymous(client), api.vault)
        names = [item["name"] for item in mcp.ok("list_entities")["items"]]
        assert names == ["Shown"]  # always the readers' policy
        assert client.post(f"{api.base}/entities", json={}).status_code == 403  # still read-only


def test_get_is_not_served(api: Api, mcp: Mcp) -> None:
    """The endpoint is stateless: no server-to-client stream to open."""
    response = api.client.get(endpoint(api.vault), headers=mcp.headers)
    assert response.status_code == 405


# --- settings ------------------------------------------------------------------------------------


def test_settings(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    def names() -> set[str]:
        return {item["name"] for item in mcp.ok("list_entities", kinds=["event"])["items"]}

    assert names() == {"The Sundering", "Aftershock"}
    assert invalid(api.modules("mcp", settings={"writes": "on"})) == ["settings"]
    assert invalid(api.modules("mcp", settings={"access": "everyone"})) == ["settings.access"]
    assert invalid(api.modules("mcp", settings={"color": "red"})) == ["settings.color"]
    assert invalid(api.modules("graph", settings={"access": "author"})) == ["settings"]
    changed = api.modules("mcp", settings={"access": "author"})
    assert changed.status_code == 200, changed.json()
    state = next(m for m in changed.json()["modules"] if m["id"] == "mcp")
    assert state == {**state, "enabled": True, "settings": {"access": "author", "writes": "off"}}
    assert names() == {"The Sundering", "Aftershock", "Secret pact"}
    both = api.modules("mcp", settings={"writes": "on"})
    assert both.status_code == 200, both.json()
    assert api.modules("mcp", enabled=False).json()["disabled"] == ["mcp"]
    settings = next(
        m["settings"] for m in api.client.get(f"{api.base}/registry").json()["modules"]
        if m["id"] == "mcp"
    )  # fmt: skip
    assert settings == {"access": "author", "writes": "on"}  # kept while it is off


def test_a_disabled_module_keeps_answering_404(api: Api, mcp: Mcp) -> None:
    api.modules("mcp", enabled=False)
    assert problem(mcp.post(_initialize()), 404, "module_disabled")


# --- tools ---------------------------------------------------------------------------------------


def test_tools_are_listed_with_schemas(mcp: Mcp) -> None:
    tools = {tool["name"]: tool for tool in mcp.result("tools/list")["tools"]}
    assert list(tools) == [
        "list_dimensions", "search", "get_entity", "list_entities", "events_between",
        "convert_date",
    ]  # fmt: skip
    for tool in tools.values():
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is True
    assert set(tools["events_between"]["inputSchema"]["required"]) == {"from", "to"}


def test_list_dimensions(world: dict[str, Any], mcp: Mcp) -> None:
    (varn,) = mcp.ok("list_dimensions")["items"]
    assert varn["name"] == "Varn"
    assert varn["summary"] == "The northern realm"
    assert varn["calendars"] == [{"id": world["calendar"]["id"], "name": "Reckoning"}]
    assert varn["default_calendar_id"] == world["calendar"]["id"]
    assert varn["timelines"] == [{"id": world["prime"], "name": "Prime", "prime": True}]
    assert varn["present"] is None
    assert varn["duration"] == str(10**12)


def test_search(world: dict[str, Any], mcp: Mcp) -> None:
    hits = mcp.ok("search", query="sundering")["items"]
    assert [hit["entity_id"] for hit in hits] == [world["sundering"]["id"]]
    ruler = mcp.ok("search", query="ruler")["items"]
    assert ruler[0]["snippet"] == "**Ruler**."
    assert mcp.ok("search", query="pact")["items"] == []  # private
    mcp.failed("search", "validation_error", query="")


def test_get_entity(world: dict[str, Any], mcp: Mcp) -> None:
    queen = world["queen"]
    for ref in (queen["id"], "Queen Ilsa", "queen ilsa", "The Ice Queen"):
        found = mcp.ok("get_entity", entity=ref)
        assert found["id"] == queen["id"], ref
    assert found["aliases"] == ["The Ice Queen"]
    assert found["uri"] == f"lore://{mcp.vault_id}/entities/{queen['id']}"
    markdown = found["markdown"]
    assert "Ruler." in markdown
    assert f"[Varn](lore://{mcp.vault_id}/entities/{world['varn']['id']})" in markdown
    mcp.failed("get_entity", "not_found", entity="Nobody")
    mcp.failed("get_entity", "not_found", entity=world["secret"]["id"])
    mcp.failed("get_entity", "not_found", entity="Secret pact")


def test_get_entity_ambiguous(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    api.make("misc", "Twin", dimension_id=world["varn"]["id"])
    api.make("misc", "Twin", dimension_id=world["varn"]["id"])
    problem_ = mcp.failed("get_entity", "conflict", entity="twin")
    assert len(problem_["context"]["ids"]) == 2


def test_get_entity_at_a_moment(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    queen, varn = world["queen"], world["varn"]
    crowned = {"anchor": {"kind": "absolute", "t": str(1000 * YEAR)}, "precision": "year"}
    response = api.client.post(
        f"{api.base}/entities/{queen['id']}/facts",
        json={"field_key": "core.exists", "timeline_id": world["prime"], "valid_from": crowned},
    )
    assert response.status_code == 201, response.json()
    then = mcp.ok("get_entity", entity="Queen Ilsa", at=str(1010 * YEAR))["state"]
    assert then["existence"] == "exists"
    assert then["timeline_id"] == world["prime"]
    assert then["at"] == {"t": str(1010 * YEAR), "date": "1 1011"}
    before = mcp.ok(
        "get_entity",
        entity="Queen Ilsa",
        at={"calendar": "Reckoning", "fields": {"year": "900"}},
    )["state"]
    assert before["existence"] == "not_exists"
    assert before["at"]["t"] == str(899 * YEAR)
    in_varn = mcp.ok("get_entity", entity=varn["id"], at="5", timeline=world["prime"])
    assert in_varn["state"]["name"] == "Varn"
    mcp.failed("get_entity", "validation_error", entity="Queen Ilsa", at="soon")


def test_list_entities(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    tagged = api.make("misc", "Tagged", tags=["Royal"], dimension_id=world["varn"]["id"])
    events = mcp.ok("list_entities", kinds=["event"])["items"]
    assert [e["name"] for e in events] == ["Aftershock", "The Sundering"]
    assert mcp.ok("list_entities", tags=["royal"])["items"][0]["id"] == tagged["id"]
    mcp.failed("list_entities", "not_found", tags=["Nope"])
    children = mcp.ok("list_entities", parent=world["sundering"]["id"])["items"]
    assert [c["name"] for c in children] == ["Aftershock"]
    first = mcp.ok("list_entities", limit=2)
    assert len(first["items"]) == 2
    second = mcp.ok("list_entities", limit=2, cursor=first["next_cursor"])
    assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in second["items"])
    mcp.failed("list_entities", "validation_error", limit=101)
    existing = mcp.ok("list_entities", dimension=world["varn"]["id"], at="0", kinds=["misc"])
    assert {e["existence"] for e in existing["items"]} == {"unknown"}
    mcp.failed("list_entities", "validation_error", at="0")


def test_events_between(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    varn = world["varn"]["id"]
    later = {"anchor": {"kind": "absolute", "t": str(1030 * YEAR)}, "precision": "year"}
    api.make("event", "Thaw", ext={"start": later}, dimension_id=varn)
    found = mcp.ok(
        "events_between",
        dimension=varn,
        **{"from": {"calendar": "Reckoning", "fields": {"year": "1000"}}, "to": str(1100 * YEAR)},
    )
    assert found["timeline_id"] == world["prime"]
    assert found["from"] == {"t": str(999 * YEAR), "date": "1 1000"}
    assert [(e["name"], e["start"]["date"]) for e in found["items"]] == [
        ("The Sundering", "1022"),
        ("Thaw", "1031"),
    ]
    assert found["items"][0]["sub_events"] == 1  # Aftershock, folded
    subs = mcp.ok(
        "events_between",
        timeline=world["prime"],
        parent=world["sundering"]["id"],
        **{"from": "0", "to": str(2000 * YEAR)},
    )["items"]
    assert [e["name"] for e in subs] == ["Aftershock"]
    paged = mcp.ok("events_between", dimension=varn, limit=1, **{"from": "0", "to": str(10**11)})
    assert len(paged["items"]) == 1
    rest = mcp.ok(
        "events_between",
        dimension=varn,
        cursor=paged["next_cursor"],
        **{"from": "0", "to": str(10**11)},
    )
    assert [e["name"] for e in rest["items"]] == ["Thaw"]
    assert rest["next_cursor"] is None
    # Calendar dates name their dimension: no timeline needed.
    by_calendar = mcp.ok(
        "events_between",
        **{
            "from": {"calendar": "Reckoning", "fields": {"year": "1030"}},
            "to": {"calendar": world["calendar"]["id"], "fields": {"year": "1040"}},
        },
    )
    assert [e["name"] for e in by_calendar["items"]] == ["Thaw"]
    mcp.failed("events_between", "validation_error", **{"from": "0", "to": "10"})
    mcp.failed("events_between", "validation_error", dimension=varn, **{"from": "9", "to": "1"})
    mcp.failed("events_between", "validation_error", dimension=varn, **{"from": "0", "to": "now"})
    mcp.failed(
        "events_between", "validation_error", dimension=varn, cursor="x", **{"from": "0", "to": "1"}
    )


def test_events_between_present(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    varn = world["varn"]
    mcp.failed(
        "events_between", "validation_error", dimension=varn["id"], **{"from": "0", "to": "present"}
    )
    present = {"anchor": {"kind": "absolute", "t": str(1025 * YEAR)}, "precision": "year"}
    patched = api.patch(varn, ext={"present": present})
    assert patched.status_code == 200, patched.json()
    found = mcp.ok("events_between", dimension=varn["id"], **{"from": "0", "to": "present"})
    assert [e["name"] for e in found["items"]] == ["The Sundering"]
    assert mcp.ok("list_dimensions")["items"][0]["present"] == {
        "t": str(1025 * YEAR),
        "date": "1 1026",
    }


def test_convert_date(world: dict[str, Any], mcp: Mcp) -> None:
    varn, calendar = world["varn"]["id"], world["calendar"]["id"]
    moment = mcp.ok("convert_date", date=str(YEAR + DAY), dimension=varn)
    assert moment["t"] == str(YEAR + DAY)
    assert [(d["calendar"], d["date"]) for d in moment["dates"]] == [
        ("Reckoning", "2 2"),
        ("Absolute", "t = 31,622,400 s"),
    ]
    dated = mcp.ok(
        "convert_date", date={"calendar": "reckoning", "fields": {"year": 2, "day": "2"}}
    )
    assert dated["t"] == str(YEAR + DAY)
    assert dated["dimension_id"] == varn
    only = mcp.ok("convert_date", date="0", dimension=varn, calendars=[calendar])
    assert [d["calendar_id"] for d in only["dates"]] == [calendar, "absolute"]
    beyond = mcp.ok("convert_date", date=str(10**13), dimension=varn)
    assert {d.get("error") for d in beyond["dates"]} == {
        "The moment lies after the end of the dimension."
    }
    mcp.failed("convert_date", "validation_error", date="5")
    mcp.failed("convert_date", "not_found", date={"calendar": "Nope", "fields": {"year": "1"}})
    bad = mcp.failed(
        "convert_date", "validation_error", date={"calendar": "Reckoning", "fields": {"month": "1"}}
    )
    assert "year" in bad["detail"]
    mcp.failed(
        "convert_date",
        "validation_error",
        date={"calendar": "Reckoning", "fields": {"day": "400", "year": "1"}},
    )


def test_bad_arguments_and_unknown_tools(mcp: Mcp) -> None:
    problem_ = mcp.failed("search", "validation_error", query="x", extra=1)
    assert problem_["errors"][0]["path"] == "extra"
    mcp.failed("drop_tables", "unknown_tool")


# --- resources -----------------------------------------------------------------------------------


def test_resources(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    listed = mcp.result("resources/list")["resources"]
    names = {resource["name"] for resource in listed}
    assert {"Varn", "Queen Ilsa", "The Sundering"} <= names
    assert "Secret pact" not in names
    (template,) = mcp.result("resources/templates/list")["resourceTemplates"]
    assert template["uriTemplate"] == f"lore://{api.vault}/entities/{{id}}"
    uri = f"lore://{api.vault}/entities/{world['queen']['id']}"
    (content,) = mcp.result("resources/read", {"uri": uri})["contents"]
    assert content["mimeType"] == "text/markdown"
    assert "Ruler." in content["text"]
    secret = mcp.read(f"lore://{api.vault}/entities/{world['secret']['id']}")
    assert "error" in secret
    other_vault = mcp.read(f"lore://{world['varn']['id']}/entities/{world['queen']['id']}")
    assert "error" in other_vault
    assert "error" in mcp.read("https://example.com/")


def test_resources_page(api: Api, mcp: Mcp) -> None:
    for n in range(105):
        api.make("misc", f"Item {n:03}")
    first = mcp.result("resources/list")
    assert len(first["resources"]) == 100
    second = mcp.result("resources/list", {"cursor": first["nextCursor"]})
    assert len(second["resources"]) == 5
    assert "nextCursor" not in second


# --- dates match the API -------------------------------------------------------------------------


def _conformance_calendars() -> list[Path]:
    return sorted(CONFORMANCE.glob("*.json"))


@pytest.mark.parametrize("path", _conformance_calendars(), ids=lambda p: p.stem)
def test_dates_match_the_api(tmp_path: Path, path: Path) -> None:
    """``convert_date`` shows a moment as ``POST /time/convert`` does, and reads a calendar date
    as ``POST /time/resolve`` does, for the conformance calendars."""
    calendar = json.loads(path.read_text())
    context = calendar["context"]
    with _client(tmp_path) as client:
        api = Api(client)
        api.modules("mcp", enabled=True)
        dimension = api.make(
            "dimension",
            "World",
            ext={"base_unit": context["base_unit"], "duration": context["dimension_duration"]},
        )
        created = api.create(
            "calendar",
            path.stem,
            dimension_id=dimension["id"],
            ext={"definition": calendar["definition"]},
        )
        if created.status_code != 201:
            pytest.skip(f"not a vault calendar: {created.json()['detail']}")
        calendar_id = created.json()["entity"]["id"]
        origin = int(next(iter(context.get("resolved", {}).values()), "0"))
        moments = [origin, origin + 1, origin + 86_399, origin + 10**7 + 12_345, origin + 10**9]
        moments = [t for t in moments if t <= int(context["dimension_duration"])]
        converted = client.post(
            f"{api.base}/time/convert",
            json={
                "dimension_id": dimension["id"],
                "moments": [str(t) for t in moments],
                "calendars": [calendar_id],
            },
        ).json()["items"]
        mcp = Mcp(_anonymous(client), api.vault)
        for item in converted:
            expected = item["results"][0]
            ours = mcp.ok("convert_date", date=item["t"], dimension=dimension["id"])["dates"][0]
            assert (ours.get("fields"), ours.get("date")) == (
                expected.get("fields"),
                expected.get("display"),
            ), item["t"]
            if expected.get("fields") is None:
                continue
            levels = expected["fields"]["levels"]
            fields = {level: value.get("id") or value["n"] for level, value in levels.items()}
            client.headers["X-Lore-Client"] = "test"
            resolved = client.post(
                f"{api.base}/time/resolve",
                json={
                    "dimension_id": dimension["id"],
                    "items": [
                        {
                            "time_point": {
                                "anchor": {
                                    "kind": "calendar",
                                    "calendar_id": calendar_id,
                                    "fields": fields,
                                },
                                "precision": next(iter(reversed(levels))),
                            }
                        }
                    ],
                },
            ).json()["items"][0]["start"]
            _anonymous(client)
            back = mcp.tool("convert_date", date={"calendar": calendar_id, "fields": fields})
            if resolved["t"] is None:
                assert back.is_error, back.text
            else:
                assert back.data["t"] == resolved["t"], fields


# --- the SDK's client ----------------------------------------------------------------------------


def test_a_session_with_the_sdk_client(api: Api, world: dict[str, Any], mcp: Mcp) -> None:
    app = api.client.app
    url = f"{BASE_URL}{endpoint(api.vault)}"

    async def session() -> dict[str, Any]:
        transport = httpx2.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {mcp.token}"}
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE_URL, headers=headers) as http,
            streamable_http_client(url, http_client=http) as (read, write, *_),
            ClientSession(read, write) as client,
        ):
            initialized = await client.initialize()
            tools = await client.list_tools()
            found = await client.call_tool("search", {"query": "queen"})
            resource = await client.read_resource(
                f"lore://{api.vault}/entities/{world['queen']['id']}"
            )
            failed = await client.call_tool("get_entity", {"entity": "Nobody"})
            return {
                "server": initialized.server_info.name,
                "tools": [tool.name for tool in tools.tools],
                "found": found.structured_content,
                "resource": resource.contents[0],
                "failed": failed,
            }

    result = anyio.run(session)
    assert result["server"] == "lore-world-tracker"
    assert "events_between" in result["tools"]
    assert result["found"]["items"][0]["name"] == "Queen Ilsa"
    assert "Ruler." in result["resource"].text
    assert result["failed"].is_error
    assert json.loads(result["failed"].content[0].text)["code"] == "not_found"


def test_the_token_never_reaches_vaults(api: Api, mcp: Mcp) -> None:
    folder = api.client.app.state.vaults.get(api.vault).path  # type: ignore[attr-defined]
    assert mcp.token is not None
    token = mcp.token.encode()
    for path in Path(folder).rglob("*"):
        if path.is_file():
            assert token not in path.read_bytes(), path
    assert os.environ.get("LORE_MCP_TOKEN") is None
