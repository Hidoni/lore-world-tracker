"""Time reads of the static export (#375, ADR 0016), recorded like the entity reads:

- per dimension: its timelines (``dimensions/<d>/timelines``);
- per timeline: the event tree (the roots and the sub-events of each event with some, every page),
  the cause → effect graph around each event it shows (at the deepest ``depth`` and the largest
  ``limit``: the browser trims to the ones asked, every node knows its ``distance``), and a
  branch's diff against its parent;
- per entity, where the module answers: its notes in each branch, its worldline and personal
  timeline per timeline, and its presence in every timeline (a time traveler can be anywhere) at
  each moment it can change (the bounds of its segments and of its existence facts);
- correspondences: the list (all, and per dimension) and each one.

Timeline windows and series occurrences are computed in the browser from `windows.py`'s files.
"""

import asyncio
from typing import Any

from lore.static_export.asgi import Recorder, route_with
from lore.static_export.entities import TimelineInfo

TREE_LIMIT = 500
CAUSALITY_DEPTH = 6
CAUSALITY_LIMIT = 500
DIFF_LIMIT = 2000
WORLDLINES = "m/worldlines/entities"
# A recorded failure (its problem body), replayed by the browser as the same problem.
PROBLEM = "problem"


class TimeExport:
    def __init__(self, recorder: Recorder, vault_id: str) -> None:
        self.recorder = recorder
        self.base = f"vaults/{vault_id}"

    async def files(
        self,
        timelines: dict[str, TimelineInfo],
        entities: dict[str, dict[str, Any]],
        moments: dict[tuple[str, str], list[int]],
    ) -> dict[str, Any]:
        """The time files, by path under ``data/``. ``entities`` are the listed summaries;
        ``moments`` the entity export's change moments per (entity, timeline)."""
        files: dict[str, Any] = {}
        get = self.recorder.get
        for dimension in sorted({t.dimension_id for t in timelines.values()}):
            route = f"{self.base}/dimensions/{dimension}/timelines"
            files[route] = await get(route)
        for timeline in timelines.values():
            tree, causality = await self._timeline(timeline)
            files[f"{self.base}/static/timelines/{timeline.id}"] = {"event_tree": tree}
            # Each event's graph in its own file: an event page loads only its own.
            for event, graph in causality.items():
                files[f"{self.base}/static/causality/{timeline.id}/{event}"] = graph
            if not timeline.prime:
                route = f"{self.base}/m/branches/timelines/{timeline.id}/diff"
                files[route] = await get(route_with(route, {"limit": DIFF_LIMIT}))
        files.update(await self._correspondences(timelines))
        ids = list(entities)
        worldlines = await asyncio.gather(*(self._worldline(e, timelines, moments) for e in ids))
        notes = await asyncio.gather(*(self._notes(e, timelines) for e in ids))
        for entity_id, worldline, note in zip(ids, worldlines, notes, strict=True):
            if worldline:
                files[f"{self.base}/static/worldlines/{entity_id}"] = worldline
            if note:
                files[f"{self.base}/static/notes/{entity_id}"] = note
        return files

    async def _timeline(
        self, timeline: TimelineInfo
    ) -> tuple[dict[str, list[Any]], dict[str, Any]]:
        """The timeline's event tree, by parent (``""``: the roots), and causality by event."""
        route = f"{self.base}/timelines/{timeline.id}"
        tree: dict[str, list[Any]] = {}
        pending: list[str | None] = [None]
        while pending:
            parent = pending.pop()
            params = {"limit": TREE_LIMIT, "parent": parent}
            items = await self.recorder.pages(f"{route}/event-tree", params)
            tree[parent or ""] = items
            pending += [item["id"] for item in items if item["has_children"]]
        events = [item["id"] for items in tree.values() for item in items]
        graphs = await asyncio.gather(
            *(
                self.recorder.get(
                    route_with(
                        f"{route}/causality",
                        {"event": event, "depth": CAUSALITY_DEPTH, "limit": CAUSALITY_LIMIT},
                    )
                )
                for event in events
            )
        )
        return tree, dict(zip(events, graphs, strict=True))

    async def _correspondences(self, timelines: dict[str, TimelineInfo]) -> dict[str, Any]:
        route = f"{self.base}/m/correspondences"
        status, listed = await self.recorder.answer(route)
        if status != 200:  # noqa: PLR2004 (the module is off in this vault)
            return {}
        files: dict[str, Any] = {route: listed}
        by_dimension = {}
        for dimension in sorted({t.dimension_id for t in timelines.values()}):
            by_dimension[dimension] = await self.recorder.get(
                route_with(route, {"dimension": dimension})
            )
        # Mapping (``correspondences/map``) is computed in the browser with the TS engine, along
        # the path the server takes for each pair (it doesn't depend on the moment).
        dimensions = sorted(by_dimension)
        paths = {}
        for a in dimensions:
            for b in dimensions:
                query = {"from_dimension": a, "to_dimension": b, "t": "0"}
                paths[f"{a}>{b}"] = (await self.recorder.get(route_with(f"{route}/map", query)))[
                    "path"
                ]
        durations = {
            d: (await self.recorder.get(f"{self.base}/entities/{d}"))["ext"]["duration"]
            for d in dimensions
        }
        files[f"{self.base}/static/correspondences"] = {
            "by_dimension": by_dimension,
            "paths": paths,
            "durations": durations,
        }
        for item in listed["items"]:
            one = f"{route}/{item['id']}"
            files[one] = await self.recorder.get(one)
        return files

    async def _worldline(
        self,
        entity_id: str,
        timelines: dict[str, TimelineInfo],
        moments: dict[tuple[str, str], list[int]],
    ) -> dict[str, Any] | None:
        """Segments, personal timeline and presence per timeline, or ``None`` where the
        worldlines module doesn't answer for the entity."""
        route = f"{self.base}/{WORLDLINES}/{entity_id}"
        status, default = await self.recorder.answer(f"{route}/segments")
        if status != 200:  # noqa: PLR2004
            return None
        status, personal = await self.recorder.answer(f"{route}/personal-timeline")
        found: dict[str, Any] = {
            "segments": {"": default},
            "personal": {"": personal if status == 200 else {PROBLEM: personal}},  # noqa: PLR2004
            "presence": {},
        }
        # Every timeline: a time traveler can be present in any dimension.
        for timeline in timelines.values():
            params = {"timeline": timeline.id}
            status, segments = await self.recorder.answer(route_with(f"{route}/segments", params))
            # A refusal (422: a timeline it can't be in) is recorded as its problem.
            found["segments"][timeline.id] = segments if status == 200 else {PROBLEM: segments}  # noqa: PLR2004
            bounds = (segments if status == 200 else default)["segments"]  # noqa: PLR2004
            status, personal = await self.recorder.answer(
                route_with(f"{route}/personal-timeline", params)
            )
            found["personal"][timeline.id] = personal if status == 200 else {PROBLEM: personal}  # noqa: PLR2004
            at = {0, *moments.get((entity_id, timeline.id), [])}
            for segment in bounds:
                for key in ("start_t", "end_t"):
                    if segment[key] is not None:
                        t = int(segment[key])
                        at.update(m for m in (t - 1, t, t + 1) if m >= 0)
            answers = []
            for t in sorted(at):
                query = {"dimension": timeline.dimension_id, "timeline": timeline.id, "t": str(t)}
                status, presence = await self.recorder.answer(
                    route_with(f"{route}/presence", query)
                )
                answers.append((t, presence if status == 200 else {PROBLEM: presence}))  # noqa: PLR2004
            found["presence"][timeline.id] = _changes(answers)
        return found

    async def _notes(self, entity_id: str, timelines: dict[str, TimelineInfo]) -> dict[str, Any]:
        """The entity's note in each branch that answers (none for prime timelines)."""
        notes: dict[str, Any] = {}
        for timeline in timelines.values():
            if timeline.prime:
                continue
            route = f"{self.base}/m/branches/notes/{entity_id}/{timeline.id}"
            status, note = await self.recorder.answer(route)
            if status == 200:  # noqa: PLR2004
                notes[timeline.id] = note
        return notes


def _changes(answers: list[tuple[int, Any]]) -> list[list[Any]]:
    """``[[moment, answer], …]`` keeping an answer only where it changes (its ``t`` aside)."""
    kept: list[list[Any]] = []
    for moment, answer in answers:
        same = kept and {k: v for k, v in kept[-1][1].items() if k != "t"} == {
            k: v for k, v in answer.items() if k != "t"
        }
        if not same:
            kept.append([str(moment), answer])
    return kept
