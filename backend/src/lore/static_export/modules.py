"""Module reads of the static export (#376, ADR 0016), as each module declares them
(``ModuleSpec.static_reads``: the builder never imports modules).

Each read is recorded per route (its ids filled in) into ``static/reads/<route>``:

- ``answers``: by query (the sorted ``[name, value]`` pairs as JSON), the answer, or the
  problem it was refused with;
- ``as_of``: by query (without ``at``), the answer at each moment as-of answers can change in
  that timeline, kept where it changes (``[[moment, answer], …]``: the browser takes the last at
  or before the cursor). Those moments are every bound of the timeline's facts and links
  (``bound_moments``, from the entity export), so any reading of them is covered;
- ``lists``: by query, every item of a paged read, for the browser to filter and page.

Downloads (``file``) are copied under ``static/files/`` and listed in ``static/files`` (by
route and query), so the app links to the copies.
"""

import json
import mimetypes
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from lore.core.modules import ModuleSpec, StaticRead
from lore.static_export.asgi import Recorder, RecordingError, route_with
from lore.static_export.entities import TimelineInfo, intervals
from lore.static_export.time import PROBLEM

READS = "static/reads"
FILES = "static/files"
NOT_FOUND = 404
OK = 200

type Pairs = tuple[tuple[str, str], ...]


def query_key(pairs: Iterable[tuple[str, str]]) -> str:
    """The key of a query in a reads file (the browser builds the same one: ``static-modules.ts``),
    without ``at`` (as-of answers are by moment)."""
    found = sorted((name, value) for name, value in pairs if name != "at")
    return json.dumps([list(pair) for pair in found], separators=(",", ":"), ensure_ascii=False)


def _fill(pairs: Pairs, entity_id: str | None) -> Pairs:
    return tuple((name, value.replace("{id}", entity_id or "")) for name, value in pairs)


def _extension(content_type: str) -> str:
    mime = content_type.partition(";")[0].strip()
    return {"image/jpeg": ".jpg", "text/csv": ".csv"}.get(mime) or (
        mimetypes.guess_extension(mime) or ".bin"
    )


@dataclass
class _File:
    """One route's recorded reads."""

    answers: dict[str, Any] = field(default_factory=dict)
    as_of: dict[str, Any] = field(default_factory=dict)
    lists: dict[str, Any] = field(default_factory=dict)

    def dump(self) -> dict[str, Any]:
        return {"answers": self.answers, "as_of": self.as_of, "lists": self.lists}


class ModuleExport:
    def __init__(self, recorder: Recorder, vault_id: str) -> None:
        self.recorder = recorder
        self.base = f"vaults/{vault_id}"
        self.reads: dict[str, _File] = {}
        self.binaries: dict[str, bytes] = {}
        self.files: dict[str, str] = {}
        self.ids: dict[tuple[str, str], set[str]] = {}

    async def record(
        self,
        modules: Iterable[ModuleSpec],
        summaries: dict[str, dict[str, Any]],
        timelines: dict[str, TimelineInfo],
        moments: dict[tuple[str, str], list[int]],
        events: dict[tuple[str, str], set[int]],
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        """The JSON files and the copied downloads, by path under ``data/``. ``summaries`` are
        the listed entities, ``moments`` the entity export's change moments per (entity,
        timeline), ``events`` the moments around each event's start and end."""
        self.summaries = summaries
        self.timelines = timelines
        # An entity's reads change where its facts and links do, and where it happens (an
        # event: a map pin of an event is shown while it happens).
        self.by_entity: dict[tuple[str, str], set[int]] = {}
        for key, found in [*moments.items(), *events.items()]:
            self.by_entity.setdefault(key, set()).update(found)
        self.moments: dict[str, list[int]] = {}
        for (_entity, timeline), found in moments.items():
            self.moments.setdefault(timeline, []).extend(found)
        for timeline, found in self.moments.items():
            self.moments[timeline] = sorted({0, *found})
        self.dimensions = sorted({t.dimension_id for t in timelines.values()})
        for module in modules:
            for read in module.static_reads:
                await self._read(module.id, read)
        files: dict[str, Any] = {
            f"{self.base}/{READS}/{route}": recorded.dump()
            for route, recorded in self.reads.items()
        }
        files[f"{self.base}/{FILES}"] = self.files
        return files, self.binaries

    def _entity_ids(self, module: str, read: StaticRead) -> Sequence[str | None]:
        if read.ids_from is not None:
            return sorted(self.ids.get((module, read.ids_from), set()))
        if read.kind is None:
            return [None]
        return [
            entity_id
            for entity_id, summary in self.summaries.items()
            if read.kind == "*" or summary["kind"] == read.kind
        ]

    def _timelines(self, entity_id: str | None) -> list[TimelineInfo]:
        """The timelines an entity's reads can name (its dimension's; any for the others)."""
        summary = self.summaries.get(entity_id or "")
        dimension = None if summary is None else summary.get("dimension_id")
        return [
            t for t in self.timelines.values() if dimension is None or t.dimension_id == dimension
        ]

    async def _read(self, module: str, read: StaticRead) -> None:
        for entity_id in self._entity_ids(module, read):
            path = read.path.replace("{id}", entity_id or "")
            route = f"m/{module}/{path}"
            for variant in read.variants:
                dimensions = [None, *self.dimensions] if read.dimension else [None]
                for dimension in dimensions:
                    pairs = _fill(variant, entity_id)
                    if dimension is not None:
                        pairs += (("dimension", dimension),)
                    if not await self._one(module, read, route, pairs, entity_id):
                        return  # the module is off in this vault

    async def _get(self, route: str, pairs: Pairs) -> tuple[int, Any]:
        return await self.recorder.answer(self._route(route, pairs))

    def _route(self, route: str, pairs: Pairs) -> str:
        return f"{self.base}/{route}" + (f"?{urlencode(pairs)}" if pairs else "")

    async def _one(
        self, module: str, read: StaticRead, route: str, pairs: Pairs, entity_id: str | None
    ) -> bool:
        """Records one query of a read (and its timelines); ``False`` when the module answers
        ``404`` to a read without ids (it is off)."""
        if read.file:
            await self._file(route, pairs)
            return True
        recorded = self.reads.setdefault(route, _File())
        if read.paged is not None:
            params = {**dict(pairs), "limit": read.paged}
            status, first = await self.recorder.answer(route_with(f"{self.base}/{route}", params))
            if status == NOT_FOUND:
                return entity_id is not None  # without ids: the module is off
            if status != OK:
                raise RecordingError(f"GET {route} with {params} answered {status}: {first}")
            items = await self.recorder.pages(f"{self.base}/{route}", params)
            recorded.lists[query_key(pairs)] = items
            self._collect(module, read.path, items)
            return True
        status, answer = await self._get(route, pairs)
        if status == NOT_FOUND and entity_id is None and read.ids_from is None:
            return False
        recorded.answers[query_key(pairs)] = answer if status == OK else {PROBLEM: answer}
        if status == OK and isinstance(answer, dict):
            self._collect(module, read.path, answer.get("items") or [])
        if not (read.timeline or read.as_of):
            return True
        dimension = dict(pairs).get("dimension")
        for timeline in self._timelines(entity_id):
            if dimension is not None and timeline.dimension_id != dimension:
                continue  # the app asks with the time context's dimension and timeline
            in_timeline = (*pairs, ("timeline", timeline.id))
            status, answer = await self._get(route, in_timeline)
            recorded.answers[query_key(in_timeline)] = answer if status == OK else {PROBLEM: answer}
            if not read.as_of or status != OK:
                continue
            answers = []
            for moment in self._moments_of(timeline.id, entity_id, answer):
                status, answer = await self._get(route, (*in_timeline, ("at", str(moment))))
                answers.append((moment, answer if status == OK else {PROBLEM: answer}))
            recorded.as_of[query_key(in_timeline)] = intervals(answers)
        return True

    def _moments_of(self, timeline_id: str, entity_id: str | None, answer: Any) -> list[int]:
        """Where an as-of read can change: the bounds of the facts and links of the entities it
        names in the timeline (its answer without ``at`` names every one it can show), or of
        all of them for a read about no entity, and the moments it names itself."""
        # The moments the answer names (a pin's validity: module rows have their own).
        found = {0, *(m for t in _moments(answer) for m in (t - 1, t, t + 1) if m >= 0)}
        if entity_id is None:
            return sorted(found | set(self.moments.get(timeline_id, [])))
        named = {entity_id, *(i for i in _strings(answer) if i in self.summaries)}
        for named_id in named:
            found.update(self.by_entity.get((named_id, timeline_id), []))
        return sorted(found)

    def _collect(self, module: str, path: str, items: list[Any]) -> None:
        """The ids of a read's items, for the reads of each one (``ids_from``)."""
        found = self.ids.setdefault((module, path), set())
        found.update(item["id"] for item in items if isinstance(item, dict) and "id" in item)

    async def _file(self, route: str, pairs: Pairs) -> None:
        status, body, content_type = await self.recorder.raw(self._route(route, pairs))
        if status != OK:
            return  # no such size (thumbnails exist for raster images only)
        name = "-".join(value for _name, value in pairs) or "file"
        path = f"{self.base}/{FILES}/{route}/{name}{_extension(content_type)}"
        self.binaries[path] = body
        self.files[f"{route}?{query_key(pairs)}"] = path


def _strings(value: Any) -> Iterable[str]:
    """Every string in a JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _moments(value: Any) -> Iterable[int]:
    """The moments of a JSON answer: its ``*_t`` fields."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_t") and isinstance(item, str) and item.isdigit():
                yield int(item)
            else:
                yield from _moments(item)
    elif isinstance(value, list):
        for item in value:
            yield from _moments(item)
