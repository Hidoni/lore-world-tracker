"""Entity reads of the static export (#374, ADR 0016).

Lists (``entities``, ``tree``, ``children``) are answered in the browser from an **index**: each
listed entity's summary as the server lists it, the server's own orders for every sort, tags,
aliases, branch origin, and its existence over time; plus each timeline's lineage. Everything
else about an entity is a **shard** of recorded answers: the entity, its facts (per timeline),
links, backlinks, unlinked mentions, the facts it caused, and, for each timeline it is seen
in, its state, links and backlinks **at each moment they can change**.

Those moments come from the server's own coverage rule (``bound_moments``): an as-of read built
on facts and links is the same between two consecutive bound moments, so recording it once per
interval answers every cursor. The browser takes the last recorded moment at or before the
cursor (the first one is ``0``, the inception).
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity, EntityAlias, EntityTag
from lore.core.entities.queries import ORDERS
from lore.core.links.models import Link
from lore.core.links.service import LINK
from lore.core.modules.spec import VaultContext
from lore.core.time.models import Timeline
from lore.core.time.state import FACT, StateReader, bound_moments, timeline_resolver
from lore.core.time.timeline_view import TimelineView
from lore.core.visibility import READER
from lore.static_export.asgi import Recorder, route_with

SORTS = tuple(ORDERS)
EVENT_KIND = "event"
DIMENSION_KIND = "dimension"
UNLINKED_LIMIT = 200
LIST_LIMIT = 500


@dataclass(frozen=True)
class TimelineInfo:
    id: str
    dimension_id: str
    prime: bool
    lineage: list[str]


def _timelines(session: Session) -> dict[str, TimelineInfo]:
    found: dict[str, TimelineInfo] = {}
    for row in session.scalars(select(Timeline).join(Entity, Entity.id == Timeline.entity_id)):
        lineage = list(TimelineView.for_timeline(session, row.entity_id).timeline_ids)
        found[row.entity_id] = TimelineInfo(row.entity_id, row.dimension_id, row.is_prime, lineage)
    return found


def _same(a: Any, b: Any) -> bool:
    """Equal answers, the cursor moment they echo aside."""
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: v for k, v in a.items() if k != "at"} == {
            k: v for k, v in b.items() if k != "at"
        }
    return bool(a == b)


def _intervals(answers: list[tuple[int, Any]]) -> list[list[Any]]:
    """``[[moment, answer], …]`` keeping an answer only where it changes."""
    kept: list[list[Any]] = []
    for moment, answer in answers:
        if not kept or not _same(kept[-1][1], answer):
            kept.append([str(moment), answer])
    return kept


class EntityExport:
    def __init__(self, app: FastAPI, recorder: Recorder, vault_id: str) -> None:
        self.app = app
        self.recorder = recorder
        self.vault_id = vault_id
        self.base = f"vaults/{vault_id}"

    async def files(self) -> dict[str, Any]:
        """The index and the shards, by path under ``data/``."""
        opened = self.app.state.vaults.open(self.vault_id)
        with opened.sessions() as session:
            context = VaultContext(opened, session, self.app.state.registry)
            timelines = _timelines(session)
            summaries = await self._summaries(timelines)
            entities = {
                e.id: e
                for e in session.scalars(select(Entity).where(Entity.deleted_at.is_(None)))
                if e.id in summaries
            }
            moments = {
                (entity_id, timeline.id): self._moments(context, session, entity_id, timeline.id)
                for entity_id, entity in entities.items()
                for timeline in self._seen_in(entity, timelines)
            }
            index = self._index(session, summaries, entities, timelines)
        shards = await asyncio.gather(
            *(self._shard(entity, timelines, moments) for entity in entities.values())
        )
        files: dict[str, Any] = {}
        for entity_id, (shard, existence) in zip(entities, shards, strict=True):
            files[f"{self.base}/static/entities/{entity_id}"] = shard
            if existence:
                index["entities"][entity_id]["existence"] = existence
        files[f"{self.base}/static/index"] = index
        # For the time reads (``time.py``).
        self.timelines, self.summaries, self.moments = timelines, summaries, moments
        return files

    async def _summaries(self, timelines: dict[str, TimelineInfo]) -> dict[str, Any]:
        """Every listed entity's summary: the prime view, and each branch for branch-only ones."""
        summaries: dict[str, Any] = {}
        for timeline in [None, *(t.id for t in timelines.values() if not t.prime)]:
            params = {"limit": LIST_LIMIT, "timeline": timeline}
            for item in await self.recorder.pages(f"{self.base}/entities", params):
                summaries[item["id"]] = item
        return summaries

    @staticmethod
    def _seen_in(entity: Entity, timelines: dict[str, TimelineInfo]) -> list[TimelineInfo]:
        """The timelines an as-of read of the entity can name: its dimension's (every one for a
        multiversal entity), within its branch's lineage for a branch-only entity."""
        return [
            t
            for t in timelines.values()
            if (entity.dimension_id is None or t.dimension_id == entity.dimension_id)
            and (entity.origin_timeline_id is None or entity.origin_timeline_id in t.lineage)
        ]

    @staticmethod
    def _moments(
        context: VaultContext, session: Session, entity_id: str, timeline_id: str
    ) -> list[int]:
        """Where the entity's state, links or backlinks in the timeline can change, from ``0``."""
        resolver = timeline_resolver(context, READER, timeline_id)
        facts = StateReader(context, READER, timeline_id, 0).facts([entity_id]).get(entity_id, [])
        view = TimelineView.for_timeline(session, timeline_id)
        links = list(
            session.scalars(
                view.select(
                    Link,
                    where=lambda row: [
                        row.deleted_at.is_(None),
                        or_(row.source_id == entity_id, row.target_id == entity_id),
                    ],
                )
            )
        )
        found = bound_moments(resolver, FACT, facts) | bound_moments(resolver, LINK, links)
        return sorted({0, *(m for m in found if m >= 0)})

    def _index(
        self,
        session: Session,
        summaries: dict[str, Any],
        entities: dict[str, Entity],
        timelines: dict[str, TimelineInfo],
    ) -> dict[str, Any]:
        tags: dict[str, list[str]] = defaultdict(list)
        for entity_id, tag_id in session.execute(select(EntityTag.entity_id, EntityTag.tag_id)):
            tags[entity_id].append(tag_id)
        aliases: dict[str, list[str]] = defaultdict(list)
        for entity_id, alias in session.execute(select(EntityAlias.entity_id, EntityAlias.alias)):
            aliases[entity_id].append(alias)
        orders = {
            sort: [
                entity_id
                for entity_id in session.scalars(
                    select(Entity.id).order_by(*ORDERS[sort].columns(Entity))
                )
                if entity_id in entities
            ]
            for sort in SORTS
        }
        return {
            "entities": {
                entity_id: {
                    "summary": summaries[entity_id],
                    "tags": sorted(tags.get(entity_id, [])),
                    "aliases": aliases.get(entity_id, []),
                    "origin": entity.origin_timeline_id,
                    "multiversal": entity.dimension_id is None and entity.kind != DIMENSION_KIND,
                }
                for entity_id, entity in entities.items()
            },
            "orders": orders,
            "timelines": {
                t.id: {"dimension": t.dimension_id, "prime": t.prime, "lineage": t.lineage}
                for t in timelines.values()
            },
        }

    async def _shard(
        self,
        entity: Entity,
        timelines: dict[str, TimelineInfo],
        moments: dict[tuple[str, str], list[int]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The entity's recorded answers, and its existence over time per timeline (only where
        it has existence facts)."""
        route = f"{self.base}/entities/{entity.id}"
        get = self.recorder.get
        seen = self._seen_in(entity, timelines)
        shard: dict[str, Any] = {
            "entity": await get(route),
            "links": await get(f"{route}/links"),
            "backlinks": await get(f"{route}/backlinks"),
            "unlinked": await get(
                route_with(f"{route}/unlinked-mentions", {"limit": UNLINKED_LIMIT})
            ),
            "facts": {"": await get(f"{route}/facts")},
            "as_of": {},
        }
        if entity.kind == EVENT_KIND:
            shard["caused"] = await get(
                route_with(f"{self.base}/facts", {"source_event": entity.id})
            )
        existence: dict[str, Any] = {}
        for timeline in seen:
            shard["facts"][timeline.id] = await get(
                route_with(f"{route}/facts", {"timeline": timeline.id})
            )
            at = moments[(entity.id, timeline.id)]
            answers: dict[str, list[tuple[int, Any]]] = {"state": [], "links": [], "backlinks": []}
            for moment in at:
                params = {"timeline": timeline.id, "at": str(moment)}
                for read, path in (("state", "/state"), ("links", "/links"),
                                   ("backlinks", "/backlinks")):  # fmt: skip
                    answers[read].append((moment, await get(route_with(route + path, params))))
            shard["as_of"][timeline.id] = {read: _intervals(a) for read, a in answers.items()}
            states = shard["as_of"][timeline.id]["state"]
            if any(state["existence"] != "unknown" for _, state in states):
                existence[timeline.id] = _intervals(
                    [(int(m), state["existence"]) for m, state in states]
                )
        return shard, existence
