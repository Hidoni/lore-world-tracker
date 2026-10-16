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
    yield from _as_of(c, path, {"limit": 500})


def _as_of(c: Canary, path: str, params: dict[str, Any]) -> Iterator[Call]:
    """A list at moments (existence filter): before, inside and after private existence, and in
    a hidden timeline (404)."""
    prime = c.public["Prime"]
    for at in ("0", "59", "60", "500"):
        yield Call(path, {**params, "timeline": prime, "at": at})
    for hidden_id in c.hidden_ids:
        yield Call(path, {**params, "timeline": hidden_id, "at": "0"}, status=404)


@recipe(f"{V}/entities/field-values")
def field_values(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/entities/field-values"
    for name in ("text", "secret", "nicknames"):
        yield Call(path, {"kind": "gadget", "field": name, "limit": 100})
        yield Call(path, {"kind": "gadget", "field": name, "q": "CANARY"})


@recipe(f"{V}/entities/{{entity_id}}")
def entity(c: Canary) -> Iterator[Call]:
    yield from _entities(c)
    holder = f"{_v(c)}/entities/{c.public['Fact Holder']}"
    for at in ("0", "41", "60"):
        yield Call(holder, {"at": at})


@recipe(f"{V}/entities/{{entity_id}}/state")
def entity_state(c: Canary) -> Iterator[Call]:
    """As-of state: names anchored to a hidden event, private existence, private fields."""
    prime = c.public["Prime"]
    holder = f"{_v(c)}/entities/{c.public['Fact Holder']}/state"
    for at in ("0", "40", "41", "59", "60", "500"):
        yield Call(holder, {"at": at})
        yield Call(holder, {"at": at, "timeline": prime})
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/entities/{hidden_id}/state", {"at": "0"}, status=404)
        yield Call(holder, {"at": "0", "timeline": hidden_id}, status=404)


@recipe(f"{V}/entities/{{entity_id}}/children")
def children(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/children")
    for entity_id in c.public.values():
        yield Call(
            f"{_v(c)}/entities/{entity_id}/children", {"timeline": c.public["Prime"], "at": "0"}
        )


def _cursors(c: Canary, *, hidden: bool = True) -> Iterator[tuple[dict[str, str], int]]:
    """Time cursors (params, the reader's status): moments in the prime timeline, and (unless
    ``hidden`` is false) every hidden id as the timeline (404)."""
    for at in ("0", "15", "500"):
        yield {"timeline": c.public["Prime"], "at": at}, 200
    if hidden:
        for hidden_id in c.hidden_ids:
            yield {"timeline": hidden_id, "at": "0"}, 404


HIDDEN_CURSOR_PATHS = 3
"""Per-entity routes try every hidden timeline on their first paths only: the timeline is
refused before anything about the entity is read, and trying every hidden id on every entity was
two thirds of the suite's requests (#307)."""


def _as_of_links(c: Canary, paths: Iterator[str]) -> Iterator[Call]:
    for index, path in enumerate(paths):
        for params, status in _cursors(c, hidden=index < HIDDEN_CURSOR_PATHS):
            yield Call(path, params, status=status)


@recipe(f"{V}/entities/{{entity_id}}/links")
def links(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/links")
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/entities/{entity_id}/links", {"include_trashed": "true"})
    yield from _as_of_links(c, (f"{_v(c)}/entities/{e}/links" for e in c.public.values()))


@recipe(f"{V}/entities/{{entity_id}}/facts")
def facts(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/facts")
    holder = c.public["Fact Holder"]
    yield Call(f"{_v(c)}/entities/{holder}/facts", {"field": "core.name"})
    yield Call(f"{_v(c)}/entities/{holder}/facts", {"timeline": c.public["Prime"]})


@recipe(f"{V}/facts")
def caused_facts(c: Canary) -> Iterator[Call]:
    """An event's "changes caused": private facts and facts of private fields stay hidden."""
    path = f"{_v(c)}/facts"
    for name in ("Coronation", "Heist", "Fact Holder"):
        yield Call(path, {"source_event": c.public[name]}, status=200 if name != "Fact Holder"
                   else 404)  # fmt: skip
    for hidden_id in c.hidden_ids:
        yield Call(path, {"source_event": hidden_id}, status=404)


@recipe(f"{V}/entities/{{entity_id}}/backlinks")
def backlinks(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/backlinks")
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/entities/{entity_id}/backlinks", {"include_trashed": "true"})
    yield from _as_of_links(c, (f"{_v(c)}/entities/{e}/backlinks" for e in c.public.values()))


@recipe(f"{V}/entities/{{entity_id}}/unlinked-mentions")
def unlinked_mentions(c: Canary) -> Iterator[Call]:
    yield from _entities(c, "/unlinked-mentions")


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
    yield from _as_of(c, path, {"limit": 500})


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
    paths = (f"{_v(c)}/m/locations/{c.public[name]}/residents" for name in LOCATIONS)
    yield from _as_of_links(c, paths)


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
    paths = (f"{_v(c)}/m/characters/{c.public[name]}/relationships" for name in CHARACTERS)
    yield from _as_of_links(c, paths)


@recipe(f"{V}/m/characters/{{character_id}}/family-tree")
def character_family_tree(c: Canary) -> Iterator[Call]:
    yield from _characters(c, "/family-tree")
    yield from _characters(c, "/family-tree", {"timeline": c.public["Prime"], "up": 5, "down": 5})
    # Lifespans and existence at the cursor: from the facts the request sees.
    yield from _characters(c, "/family-tree", {"timeline": c.public["Prime"], "at": "0"})
    for hidden_id in c.hidden_ids:
        path = f"{_v(c)}/m/characters/{c.public[CHARACTERS[0]]}/family-tree"
        yield Call(path, {"timeline": hidden_id, "at": "0"}, status=404)


@recipe(f"{V}/m/characters/{{character_id}}/life")
def character_life(c: Canary) -> Iterator[Call]:
    yield from _characters(c, "/life", {"timeline": c.public["Prime"]})


GROUPS = ("Empire", "Ministry")


def _groups(c: Canary, suffix: str, params: dict[str, Any] | None = None) -> Iterator[Call]:
    """The route for every visible group (200) and every hidden id (404)."""
    for name in GROUPS:
        yield Call(f"{_v(c)}/m/groups/{c.public[name]}{suffix}", dict(params or {}))
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/groups/{hidden_id}{suffix}", dict(params or {}), status=404)


@recipe(f"{V}/m/groups/{{group_id}}/members")
def group_members(c: Canary) -> Iterator[Call]:
    yield from _groups(c, "/members")
    yield from _groups(c, "/members", {"include_subgroups": "true"})
    yield from _as_of_links(c, (f"{_v(c)}/m/groups/{c.public[n]}/members" for n in GROUPS))


@recipe(f"{V}/m/groups/{{group_id}}/leaders")
def group_leaders(c: Canary) -> Iterator[Call]:
    yield from _groups(c, "/leaders")
    yield from _as_of_links(c, (f"{_v(c)}/m/groups/{c.public[n]}/leaders" for n in GROUPS))


@recipe(f"{V}/m/groups/{{group_id}}/org-chart")
def group_org_chart(c: Canary) -> Iterator[Call]:
    yield from _groups(c, "/org-chart")
    yield from _groups(c, "/org-chart", {"depth": 5, "at": "7", "timeline": c.public["Prime"]})


@recipe(f"{V}/m/groups/{{group_id}}/territory")
def group_territory(c: Canary) -> Iterator[Call]:
    yield from _groups(c, "/territory")
    yield from _as_of_links(c, (f"{_v(c)}/m/groups/{c.public[n]}/territory" for n in GROUPS))


@recipe(f"{V}/m/languages/family-tree")
def language_family_tree(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/m/languages/family-tree"
    yield Call(path, {"limit": 2000})
    for entity_id in [*c.public.values(), *c.hidden_ids]:
        yield Call(path, {"dimension": entity_id})


@recipe(f"{V}/m/graph/graph")
def graph(c: Canary) -> Iterator[Call]:
    """The whole graph (with the time cursor too), every visible entity's neighborhood and
    dimension; hidden centers and timelines are ``404``."""
    path = f"{_v(c)}/m/graph/graph"
    yield Call(path, {"limit": 20000})
    yield Call(path, {"timeline": c.public["Prime"], "at": "7", "depth": 4})
    for entity_id in c.public.values():
        yield Call(path, {"center": entity_id, "depth": 2})
        yield Call(path, {"dimension": entity_id})
    for hidden_id in c.hidden_ids:
        yield Call(path, {"center": hidden_id}, status=404)
        yield Call(path, {"timeline": hidden_id, "at": "0"}, status=404)


@recipe(f"{V}/m/species/descent-tree")
def species_descent_tree(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/m/species/descent-tree"
    yield Call(path, {"limit": 2000})
    for entity_id in [*c.public.values(), *c.hidden_ids]:
        yield Call(path, {"dimension": entity_id})


@recipe(f"{V}/m/species/{{species_id}}/members")
def species_members(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/species/{c.public['Elves']}/members")
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/species/{hidden_id}/members", status=404)
    yield from _as_of_links(c, iter([f"{_v(c)}/m/species/{c.public['Elves']}/members"]))


@recipe(f"{V}/m/languages/{{language_id}}/lexicon")
def lexicon(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/m/languages/{c.public['Varnish']}/lexicon"
    for params in ({}, {"tag": "sea"}, {"sort": "recent"}, {"sort": "headword"}, {"q": "CANARY"}):
        yield Call(path, params)
    for needle in c.strings:
        yield Call(path, {"q": needle})
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/languages/{hidden_id}/lexicon", status=404)


@recipe(f"{V}/m/languages/lexicon/{{entry_id}}")
def lexicon_entry(c: Canary) -> Iterator[Call]:
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/languages/lexicon/{hidden_id}", status=404)


@recipe(f"{V}/m/languages/{{language_id}}/lexicon/export")
def lexicon_export(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/languages/{c.public['Varnish']}/lexicon/export")
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/languages/{hidden_id}/lexicon/export", status=404)


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


# --- branches ------------------------------------------------------------------------------------


@recipe(f"{V}/m/branches/notes/{{entity_id}}/{{timeline_id}}")
def branch_notes(c: Canary) -> Iterator[Call]:
    """A note with a private block and a mention of a private event; hidden entities and
    timelines (404)."""
    divergence = c.public["Divergence"]
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/m/branches/notes/{entity_id}/{divergence}")
    yield Call(f"{_v(c)}/m/branches/notes/{c.public['Wanderer']}/{c.public['Prime']}", status=422)
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/branches/notes/{hidden_id}/{divergence}", status=404)
        yield Call(f"{_v(c)}/m/branches/notes/{c.public['Wanderer']}/{hidden_id}", status=404)


@recipe(f"{V}/m/branches/timelines/{{timeline_id}}/diff")
def branch_diff(c: Canary) -> Iterator[Call]:
    """The branch's own private event isn't listed; hidden timelines (404)."""
    yield Call(f"{_v(c)}/m/branches/timelines/{c.public['Divergence']}/diff")
    yield Call(f"{_v(c)}/m/branches/timelines/{c.public['Divergence']}/diff", {"limit": 1})
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/branches/timelines/{hidden_id}/diff", status=404)


# --- correspondences -----------------------------------------------------------------------------


@recipe(f"{V}/m/correspondences")
def correspondence_list(c: Canary) -> Iterator[Call]:
    """A public correspondence anchored to a private event; a private one; one with a private
    dimension (hidden, and a hidden dimension filter is a 404)."""
    path = f"{_v(c)}/m/correspondences"
    yield Call(path)
    for name in ("Aetheria", "Dreamrealm"):
        yield Call(path, {"dimension": c.public[name]})
    for hidden_id in c.hidden_ids:
        yield Call(path, {"dimension": hidden_id}, status=404)


@recipe(f"{V}/m/correspondences/{{correspondence_id}}")
def correspondence(c: Canary) -> Iterator[Call]:
    yield Call(f"{_v(c)}/m/correspondences/{c.records['Portal']}")
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/correspondences/{hidden_id}", status=404)


@recipe(f"{V}/m/correspondences/map")
def correspondence_map(c: Canary) -> Iterator[Call]:
    """Mapping through the public correspondence only (the private one would map 300)."""
    path = f"{_v(c)}/m/correspondences/map"
    world, dream = c.public["Aetheria"], c.public["Dreamrealm"]
    for t in ("70", "150", "300", "10"):
        yield Call(path, {"from_dimension": world, "to_dimension": dream, "t": t})
    for hidden_id in c.hidden_ids:
        yield Call(path, {"from_dimension": world, "to_dimension": hidden_id, "t": "10"},
                   status=422)  # fmt: skip


# --- worldlines ---------------------------------------------------------------------------------


def _worldline_entities(c: Canary, suffix: str) -> Iterator[Call]:
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/m/worldlines/entities/{entity_id}/{suffix}")
    for hidden_id in c.hidden_ids:
        yield Call(f"{_v(c)}/m/worldlines/entities/{hidden_id}/{suffix}", status=404)


@recipe(f"{V}/m/worldlines/entities/{{entity_id}}/segments")
def worldline_segments(c: Canary) -> Iterator[Call]:
    """Every visible entity's worldline (the Time Traveler's explicit one, implicit ones of others;
    readers see neither the private segment nor the one in the private dimension, nor the
    private events that anchor and document the visible ones)."""
    yield from _worldline_entities(c, "segments")


@recipe(f"{V}/m/worldlines/entities/{{entity_id}}/presence")
def worldline_presence(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/m/worldlines/entities/{c.public['Time Traveler']}/presence"
    world = c.public["Aetheria"]
    for t in ("55", "150", "750", "0"):
        yield Call(path, {"dimension": world, "t": t})
    for hidden_id in c.hidden_ids:
        yield Call(path, {"dimension": hidden_id, "t": "15"}, status=404)
        yield Call(f"{_v(c)}/m/worldlines/entities/{hidden_id}/presence",
                   {"dimension": world, "t": "15"}, status=404)  # fmt: skip


@recipe(f"{V}/m/worldlines/entities/{{entity_id}}/personal-timeline")
def worldline_personal_timeline(c: Canary) -> Iterator[Call]:
    """Ages count only the visible segments, and aren't formatted in the private calendar."""
    yield from _worldline_entities(c, "personal-timeline")


# --- media (#126) ---------------------------------------------------------------------------------


def _media_ids(c: Canary) -> Iterator[tuple[str, int]]:
    yield c.records["Shown media"], 200
    for hidden_id in sorted(c.hidden_ids):
        yield hidden_id, 404


@recipe(f"{V}/m/media/items")
def media_items(c: Canary) -> Iterator[Call]:
    """Only the item a visible context uses; filters by hidden entities find nothing."""
    path = f"{_v(c)}/m/media/items"
    yield Call(path)
    yield Call(path, {"unused": True})
    yield Call(path, {"trashed": True})
    yield Call(path, {"mime": "image/"})
    for entity_id in [*c.public.values(), *sorted(c.hidden_ids)]:
        yield Call(path, {"entity": entity_id})
    for needle in c.strings:
        yield Call(path, {"q": needle})


@recipe(f"{V}/m/media/items/{{media_id}}")
def media_item(c: Canary) -> Iterator[Call]:
    for media_id, status in _media_ids(c):
        yield Call(f"{_v(c)}/m/media/items/{media_id}", status=status)


@recipe(f"{V}/m/media/items/{{media_id}}/file")
def media_file(c: Canary) -> Iterator[Call]:
    for media_id, status in _media_ids(c):
        for size in ("original", "160"):
            yield Call(f"{_v(c)}/m/media/items/{media_id}/file", {"size": size}, status=status)


@recipe(f"{V}/m/media/entities/{{entity_id}}/gallery")
def media_gallery(c: Canary) -> Iterator[Call]:
    """Visible entities' galleries without their private items; hidden entities' are 404."""
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/m/media/entities/{entity_id}/gallery")
    for hidden_id in sorted(c.hidden_ids):
        yield Call(f"{_v(c)}/m/media/entities/{hidden_id}/gallery", status=404)


# --- maps (#128) ----------------------------------------------------------------------------------


@recipe(f"{V}/m/maps/maps")
def maps_list(c: Canary) -> Iterator[Call]:
    path = f"{_v(c)}/m/maps/maps"
    yield Call(path)
    for entity_id in c.public.values():
        yield Call(path, {"location": entity_id})
    for hidden_id in sorted(c.hidden_ids):
        yield Call(path, {"location": hidden_id}, status=404)


@recipe(f"{V}/m/maps/maps/{{map_id}}")
def maps_map(c: Canary) -> Iterator[Call]:
    """The public map without its private, hidden-target and private-timeline pins, at every
    cursor; hidden maps (and hidden timelines) are 404."""
    path = f"{_v(c)}/m/maps/maps/{c.records['Harbor map']}"
    yield Call(path)
    yield Call(path, {"at": "42"})
    yield Call(path, {"at": "100", "timeline": c.public["Prime"]})
    for hidden_id in sorted(c.hidden_ids):
        yield Call(path, {"timeline": hidden_id}, status=404)
        yield Call(f"{_v(c)}/m/maps/maps/{hidden_id}", status=404)


@recipe(f"{V}/m/maps/entities/{{entity_id}}/pins")
def maps_entity_pins(c: Canary) -> Iterator[Call]:
    for entity_id in c.public.values():
        yield Call(f"{_v(c)}/m/maps/entities/{entity_id}/pins")
    for hidden_id in sorted(c.hidden_ids):
        yield Call(f"{_v(c)}/m/maps/entities/{hidden_id}/pins", status=404)
