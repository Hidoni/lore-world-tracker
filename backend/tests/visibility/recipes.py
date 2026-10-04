"""Leak-test recipes (``visibility-and-sharing.md`` §5): for every GET route of the OpenAPI
document, the requests the leak suite sends against the canary vault.

**Adding a GET route? Add a recipe here** (keyed by the OpenAPI path), with realistic parameters:
ids of visible entities (expecting 200), ids of hidden ones (expecting 404 or an empty result),
filters pointing at hidden records, searches for every canary string. A route without a recipe
fails ``test_every_get_route_has_a_recipe``.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from tests.visibility.canary import Canary

V = "/api/v1/vaults/{vault_id}"


@dataclass(frozen=True)
class Call:
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    status: int = 200  # the reader's expected status


type Recipe = Callable[[Canary], Iterator[Call]]

RECIPES: dict[str, Recipe] = {}


def recipe(path: str) -> Callable[[Recipe], Recipe]:
    def register(function: Recipe) -> Recipe:
        assert path not in RECIPES, path
        RECIPES[path] = function
        return function

    return register


def _v(c: Canary) -> str:
    return f"/api/v1/vaults/{c.vault}"


def _entities(c: Canary, suffix: str = "", hidden_status: int = 404) -> Iterator[Call]:
    """The route for every visible entity (200) and every hidden id (404)."""
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/entities/{entity_id}{suffix}")
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/entities/{hidden_id}{suffix}", status=hidden_status)


def _searches(c: Canary) -> Iterator[str]:
    yield from c.strings
    yield from ("lantern", "lamp", "public", "canary", "someone", "near", "chronicle")


# --- system and vaults ---------------------------------------------------------------------------


@recipe("/api/v1/health")
def health(_c: Canary) -> Iterator[Call]:
    yield Call("/api/v1/health")


@recipe("/api/v1/meta")
def meta(_c: Canary) -> Iterator[Call]:
    yield Call("/api/v1/meta")


@recipe("/api/v1/vaults")
def vaults(_c: Canary) -> Iterator[Call]:
    yield Call("/api/v1/vaults")


@recipe(V)
def vault(c: Canary) -> Iterator[Call]:
    yield Call(_v(c))


@recipe(f"{V}/registry")
def registry(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/registry")


@recipe(f"{V}/link-types")
def link_types(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/link-types")


# --- entities ------------------------------------------------------------------------------------


@recipe(f"{V}/entities")
def entity_list(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/entities"
    yield Call(path, {"limit": 500})
    yield Call(path, {"limit": 500, "include_trashed": "true"})
    for sort in ("name", "-updated", "sort_key"):
        yield Call(path, {"limit": 500, "sort": sort})
    for kind in ("gadget", "misc", "dimension", "timeline", "creature"):
        yield Call(path, {"kind": kind, "limit": 500})
    for hidden_id in c.hidden_ids:
        for name in ("parent", "dimension"):
            yield Call(path, {name: hidden_id})
    for tag_id in c.tags.values():
        yield Call(path, {"tag": tag_id})
    for needle in [*c.strings, "C", "L"]:
        yield Call(path, {"q": needle})


@recipe(f"{V}/entities/field-values")
def field_values(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/entities/field-values"
    for name in ("text", "secret", "nicknames"):
        yield Call(path, {"kind": "gadget", "field": name, "limit": 100})
        yield Call(path, {"kind": "gadget", "field": name, "q": "CANARY"})


@recipe(f"{V}/entities/{{entity_id}}")
def entity(c: Canary) -> Iterator[Call]:
    yield from _entities(c)


@recipe(f"{V}/entities/{{entity_id}}/children")
def children(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/children")


@recipe(f"{V}/entities/{{entity_id}}/links")
def links(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/links")
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/entities/{entity_id}/links", {"include_trashed": "true"})


@recipe(f"{V}/entities/{{entity_id}}/backlinks")
def backlinks(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/backlinks")
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/entities/{entity_id}/backlinks", {"include_trashed": "true"})


@recipe(f"{V}/tree")
def tree(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/tree"
    yield Call(path, {"limit": 500})
    for entity_id in [*c.public.values(), *c.hidden_ids]:
        yield Call(path, {"parent": entity_id})
        yield Call(path, {"dimension": entity_id})


@recipe(f"{V}/trash")
def trash(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/trash", status=404)


# --- history -------------------------------------------------------------------------------------


@recipe(f"{V}/changes")
def changes(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/changes", status=404)


@recipe(f"{V}/changes/{{changeset_id}}")
def changeset(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/changes/{c.changeset}", status=404)


@recipe(f"{V}/entities/{{entity_id}}/history")
def entity_history(c: Canary) -> Iterator[Call]:
    for entity_id in [*c.public.values(), *c.hidden_ids]:
        yield Call(f"{_v(c)}/entities/{entity_id}/history", status=404)


# --- search --------------------------------------------------------------------------------------


@recipe(f"{V}/search")
def search(c: Canary) -> Iterator[Call]:
    for q in _searches(c):
        yield Call(f"{_v(c)}/search", {"q": q, "limit": 500})
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/search", {"q": "lantern", "dimension": hidden_id})


@recipe(f"{V}/search/quick")
def quick(c: Canary) -> Iterator[Call]:
    for q in _searches(c):
        yield Call(f"{_v(c)}/search/quick", {"q": q})


# --- module routes (test modules) ----------------------------------------------------------------


@recipe(f"{V}/m/sample/ping")
def sample_ping(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/sample/ping")


@recipe(f"{V}/m/addon/ping")
def addon_ping(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/addon/ping")
