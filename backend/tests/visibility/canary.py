"""The canary vault (``visibility-and-sharing.md`` §5): private content of every type that exists
so far, each carrying a unique ``CANARY-<n>`` string, plus the ids of everything readers must
never see. Built through the API (services), in author mode.

Extend it whenever a new kind of private content appears (``#139`` completes it for M12): add the
content, its canary string, and the ids that must stay hidden.
"""

import copy
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lore.app import create_app
from lore.config import Settings
from lore.core.modules import ModuleSpec
from lore.modules import ALL_MODULES
from tests.conftest import local_client
from tests.entity_api import HEADERS, LinkApi
from tests.entity_modules import ENTITY_MODULES
from tests.sample_modules import ADDON, BASE, SAMPLE
from tests.time.test_calendars import YEARS

# The real modules plus test modules with kinds, fields and module routes to cover.
LEAK_MODULES: tuple[ModuleSpec, ...] = (*ALL_MODULES, *ENTITY_MODULES, BASE, SAMPLE, ADDON)
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
        b.public("gadget", "Compass", fields={"text": "brass"}, **home)

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
        api.made_link("core.related", spoiled, b.public("gadget", "Mirror", **home))

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
        shelf = b.public("misc", "Shelf", **home)
        b.public("misc", "Book", parent_id=shelf["id"], **home)
        b.hidden("misc", visibility="private", parent_id=shelf["id"], **home)

        # A module kind whose rich-text field has a private block.
        b.public(
            "creature",
            "Wyrm",
            fields={"lore": doc(p(text("it sleeps")), private(p(text(b.canary_string()))))},
            **home,
        )

        canary.tags = {t["name"]: t["id"] for t in api.get(ghost["id"]).json()["tags"]}
        canary.hidden_ids.update(canary.tags.values())
        changes = client.get(f"{api.base}/changes", params={"limit": 1}).json()
        canary.changeset = changes["items"][0]["id"]
        backup = client.post(f"{api.base}/backups", json={"include_media": False})
        assert backup.status_code == 201, backup.json()
        canary.backup = backup.json()["id"]
        return canary
