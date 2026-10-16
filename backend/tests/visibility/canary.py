"""The canary vault (``visibility-and-sharing.md`` §5): private content of every type that exists
so far, each carrying a unique ``CANARY-<n>`` string, plus the ids of everything readers must
never see. Built through the API (services), in author mode.

Extend it whenever a new kind of private content appears (``#139`` completes it for M12): add the
content, its canary string, and the ids that must stay hidden.
"""

import copy
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from lore.app import create_app
from lore.config import Settings
from lore.core.modules import ModuleSpec
from lore.modules import ALL_MODULES
from tests.conftest import local_client
from tests.entity_api import HEADERS, YEARS, LinkApi
from tests.entity_modules import ENTITY_MODULES
from tests.sample_modules import ADDON, BASE, SAMPLE

# The real modules plus test modules with kinds, fields and module routes to cover.
LEAK_MODULES: tuple[ModuleSpec, ...] = tuple(
    {m.id: m for m in (*ALL_MODULES, *ENTITY_MODULES, BASE, SAMPLE, ADDON)}.values()
)
POINT = {"anchor": {"kind": "absolute", "t": "42"}, "precision": "base", "approximate": False}


def leak_client(data_dir: Path, **settings: Any) -> TestClient:
    app = create_app(Settings(data_dir=data_dir, **settings), modules=LEAK_MODULES)
    return local_client(app, headers=HEADERS)


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


def private(*content: Any) -> dict[str, Any]:
    return {"type": "visibilityBlock", "attrs": {"level": "private"}, "content": list(content)}


@dataclass
class Canary:
    data_dir: Path
    vault: str
    strings: list[str] = field(default_factory=list)
    hidden_ids: set[str] = field(default_factory=set)  # never in a reader response
    public: dict[str, str] = field(default_factory=dict)  # name -> id of visible entities
    tags: dict[str, str] = field(default_factory=dict)  # name -> id
    records: dict[str, str] = field(default_factory=dict)  # name -> id of visible non-entities
    changeset: str = ""
    backup: str = ""

    @property
    def needles(self) -> Iterator[str]:
        yield from self.strings
        yield from self.hidden_ids


class _Builder:
    def __init__(self, api: LinkApi, canary: Canary) -> None:
        self.api = api
        self.canary = canary

    def canary_string(self) -> str:
        value = f"CANARY-{len(self.canary.strings) + 1}"
        self.canary.strings.append(value)
        return value

    def public(self, kind: str, name: str, **body: Any) -> dict[str, Any]:
        entity = self.api.make(kind, name, **body)
        self.canary.public[name] = entity["id"]
        return entity

    def hidden(self, kind: str, **body: Any) -> dict[str, Any]:
        """An entity readers must not see; its name is a canary string."""
        entity = self.api.make(kind, f"{self.canary_string()} {kind}", **body)
        self.canary.hidden_ids.add(entity["id"])
        return entity

    def hidden_link(self, *args: Any, **body: Any) -> dict[str, Any]:
        link = self.api.made_link(*args, **body)
        self.canary.hidden_ids.add(link["id"])
        return link


def build_canary_vault(data_dir: Path) -> Canary:
    with leak_client(data_dir) as client:
        api = LinkApi(client)
        canary = Canary(data_dir, api.vault)
        b = _Builder(api, canary)

        world = b.public("dimension", "Aetheria")
        home = {"dimension_id": world["id"]}
        canary.public["Prime"] = world["ext"]["prime_timeline_id"]
        # A private calendar that is the world's default (its id must not leak through the
        # dimension's ext), and a public one.
        secret_calendar = copy.deepcopy(YEARS)
        secret_calendar["levels"][1]["label"] = b.canary_string()
        secret = b.hidden(
            "calendar", visibility="private", ext={"definition": secret_calendar}, **home
        )
        assert api.get(world["id"]).json()["ext"]["default_calendar_id"] == secret["id"]
        b.public("calendar", "Common Reckoning", ext={"definition": YEARS}, **home)

        # Private entities: by visibility, and effectively (home dimension private, trashed).
        ghost = b.hidden(
            "gadget",
            visibility="private",
            summary=b.canary_string(),
            fields={"text": b.canary_string()},
            tags=[b.canary_string()],
            aliases=[{"alias": b.canary_string()}],
            **home,
        )
        realm = b.hidden("dimension", visibility="private")
        b.hidden("gadget", dimension_id=realm["id"], summary=b.canary_string())
        discarded = b.hidden("gadget", summary=b.canary_string(), **home)
        assert api.delete(discarded["id"]).status_code == 200
        # A private timeline: the prime of the private dimension (it copies its visibility).
        branch = api.get(realm["ext"]["prime_timeline_id"]).json()
        assert branch["visibility"] == "private"
        canary.hidden_ids.add(branch["id"])

        # A public entity with private parts of every kind.
        lantern = b.public(
            "gadget",
            "Lantern",
            aliases=[
                {"alias": "Lamp"},
                {"alias": b.canary_string(), "visibility": "private"},
            ],
            fields={
                "secret": b.canary_string(),  # private by the field's default
                "text": b.canary_string(),  # private by override
                "long_text": "a public description",
                "rich_text": doc(p(text("public lore")), private(p(text(b.canary_string())))),
            },
            field_visibility={"text": "private"},
            body=doc(
                p(text("A lantern seen by "), text("someone", mention(ghost["id"]))),
                private(p(text(b.canary_string()))),
            ),
            **home,
        )
        alias_ids = [a["id"] for a in api.get(lantern["id"]).json()["aliases"]]
        canary.hidden_ids.add(alias_ids[1])
        spoiled = b.public("gadget", "Spoiled", visibility="spoiler", **home)
        # Time points anchored in the private calendar: readers get the moment, not the calendar.
        secret_year = {
            "anchor": {"kind": "calendar", "calendar_id": secret["id"], "fields": {"year": "3"}},
            "precision": "year",
            "approximate": True,
        }
        compass = b.public(
            "gadget", "Compass", fields={"text": "brass", "time_point": secret_year}, **home
        )

        # Links: private ones, links to hidden entities, links in a private timeline.
        b.hidden_link("core.related", lantern, spoiled, visibility="private",
                      role=b.canary_string(), data={"note": b.canary_string()})  # fmt: skip
        b.hidden_link("core.related", lantern, ghost, role="seen with")
        b.hidden_link(
            "core.related",
            lantern,
            spoiled,
            role=b.canary_string(),
            timeline_id=branch["id"],
            valid_from=POINT,
        )
        mirror = b.public("gadget", "Mirror", **home)
        api.made_link("core.related", spoiled, mirror)
        api.made_link(
            "core.related",
            compass,
            mirror,
            timeline_id=canary.public["Prime"],
            valid_from=secret_year,
        )

        # Mentions: from a private entity, and only inside a private block.
        api.patch(ghost, body=doc(p(text("near the "), text("lantern", mention(lantern["id"])))))
        b.public(
            "gadget",
            "Chronicle",
            body=doc(private(p(text(b.canary_string(), mention(lantern["id"]))))),
            **home,
        )
        b.public(
            "gadget",
            "Diary",
            body=doc(p(text("the "), text("lantern", mention(lantern["id"])))),
            **home,
        )

        # Hierarchy: a private parent with a public child, a public parent with a private child.
        cabal = b.hidden("misc", visibility="private", **home)
        b.public("misc", "Member", parent_id=cabal["id"], **home)
        # A misc category readers may not see (the sidebar groups by it: `/tree?group_by=`).
        shelf = b.public(
            "misc",
            "Shelf",
            fields={"category": b.canary_string()},
            field_visibility={"category": "private"},
            **home,
        )
        b.public("misc", "Book", parent_id=shelf["id"], **home)
        b.hidden("misc", visibility="private", parent_id=shelf["id"], **home)

        # A module kind whose rich-text field has a private block.
        b.public(
            "creature",
            "Wyrm",
            fields={"lore": doc(p(text("it sleeps")), private(p(text(b.canary_string()))))},
            **home,
        )

        _events(b, home, secret, secret_year, realm)
        _module_content(b, home)

        canary.tags = {t["name"]: t["id"] for t in api.get(ghost["id"]).json()["tags"]}
        canary.hidden_ids.update(canary.tags.values())
        changes = client.get(f"{api.base}/changes", params={"limit": 1}).json()
        canary.changeset = changes["items"][0]["id"]
        backup = client.post(f"{api.base}/backups", json={"include_media": False})
        assert backup.status_code == 201, backup.json()
        canary.backup = backup.json()["id"]
        return canary


def _events(
    b: _Builder,
    home: dict[str, Any],
    secret: dict[str, Any],
    secret_year: dict[str, Any],
    realm: dict[str, Any],
) -> None:
    """Events: dated in the private default calendar (readers get moments and absolute
    displays), a private parent with a public sub-event (a root for readers), a private
    sub-event, an anchor on a private event, a private cause, participants (one public, one by a
    private link, one private entity), and an event in the private dimension."""
    secret_span = {
        "kind": "duration",
        "duration": {
            "kind": "calendar",
            "calendar_id": secret["id"],
            "amounts": {"year": "1"},
            "sign": 1,
        },
    }
    coronation = b.public(
        "event", "Coronation", ext={"start": secret_year, "end": secret_span}, **home
    )
    b.public("event", "Feast", parent_id=coronation["id"], **home)
    herald = b.public("misc", "Herald", **home)
    b.api.made_link("core.participant", coronation, herald, role="herald")
    b.hidden_link("core.participant", coronation, herald, visibility="private")
    b.hidden("event", visibility="private", parent_id=coronation["id"], **home)
    plot = b.hidden("event", visibility="private", **home)
    after_plot = {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": plot["id"], "slot": "start"},
            "offset": {"kind": "base", "units": "86400"},
        },
        "precision": "base",
    }
    b.api.made_link("core.participant", coronation, plot)  # a private participant
    aftermath = b.public(
        "event", "Aftermath", parent_id=plot["id"], ext={"start": after_plot}, **home
    )
    b.hidden_link("core.causes", plot, aftermath, data={"description": b.canary_string()})
    _series(b, home, secret, plot)
    b.hidden("calendar", ext={"definition": YEARS}, dimension_id=realm["id"])
    b.hidden("event", dimension_id=realm["id"])
    _correspondences(b, home, realm)
    _worldlines(b, home, realm)


def _facts(b: _Builder, home: dict[str, Any]) -> None:
    """Facts: a private fact, a fact of a private field, a name over time anchored to a hidden
    event and caused by it, a private rich-text value and private existence (time-model.md
    §10.2-§10.4)."""
    holder = b.public("gadget", "Fact Holder", **home)
    timeline = b.canary.public["Prime"]
    start = {"start": {"anchor": {"kind": "absolute", "t": "40"}, "precision": "base"}}
    cause = b.hidden("event", visibility="private", ext=start, **home)

    def fact(**body: Any) -> dict[str, Any]:
        response = b.api.client.post(
            f"{b.api.base}/entities/{holder['id']}/facts", json={"timeline_id": timeline, **body}
        )
        assert response.status_code == 201, response.json()
        made: dict[str, Any] = response.json()["fact"]
        return made

    hidden = fact(field_key="core.name", value=b.canary_string(), visibility="private")
    b.canary.hidden_ids.add(hidden["id"])
    secret_field = fact(field_key="hidden_rank", value="9")
    b.canary.hidden_ids.add(secret_field["id"])
    ref = {"type": "event", "id": cause["id"], "slot": "start"}
    fact(
        field_key="core.name",
        value="Renamed",
        source_event_id=cause["id"],
        valid_from={
            "anchor": {"kind": "relative", "ref": ref, "offset": {"kind": "base", "units": "1"}},
            "precision": "base",
        },
    )
    lore = {"type": "doc", "content": [{"type": "paragraph",
            "content": [{"type": "text", "text": b.canary_string()}]}]}  # fmt: skip
    private_lore = fact(field_key="lore", value=lore, visibility="private")
    b.canary.hidden_ids.add(private_lore["id"])
    # Existence only the author knows of (as-of state, §10.4-§10.5): readers see "unknown".
    until = {"anchor": {"kind": "absolute", "t": "60"}, "precision": "base"}
    private_existence = fact(field_key="core.exists", valid_to=until, visibility="private")
    b.canary.hidden_ids.add(private_existence["id"])
    # A public event that caused private changes: its "changes caused" hides them.
    coronation = b.public("event", "Coronation", ext=start, **home)
    caused = fact(field_key="rank", value="4", source_event_id=coronation["id"],
                  visibility="private", note=b.canary_string())  # fmt: skip
    b.canary.hidden_ids.add(caused["id"])
    hidden_rank = fact(field_key="hidden_rank", value="5", source_event_id=coronation["id"])
    b.canary.hidden_ids.add(hidden_rank["id"])


def _module_content(b: _Builder, home: dict[str, Any]) -> None:
    """Private content of the real modules' kinds and links, and facts."""
    _facts(b, home)
    _temporal_links(b, home)
    _locations(b, home)
    _characters(b, home)
    _groups(b, home)
    _languages(b, home)
    _species(b, home)
    _branches(b, home)
    _media(b, home)
    _maps(b, home)
    _custom_fields(b, home)


def _png(color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(out, "PNG")
    return out.getvalue()


def _media(b: _Builder, home: dict[str, Any]) -> None:
    """One item a reader sees (an image in a public body) and four they don't: an image only in
    a private block, the cover of a private entity, a private gallery item and an unused upload,
    each with canary text in its name, alt or caption."""
    api = b.api

    def upload(color: str, filename: str, alt: str = "") -> str:
        response = api.client.post(
            f"{api.base}/m/media/items", files={"file": (filename, _png(color))},
            data={"alt": alt}, headers=HEADERS,
        )  # fmt: skip
        assert response.status_code == 201, response.json()
        media_id: str = response.json()["item"]["id"]
        return media_id

    shown = upload("red", "lamp.png", alt="the lantern at night")
    b.canary.records["Shown media"] = shown
    secret = upload("black", f"{b.canary_string()}.png", alt=b.canary_string())
    cover = upload("blue", "cover.png", alt=b.canary_string())
    in_gallery = upload("green", "plate.png", alt=b.canary_string())
    unused = upload("white", f"{b.canary_string()}.png")
    b.canary.hidden_ids |= {secret, cover, in_gallery, unused}

    def image(media_id: str) -> dict[str, Any]:
        return {"type": "image", "attrs": {"mediaId": media_id, "alt": "", "caption": ""}}

    album = b.public("gadget", "Album", body=doc(image(shown), private(image(secret))), **home)
    b.hidden("gadget", visibility="private", cover_media_id=cover, **home)
    added = api.client.post(
        f"{api.base}/m/media/entities/{album['id']}/gallery",
        json={"media_id": in_gallery, "caption": b.canary_string(), "visibility": "private"},
        headers=HEADERS,
    )
    assert added.status_code == 201, added.json()
    b.canary.hidden_ids.add(added.json()["id"])


def _maps(b: _Builder, home: dict[str, Any]) -> None:
    """A public map of a public location with a public pin, and what readers must not see: a
    private map, a private label pin, a pin of a private location and a pin in a private branch
    of the prime timeline."""
    api = b.api
    image = api.client.post(
        f"{api.base}/m/media/items", files={"file": ("chart.png", _png("gray"))}, headers=HEADERS
    ).json()["item"]["id"]
    harbor = b.public("location", "Harbor", **home)
    pier = b.public("location", "Pier", parent_id=harbor["id"], **home)
    base = f"{api.base}/m/maps"

    def made(path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = api.client.post(f"{base}/{path}", json=body, headers=HEADERS)
        assert response.status_code == 201, response.json()
        found: dict[str, Any] = response.json()
        return found

    chart = made("maps", {"location_id": harbor["id"], "media_id": image, "name": "Harbor"})["map"]
    b.canary.records["Harbor map"] = chart["id"]
    secret = {"location_id": harbor["id"], "media_id": image, "name": b.canary_string(),
              "visibility": "private"}  # fmt: skip
    secret_map = made("maps", secret)["map"]
    b.canary.hidden_ids.add(secret_map["id"])
    pins = f"maps/{chart['id']}/pins"
    made(pins, {"target_entity_id": pier["id"], "x": 1, "y": 1})
    hidden = [
        made(pins, {"label": b.canary_string(), "x": 2, "y": 1, "visibility": "private"}),
        made(pins, {"target_entity_id": b.hidden("location", visibility="private", **home)["id"],
                    "label": b.canary_string(), "x": 3, "y": 1}),
    ]  # fmt: skip
    branch = api.client.post(f"{api.base}/m/branches/timelines", json={
        "parent_timeline_id": b.canary.public["Prime"], "name": b.canary_string(),
        "branch_point": POINT, "visibility": "private"}, headers=HEADERS)  # fmt: skip
    assert branch.status_code == 201, branch.json()
    b.canary.hidden_ids.add(branch.json()["entity"]["id"])
    hidden.append(made(pins, {"label": b.canary_string(), "x": 4, "y": 1,
                              "timeline_id": branch.json()["entity"]["id"],
                              "valid_from": POINT}))  # fmt: skip
    b.canary.hidden_ids |= {pin["pin"]["id"] for pin in hidden}


def _branches(b: _Builder, home: dict[str, Any]) -> None:
    """A public branch with a private sub-branch, a private event and private facts of its own
    (the branch diff) and a note on a public entity with a private block and a mention of a
    private event."""
    api = b.api

    def branch(parent: str, name: str, **body: Any) -> dict[str, Any]:
        response = api.client.post(f"{api.base}/m/branches/timelines", json={
            "parent_timeline_id": parent, "branch_point": POINT, "name": name, **body})  # fmt: skip
        assert response.status_code == 201, response.json()
        entity: dict[str, Any] = response.json()["entity"]
        return entity

    divergence = branch(b.canary.public["Prime"], "Divergence")
    b.canary.public["Divergence"] = divergence["id"]
    hidden = branch(divergence["id"], f"{b.canary_string()} branch", visibility="private")
    b.canary.hidden_ids.add(hidden["id"])
    later = {"anchor": {"kind": "absolute", "t": "50"}, "precision": "base"}
    plot = b.hidden("event", visibility="private",
                    ext={"start": later, "timeline_id": divergence["id"]}, **home)  # fmt: skip
    holder = b.canary.public["Fact Holder"]
    for body in (
        {"field_key": "hidden_rank", "value": "7"},
        {"field_key": "core.name", "value": b.canary_string(), "visibility": "private"},
    ):
        response = api.client.post(f"{api.base}/entities/{holder}/facts",
                                   json={"timeline_id": divergence["id"], "valid_from": later,
                                         **body})  # fmt: skip
        assert response.status_code == 201, response.json()
        b.canary.hidden_ids.add(response.json()["fact"]["id"])
    wanderer = b.public("gadget", "Wanderer", **home)
    note = doc(
        p(text("public branch note, "), text("someone", mention(plot["id"]))),
        private(p(text(b.canary_string()))),
    )
    response = api.client.put(
        f"{api.base}/m/branches/notes/{wanderer['id']}/{divergence['id']}",
        json={"body": note, "revision": 0},
    )
    assert response.status_code == 200, response.json()


def _correspondences(b: _Builder, home: dict[str, Any], realm: dict[str, Any]) -> None:
    """A public correspondence to a public Dreamrealm whose sync point is anchored to a private
    event (readers get its moment), a private one, and one with the private dimension."""
    api = b.api
    dream = b.public("dimension", "Dreamrealm")
    api.calendar(dream["id"])
    secret_start = {"anchor": {"kind": "absolute", "t": "70"}, "precision": "base"}
    opening = b.hidden("event", visibility="private", ext={"start": secret_start}, **home)
    ref = {"type": "event", "id": opening["id"], "slot": "start"}
    offset = {"kind": "base", "units": "0"}
    anchored = {"anchor": {"kind": "relative", "ref": ref, "offset": offset}, "precision": "base"}

    def made(a: str, b_: str, name: str, points: list[Any], **body: Any) -> dict[str, Any]:
        response = api.client.post(f"{api.base}/m/correspondences", json={
            "dimension_a_id": a, "dimension_b_id": b_, "name": name,
            "points": [{"a": pa, "b": pb} for pa, pb in points], **body})  # fmt: skip
        assert response.status_code == 201, response.json()
        found: dict[str, Any] = response.json()["correspondence"]
        return found

    def at(t: int) -> dict[str, Any]:
        return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}

    world = home["dimension_id"]
    portal = made(world, dream["id"], "Portal", [(anchored, at(1000)), (at(200), at(3000))])
    b.canary.records["Portal"] = portal["id"]
    secret = made(world, dream["id"], b.canary_string(), [(at(300), at(5000))],
                  visibility="private", note=b.canary_string())  # fmt: skip
    b.canary.hidden_ids.add(secret["id"])
    realm_link = made(world, realm["id"], b.canary_string(), [(at(10), at(10))])
    b.canary.hidden_ids.add(realm_link["id"])


def _worldlines(b: _Builder, home: dict[str, Any], realm: dict[str, Any]) -> None:
    """A traveler with a public segment ending at (and departing with) a private event, a
    private segment, a segment in the private dimension and a public one arrived at by a private
    event; a public and a private participation. The world's default calendar is private, so
    readers get no formatted ages."""
    api = b.api

    def at(t: int) -> dict[str, Any]:
        return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}

    secret = b.hidden("event", visibility="private", ext={"start": at(500)}, **home)
    ref = {"type": "event", "id": secret["id"], "slot": "start"}
    offset = {"kind": "base", "units": "0"}
    anchored = {"anchor": {"kind": "relative", "ref": ref, "offset": offset}, "precision": "base"}
    traveler = b.public("character", "Time Traveler", **home)
    prime = b.canary.public["Prime"]

    def segment(start: Any, end: Any, **body: Any) -> dict[str, Any]:
        body.setdefault("dimension_id", home["dimension_id"])
        body.setdefault("timeline_id", prime)
        return {"start": start, "end": end, **body}

    response = api.client.put(
        f"{api.base}/m/worldlines/entities/{traveler['id']}/segments",
        json={"segments": [
            segment(at(100), anchored, departure_event_id=secret["id"], note="The road"),
            segment(at(50), at(60), visibility="private", note=b.canary_string()),
            segment(at(10), at(20), dimension_id=realm["id"],
                    timeline_id=realm["ext"]["prime_timeline_id"], note=b.canary_string()),
            segment(at(700), at(800), arrival_event_id=secret["id"]),
        ]},
    )  # fmt: skip
    assert response.status_code == 200, response.json()
    road, hidden, elsewhere, home_again = response.json()["worldline"]["segments"]
    b.canary.records["Road"] = road["id"]
    b.canary.records["Home again"] = home_again["id"]
    b.canary.hidden_ids |= {hidden["id"], elsewhere["id"]}
    ball = b.public("event", "Ball", ext={"start": at(750)}, **home)
    api.made_link("core.participant", ball, traveler, role="guest")
    api.made_link("core.participant", secret, traveler, role=b.canary_string())


def _temporal_links(b: _Builder, home: dict[str, Any]) -> None:
    """A private temporal link between public entities in the prime timeline (as-of reads must
    not show it, time-model.md §10.3)."""
    sundial = b.public("gadget", "Sundial", **home)
    hourglass = b.public("gadget", "Hourglass", **home)
    b.hidden_link("core.related", sundial, hourglass, visibility="private",
                  role=b.canary_string(), timeline_id=b.canary.public["Prime"],
                  valid_from=POINT)  # fmt: skip


def _locations(b: _Builder, home: dict[str, Any]) -> None:
    """Locations: a private location inside a public city (its contents, events and residents
    stay hidden), events there, a private event at the city, a private site link, and residents
    by a private link or private themselves."""
    varn = b.public("location", "Varn", fields={"location_type": "city"}, **home)
    vault = b.hidden("location", visibility="private", parent_id=varn["id"], **home)
    b.public("location", "Undercroft", parent_id=vault["id"], **home)  # a root for readers
    b.public("location", "Market", parent_id=varn["id"], **home)
    start = {"start": {"anchor": {"kind": "absolute", "t": "5"}, "precision": "base"}}
    heist = b.public("event", "Heist", ext=start, **home)
    b.api.made_link("locations.event_site", heist, vault)  # its only site is hidden
    riot = b.public("event", "Riot", ext=start, **home)
    b.hidden_link("locations.event_site", riot, varn, visibility="private")
    secret_meeting = b.hidden("event", visibility="private", ext=start, **home)
    b.api.made_link("locations.event_site", secret_meeting, varn)
    lantern = b.public("gadget", "Street lamp", **home)
    b.hidden_link("locations.resides_in", lantern, varn, visibility="private")
    spy = b.hidden("gadget", visibility="private", **home)
    b.api.made_link("locations.resides_in", spy, varn, data={"kind": "base"})


def _characters(b: _Builder, home: dict[str, Any]) -> None:
    """Characters: a private secret (by the field's default), a private relative, a relationship
    by a private link, a private event the queen takes part in and a private participant link."""
    queen = b.public("character", "Queen Ilsa", fields={"secret": b.canary_string()}, **home)
    heir = b.public("character", "Prince Oren", **home)
    b.api.made_link("characters.parent_of", queen, heir, data={"kind": "biological"})
    lover = b.hidden("character", visibility="private", **home)
    b.api.made_link("characters.romance", queen, lover)
    b.hidden_link("characters.rival_of", queen, heir, visibility="private")
    start = {"start": {"anchor": {"kind": "absolute", "t": "7"}, "precision": "base"}}
    coronation = b.public("event", "Crowning", ext=start, **home)
    b.api.made_link("core.participant", coronation, queen, role="queen")
    tryst = b.hidden("event", visibility="private", ext=start, **home)
    b.api.made_link("core.participant", tryst, queen)
    duel = b.public("event", "Duel", ext=start, **home)
    b.hidden_link("core.participant", duel, heir, visibility="private", role=b.canary_string())
    # The family tree: a private child and a marriage by a private link.
    bastard = b.hidden("character", visibility="private", **home)
    b.api.made_link("characters.parent_of", queen, bastard)
    b.hidden_link("characters.spouse_of", queen, heir, visibility="private")


def _groups(b: _Builder, home: dict[str, Any]) -> None:
    """Groups: a private sub-group with a member, a member by a private link, a private member,
    a private leader and a hidden territory."""
    empire = b.public("group", "Empire", **home)
    b.public("group", "Ministry", parent_id=empire["id"], **home)
    cabal = b.hidden("group", visibility="private", parent_id=empire["id"], **home)
    agent = b.public("character", "Agent", **home)
    b.api.made_link("groups.member_of", agent, cabal, data={"rank": "adept"})
    b.hidden_link(
        "groups.member_of", agent, empire, visibility="private", data={"title": b.canary_string()}
    )
    spy = b.hidden("character", visibility="private", **home)
    b.api.made_link("groups.member_of", spy, empire)
    b.api.made_link("groups.led_by", empire, spy)
    vault = b.hidden("location", visibility="private", **home)
    b.api.made_link("groups.controls", empire, vault)
    # The org chart: a part by a private link.
    guild = b.public("group", "Guild", **home)
    b.hidden_link("groups.part_of", guild, empire, visibility="private")


def _languages(b: _Builder, home: dict[str, Any]) -> None:
    """Languages: a private ancestor, a private dialect, and a descent by a private link."""
    varnish = b.public("language", "Varnish", **home)
    trade = b.public("language", "Trade Cant", **home)
    secret = b.hidden("language", visibility="private", **home)
    b.api.made_link("languages.descended_from", varnish, secret)
    b.hidden("language", visibility="private", parent_id=varnish["id"], **home)
    b.hidden_link("languages.borrowed_from", trade, varnish, visibility="private")
    # The lexicon: a private entry, an entry of the private language, a public one.
    lexicon = f"{b.api.base}/m/languages/{varnish['id']}/lexicon"
    for body in (
        {"headword": "thalass", "definitions": [{"gloss": "the sea"}], "tags": ["sea"]},
        {"headword": b.canary_string(), "visibility": "private", "tags": ["sea"],
         "definitions": [{"gloss": b.canary_string()}]},
    ):  # fmt: skip
        made = b.api.client.post(lexicon, json=body)
        assert made.status_code == 201, made.json()
        if body.get("visibility") == "private":
            b.canary.hidden_ids.add(made.json()["entry"]["id"])
    hidden = b.api.client.post(
        f"{b.api.base}/m/languages/{secret['id']}/lexicon", json={"headword": b.canary_string()}
    )
    assert hidden.status_code == 201, hidden.json()
    b.canary.hidden_ids.add(hidden.json()["entry"]["id"])
    # A page referring to a word of the private language (readers lose the reference).
    ref = {
        "type": "lexiconRef",
        "attrs": {"entryId": hidden.json()["entry"]["id"], "languageId": secret["id"]},
    }
    b.public("gadget", "Glossary", body=doc(p(text("The word "), ref)), **home)


def _species(b: _Builder, home: dict[str, Any]) -> None:
    """Species: a private ancestor, a private subspecies, a private member and a member by a
    private link."""
    elves = b.public("species", "Elves", **home)
    elder = b.hidden("species", visibility="private", **home)
    b.api.made_link("species.descended_from", elves, elder)
    b.hidden("species", visibility="private", parent_id=elves["id"], **home)
    changeling = b.hidden("character", visibility="private", **home)
    b.api.made_link("species.is_a", changeling, elves)
    hermit = b.public("character", "Hermit", **home)
    b.hidden_link("species.is_a", hermit, elves, visibility="private")


def _series(
    b: _Builder, home: dict[str, Any], secret: dict[str, Any], plot: dict[str, Any]
) -> None:
    """Recurring events: a yearly rule in the private calendar (readers get no rule), a comet
    whose exclusion is anchored to a private event (readers get its moment) with a private and
    a public materialized occurrence, and a private series (its occurrences and bands never reach
    readers)."""
    start = {"anchor": {"kind": "absolute", "t": "0"}, "precision": "base"}
    at_plot = {
        "anchor": {
            "kind": "relative",
            "ref": {"type": "event", "id": plot["id"], "slot": "start"},
            "offset": {"kind": "base", "units": "0"},
        },
        "precision": "base",
    }
    yearly = {"kind": "calendar", "calendar_id": secret["id"], "freq": {"level": "year"},
              "limit": {"kind": "never"}}  # fmt: skip
    b.public("event", "Festival", ext={"start": start, "recurrence": yearly}, **home)
    comet = {
        "kind": "interval",
        "every": "1000",
        "limit": {"kind": "count", "count": "50"},
        "exclusions": [{"from": at_plot, "to": at_plot, "note": "Hidden by the plot"}],
    }
    comet_event = b.public("event", "Comet", ext={"start": start, "recurrence": comet}, **home)
    # A private materialized occurrence (moved): readers get the computed occurrence instead.
    moved = {"series_id": comet_event["id"], "occurrence_key": "3", "start": at_plot}
    b.hidden("event", visibility="private", ext=moved, **home)
    referenced = {"series_id": comet_event["id"], "occurrence_key": "4"}
    b.public("event", "Comet return", ext=referenced, **home)
    hidden = {"kind": "interval", "every": "86400", "limit": {"kind": "never"}}
    b.hidden("event", visibility="private", ext={"start": start, "recurrence": hidden}, **home)


def _custom_fields(b: _Builder, home: dict[str, Any]) -> None:
    """A custom field private by default (its value must not reach readers through fields,
    facts or search) on a public entity, and a public one with a private override."""
    api = b.api
    base = f"{api.base}/m/custom_fields/fields"
    for key, visibility in (("cipher", "private"), ("motto", "public")):
        response = api.client.post(base, json={"kind_key": "*", "key": key, "label": key.title(),
                                               "type": "text", "default_visibility": visibility,
                                               "temporal": True}, headers=HEADERS)  # fmt: skip
        assert response.status_code == 201, response.json()
    ledger = b.public("gadget", "Ledger", fields={"custom.cipher": b.canary_string(),
                                                  "custom.motto": b.canary_string()},
                      field_visibility={"custom.motto": "private"}, **home)  # fmt: skip
    fact = api.client.post(f"{api.base}/entities/{ledger['id']}/facts", headers=HEADERS, json={
        "field_key": "custom.cipher", "value": b.canary_string(),
        "timeline_id": b.canary.public["Prime"]})  # fmt: skip
    assert fact.status_code == 201, fact.json()
    b.canary.hidden_ids.add(fact.json()["fact"]["id"])
