"""The canary leak suite (``visibility-and-sharing.md`` §5): every GET route, called with its
recipes against the canary vault, must never return a canary string or a hidden id to readers,
on a read-only server and with ``?as_reader=true``."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.visibility.canary import Canary, build_canary_vault, leak_client
from tests.visibility.recipes import RECIPES

# Reader modes: (server settings, query parameters added to every request).
READER_MODES: dict[str, tuple[dict[str, Any], dict[str, str]]] = {
    "read_only": ({"read_only": True}, {}),
    "as_reader": ({}, {"as_reader": "true"}),
}


@pytest.fixture(scope="module")
def canary(tmp_path_factory: pytest.TempPathFactory) -> Canary:
    return build_canary_vault(tmp_path_factory.mktemp("canary"))


@pytest.fixture(params=sorted(READER_MODES))
def reader(request: pytest.FixtureRequest, canary: Canary) -> Iterator[TestClient]:
    """A client seeing the canary vault as a reader (every request gets the mode's params)."""
    settings, params = READER_MODES[request.param]
    with leak_client(canary.data_dir, **settings) as client:
        client.params = params
        yield client


def get_routes(app: FastAPI) -> set[str]:
    return {path for path, item in app.openapi()["paths"].items() if "get" in item}


def missing_recipes(app: FastAPI) -> list[str]:
    return sorted(get_routes(app) - set(RECIPES))


# --- route coverage ------------------------------------------------------------------------------


def test_every_get_route_has_a_recipe(tmp_path: Path) -> None:
    app = leak_client(tmp_path).app
    assert isinstance(app, FastAPI)
    assert missing_recipes(app) == [], "add a leak-test recipe in tests/visibility/recipes.py"
    assert sorted(set(RECIPES) - get_routes(app)) == [], "recipes for routes that don't exist"


def test_a_get_route_without_a_recipe_fails_the_suite(tmp_path: Path) -> None:
    app = leak_client(tmp_path).app
    assert isinstance(app, FastAPI)

    @app.get("/api/v1/vaults/{vault_id}/dummy")
    def dummy(vault_id: str) -> dict[str, str]:
        return {"vault": vault_id}

    app.openapi_schema = None
    assert missing_recipes(app) == ["/api/v1/vaults/{vault_id}/dummy"]


# --- leaks ---------------------------------------------------------------------------------------


def _responses(client: TestClient, canary: Canary) -> Iterator[tuple[str, Any, int]]:
    for path, recipe in sorted(RECIPES.items()):
        for call in recipe(canary):
            response = client.get(call.path, params=call.params)
            yield f"{path} {call.path} {call.params}", response, call.status


def test_readers_never_see_canaries(reader: TestClient, canary: Canary) -> None:
    problems: list[str] = []
    calls = 0
    for where, response, status in _responses(reader, canary):
        calls += 1
        if response.status_code != status:
            problems.append(f"{where}: status {response.status_code} (expected {status})")
        # An error may echo the requested id ("No entity <id>."): that tells nothing new.
        echoed = str(response.request.url) if response.status_code >= 400 else ""
        leaked = [n for n in canary.needles if n in response.text and n not in echoed]
        if leaked:
            problems.append(f"{where}: leaked {leaked}")
    assert problems == [], "\n".join(problems)
    assert calls > 100


def test_the_author_sees_every_canary(canary: Canary) -> None:
    """The positive control: the recipes reach every canary, so their absence for readers means
    they were filtered out."""
    with leak_client(canary.data_dir) as author:
        seen = "\n".join(response.text for _, response, _ in _responses(author, canary))
    assert [needle for needle in canary.needles if needle not in seen] == []


# --- counts and shapes ---------------------------------------------------------------------------


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def test_readers_get_filtered_entities(reader: TestClient, canary: Canary) -> None:
    base = f"/api/v1/vaults/{canary.vault}"
    lantern = _get(reader, f"{base}/entities/{canary.public['Lantern']}")
    assert set(lantern["fields"]) == {"long_text", "rich_text"}
    assert lantern["field_visibility"] == {}
    assert [a["alias"] for a in lantern["aliases"]] == ["Lamp"]
    first = lantern["body"]["content"][0]["content"]
    assert first[1] == {"type": "text", "text": "someone"}  # the link to the ghost is gone
    assert len(lantern["body"]["content"]) == 1
    spoiled = _get(reader, f"{base}/entities/{canary.public['Spoiled']}")
    assert spoiled["visibility"] == "spoiler"
    member = _get(reader, f"{base}/entities/{canary.public['Member']}")
    assert member["parent_id"] is None  # its parent is private: shown as a root


def test_reader_counts_exclude_hidden_items(reader: TestClient, canary: Canary) -> None:
    base = f"/api/v1/vaults/{canary.vault}"
    roots = {node["name"]: node for node in _get(reader, f"{base}/tree", limit=500)["items"]}
    assert roots["Shelf"]["child_counts"] == {"misc": 1}
    assert roots["Member"]["parent_id"] is None
    assert not any(name.startswith("CANARY") for name in roots)

    backlinks = _get(reader, f"{base}/entities/{canary.public['Lantern']}/backlinks")["items"]
    assert [b["entity"]["name"] for b in backlinks] == ["Diary"]
    assert backlinks[0]["mentions"] == {"public": 1, "spoiler": 0, "private": 0}
    spoiled = _get(reader, f"{base}/entities/{canary.public['Spoiled']}/backlinks")["items"]
    assert [b["entity"]["name"] for b in spoiled] == ["Mirror"]

    values = _get(reader, f"{base}/entities/field-values", kind="gadget", field="text")
    assert values["items"] == [{"value": "brass", "count": 1}]


def test_the_author_sees_the_hidden_items(canary: Canary) -> None:
    """The same counts in author mode, to show the reader tests filter something."""
    base = f"/api/v1/vaults/{canary.vault}"
    with leak_client(canary.data_dir) as author:
        roots = {node["name"]: node for node in _get(author, f"{base}/tree", limit=500)["items"]}
        assert roots["Shelf"]["child_counts"] == {"misc": 2}
        backlinks = _get(author, f"{base}/entities/{canary.public['Lantern']}/backlinks")
        assert len(backlinks["items"]) == 4
        values = _get(author, f"{base}/entities/field-values", kind="gadget", field="text")
        assert len(values["items"]) == 3
