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


@recipe(f"{V}/settings")
def settings(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/settings")


@recipe(f"{V}/backups")
def backups(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/backups", status=404)  # backups hold private data: author-only


@recipe(f"{V}/backups/{{backup_id}}/download")
def backup_download(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/backups/{c.backup}/download", status=404)


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
    # Groups are field values: private ones must not show.
    yield Call(path, {"kind": "misc", "group_by": "category", "limit": 500})
    for name in ("text", "secret"):
        yield Call(path, {"kind": "gadget", "group_by": name, "limit": 500})


LOCATIONS = ("Varn", "Undercroft", "Market")


def _locations(c: Canary, suffix: str, params: dict[str, Any] | None = None) -> Iterator[Call]:
    """The route for every visible location (200) and every hidden id (404)."""
    for name in LOCATIONS:
        yield Call(f"{_v(c)}/m/locations/{c.public[name]}{suffix}", dict(params or {}))
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/locations/{hidden_id}{suffix}", dict(params or {}), status=404)


@recipe(f"{V}/m/locations/tree")
def location_tree(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/m/locations/tree"
    yield Call(path, {"depth": 6, "limit": 500})
    for name in LOCATIONS:
        yield Call(path, {"root": c.public[name], "depth": 6})
    for entity_id in c.hidden_ids:
        yield Call(path, {"root": entity_id}, status=404)
    for entity_id in [*c.public.values(), *c.hidden_ids]:
        yield Call(path, {"dimension": entity_id, "depth": 6})


@recipe(f"{V}/m/locations/{{location_id}}/events")
def location_events(c: Canary) -> Iterator[Call]:
    timeline = {"timeline": c.public["Prime"]}
    yield from _locations(c, "/events", timeline)
    yield from _locations(c, "/events", {**timeline, "include_descendants": "false"})


@recipe(f"{V}/m/locations/{{location_id}}/residents")
def location_residents(c: Canary) -> Iterator[Call]:
    yield from _locations(c, "/residents")


CHARACTERS = ("Queen Ilsa", "Prince Oren")


def _characters(c: Canary, suffix: str, params: dict[str, Any] | None = None) -> Iterator[Call]:
    """The route for every visible character (200) and every hidden id (404)."""
    for name in CHARACTERS:
        yield Call(f"{_v(c)}/m/characters/{c.public[name]}{suffix}", dict(params or {}))
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/characters/{hidden_id}{suffix}", dict(params or {}), status=404)


@recipe(f"{V}/m/characters/{{character_id}}/relationships")
def character_relationships(c: Canary) -> Iterator[Call]:
    yield from _characters(c, "/relationships")


@recipe(f"{V}/m/characters/{{character_id}}/life")
def character_life(c: Canary) -> Iterator[Call]:
    yield from _characters(c, "/life", {"timeline": c.public["Prime"]})


@recipe(f"{V}/tags")
def tags(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/tags")
    yield Call(f"{_v(c)}/tags", {"q": "CANARY"})  # the hidden tag's name prefix


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


# --- consistency (author-only) -------------------------------------------------------------------


@recipe(f"{V}/consistency/findings")
def findings(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/consistency/findings", status=404)
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/consistency/findings", {"entity": hidden_id}, status=404)


@recipe(f"{V}/consistency/rules")
def consistency_rules(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/consistency/rules", status=404)


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


# --- time ----------------------------------------------------------------------------------------


@recipe(f"{V}/dimensions/{{dimension_id}}/timelines")
def timelines(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/dimensions/{c.public['Aetheria']}/timelines")
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/dimensions/{hidden_id}/timelines", status=404)


@recipe(f"{V}/timelines/{{timeline_id}}/event-tree")
def event_tree(c: Canary) -> Iterator[Call]:
    prime = f"{_v(c)}/timelines/{c.public['Prime']}/event-tree"
    yield Call(prime)
    yield Call(prime, {"limit": 1})
    for name in ("Coronation", "Feast", "Aftermath"):
        yield Call(prime, {"parent": c.public[name]})
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/timelines/{hidden_id}/event-tree", status=404)
        yield Call(prime, {"parent": hidden_id}, status=404)


@recipe(f"{V}/timelines/{{timeline_id}}/causality")
def causality(c: Canary) -> Iterator[Call]:
    url = f"{_v(c)}/timelines/{c.public['Prime']}/causality"
    for name in ("Coronation", "Aftermath"):  # Aftermath: a private cause, by a private link
        yield Call(url, {"event": c.public[name], "depth": 6})
        yield Call(url, {"event": c.public[name], "limit": 1})
    for hidden_id in c.hidden_ids:
        yield Call(url, {"event": hidden_id}, status=404)
        yield Call(
            f"{_v(c)}/timelines/{hidden_id}/causality",
            {"event": c.public["Coronation"]},
            status=404,
        )


@recipe(f"{V}/timelines/{{timeline_id}}/window")
def timeline_window(c: Canary) -> Iterator[Call]:
    url = f"{_v(c)}/timelines/{c.public['Prime']}/window"
    whole = {"from": "0", "to": str(10**12 + 1)}
    yield Call(url, {**whole, "px": 1500})
    yield Call(url, {**whole, "px": 1})  # culled into buckets
    yield Call(url, {**whole, "px": 1500, "parent": c.public["Coronation"]})
    # Coronation's private participants (an event, a private link) are of these kinds.
    yield Call(url, {**whole, "px": 1500, "participant_kind": ["misc", "event"]})
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/timelines/{hidden_id}/window", {**whole, "px": 10}, status=404)
        yield Call(url, {**whole, "px": 10, "parent": hidden_id}, status=404)
        yield Call(url, {**whole, "px": 10, "participant": hidden_id})
        yield Call(url, {**whole, "px": 10, "tag": hidden_id})


@recipe(f"{V}/events/{{event_id}}/occurrences")
def occurrences(c: Canary) -> Iterator[Call]:
    window = {"from": "0", "to": str(10**12 + 1)}
    for name in ("Festival", "Comet"):
        url = f"{_v(c)}/events/{c.public[name]}/occurrences"
        yield Call(url, window)
        yield Call(url, {**window, "limit": 1})  # truncated
    yield Call(f"{_v(c)}/events/{c.public['Coronation']}/occurrences", window, status=409)
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/events/{hidden_id}/occurrences", window, status=404)


@recipe(f"{V}/calendars/presets")
def calendar_presets(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/calendars/presets")


@recipe(f"{V}/m/sample/ping")
def sample_ping(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/sample/ping")


@recipe(f"{V}/m/addon/ping")
def addon_ping(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/addon/ping")
