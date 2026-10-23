"""The MCP tools and resources against the canary vault (``mcp.md`` §8): with ``access =
readers``, on a read-only server and on a published snapshot, no canary string or hidden id is in
any result, snippet, error or resource (the leak suite's byte scan); with ``access = author``,
the private content is there."""

import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.mcp_api import Mcp
from tests.visibility.canary import Canary, build_canary_vault, leak_client, publish_canary

ROOT = "lore://{vault}/entities/{id}"


@dataclass(frozen=True)
class Request:
    method: str
    params: dict[str, Any]

    @property
    def echo(self) -> str:
        """What the request itself says: an error may repeat it (``No calendar 'X'.``)."""
        return repr(self.params)


def _tool(name: str, **arguments: Any) -> Request:
    return Request("tools/call", {"name": name, "arguments": arguments})


def _requests(canary: Canary, mcp: Mcp) -> Iterator[Request]:
    """Every tool and resource, with visible and hidden ids, names and canary searches."""
    world = canary.public["Aetheria"]
    prime = canary.public["Prime"]
    hidden = sorted(canary.hidden_ids)
    yield Request("tools/list", {})
    yield _tool("list_dimensions", limit=100)
    for needle in [*canary.strings, "lantern", "Lamp", "Coronation"]:
        yield _tool("search", query=needle, limit=100)
        yield _tool("get_entity", entity=needle)
    for entity_id in [*canary.public.values(), *hidden]:
        yield _tool("get_entity", entity=entity_id)
        yield _tool("get_entity", entity=entity_id, at="100000000", timeline=prime)
        yield _tool("list_entities", parent=entity_id, limit=100)
        yield Request("resources/read", {"uri": ROOT.format(vault=canary.vault, id=entity_id)})
    yield _tool("list_entities", limit=100)
    yield _tool("list_entities", dimension=world, at="100000000", limit=100)
    yield _tool("list_entities", tags=list(canary.tags), limit=100)
    yield _tool("list_entities", tags=list(canary.tags.values()), limit=100)
    for timeline in [prime, *hidden]:
        yield _tool("events_between", timeline=timeline, **{"from": "0", "to": str(10**12)})
        yield _tool(
            "events_between", timeline=timeline, limit=100, **{"from": "0", "to": str(10**11)}
        )
    yield _tool("events_between", dimension=world, **{"from": "0", "to": "present"})
    for parent in hidden:
        yield _tool("events_between", parent=parent, timeline=prime, **{"from": "0", "to": "9"})
    yield _tool("convert_date", date="100000000", dimension=world)
    yield _tool("convert_date", date={"calendar": "Common Reckoning", "fields": {"year": "3"}})
    for calendar in [*hidden, *canary.strings]:
        yield _tool("convert_date", date={"calendar": calendar, "fields": {"year": "3"}})
        yield _tool("convert_date", date="5", dimension=world, calendars=[calendar])
    cursor: str | None = None
    while True:
        yield Request("resources/list", {} if cursor is None else {"cursor": cursor})
        page = mcp.result("resources/list", {} if cursor is None else {"cursor": cursor})
        cursor = page.get("nextCursor")
        if cursor is None:
            break
    yield Request("resources/templates/list", {})


def _answers(canary: Canary, mcp: Mcp) -> Iterator[tuple[Request, str]]:
    for request in _requests(canary, mcp):
        response = mcp.post({"jsonrpc": "2.0", "id": 1, **request.__dict__})
        assert response.status_code == 200, (request, response.text)
        yield request, response.text


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Canary, Path]:
    """The canary vault with the module on (``access = readers``), and a copy of its data
    directory with ``access = author``, made before any reader opens the vault."""
    canary = build_canary_vault(tmp_path_factory.mktemp("mcp-canary"))
    author_dir = tmp_path_factory.mktemp("mcp-author") / "data"
    _enable(canary.data_dir, canary.vault, "readers")
    shutil.copytree(canary.data_dir, author_dir)
    _enable(author_dir, canary.vault, "author")
    return canary, author_dir


def _enable(data_dir: Path, vault_id: str, access: str) -> None:
    with leak_client(data_dir) as client:
        response = client.patch(
            f"/api/v1/vaults/{vault_id}/modules/mcp",
            json={"enabled": True, "settings": {"access": access}},
        )
        assert response.status_code == 200, response.json()


@pytest.fixture(scope="module")
def canary(built: tuple[Canary, Path]) -> Canary:
    return built[0]


@pytest.fixture(scope="module", params=["readers", "read_only", "published"])
def reader(
    request: pytest.FixtureRequest, canary: Canary, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Mcp]:
    data_dir: Path = canary.data_dir
    settings: dict[str, Any] = {} if request.param == "readers" else {"read_only": True}
    if request.param == "published":
        data_dir = publish_canary(canary, tmp_path_factory.mktemp("mcp-published"))
    with leak_client(data_dir, **settings) as client:
        client.headers.pop("X-Lore-Client")
        yield Mcp(client, canary.vault)


def test_readers_never_see_canaries(reader: Mcp, canary: Canary) -> None:
    problems = []
    for request, text in _answers(canary, reader):
        leaked = [n for n in canary.needles if n in text and n not in request.echo]
        if leaked:
            problems.append(f"{request.method} {request.params}: leaked {leaked}")
    assert problems == [], "\n".join(problems)


def test_readers_get_answers(reader: Mcp, canary: Canary) -> None:
    """The reader calls answer (the scan above would pass on errors alone)."""
    lantern = reader.ok("get_entity", entity="Lamp")
    assert lantern["id"] == canary.public["Lantern"]
    assert "A lantern seen by someone" in lantern["markdown"]
    hits = reader.ok("search", query="lantern")["items"]
    assert canary.public["Lantern"] in {hit["entity_id"] for hit in hits}
    events = reader.ok(
        "events_between",
        timeline=canary.public["Prime"],
        limit=100,
        **{"from": "0", "to": "9" * 11},
    )["items"]
    assert "Coronation" in {event["name"] for event in events}
    # The world's default calendar is private: readers get Absolute dates.
    assert all("t = " in event["start"]["date"] for event in events), events
    world = reader.ok("list_dimensions")["items"]
    assert [w["name"] for w in world] == ["Aetheria", "Dreamrealm"]
    assert [c["name"] for c in world[0]["calendars"]] == ["Common Reckoning"]  # not the secret one
    reader.failed("get_entity", "not_found", entity=sorted(canary.hidden_ids)[0])


def test_authors_see_the_private_content(built: tuple[Canary, Path]) -> None:
    """The positive control: with ``access = author`` the same calls reach private content."""
    canary, author_dir = built
    with leak_client(author_dir) as client:
        client.headers.pop("X-Lore-Client")
        seen = "\n".join(text for _, text in _answers(canary, Mcp(client, canary.vault)))
    found = [needle for needle in canary.strings if needle in seen]
    assert len(found) >= len(canary.strings) // 2, found
    assert any(hidden in seen for hidden in canary.hidden_ids)


def test_the_requests_are_many(reader: Mcp, canary: Canary) -> None:
    assert sum(1 for _ in _requests(canary, reader)) > 200
