"""The maps service (``docs/modules/maps.md``): maps of locations and their pins.

- A map's image is a raster item of the media library; its size is copied at creation (and when
  the image changes). The map records its use with ``media.api.reference`` (context ``map``, at
  the map's visibility), so readers who see the map see the image and it is never collected.
- A pin with an explicit validity lives in a timeline of the map location's dimension (time slots
  ``maps.pin``: ``valid_from``, ``valid_to``; branches override them like facts). Without one it
  is timeless and follows its target's existence at the cursor: an entity with existence facts
  where it exists (possibly, too), an event while it happens; a label pin always.
- Readers see a pin iff the pin, its map (and the map's location) and its target (if any) are
  visible (``PIN_VISIBILITY``, ``MAP_VISIBILITY``); time-bound pins also need their timeline.
- Regions (#154) are polygons, time-bound and shown at the cursor exactly like pins (record type
  ``maps.region``). Each lists who controls its target: the visible entities with a
  ``groups.controls`` link to it (valid at the cursor), so a territory takes its ruler's color.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Select, or_, select

from lore.chronology.schema import TimePoint
from lore.core.db.base import Visibility
from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ErrorItem, InvalidInputError, NotFoundError
from lore.core.links.service import LinkService
from lore.core.modules.spec import VaultContext
from lore.core.time import SlotDef, SlotProvider
from lore.core.time.changes import report as report_time
from lore.core.time.dimensions import TIMELINE, prime_timeline
from lore.core.time.models import Event
from lore.core.time.overrides import ValidityRecord, register_validity_record, sync_starts
from lore.core.time.propagate import TimeWriter
from lore.core.time.state import AsOf, Coverage, StateReader, resolve_as_of
from lore.core.time.timeline_view import TimelineView
from lore.core.types import Affected
from lore.core.visibility import AUTHOR, VisibilityFilter, VisibilityPolicy
from lore.modules.maps.models import Map, MapPin, MapRegion
from lore.modules.maps.schemas import (
    EntityPin,
    EntityPins,
    MapCreate,
    MapCrumb,
    MapDetail,
    MapList,
    MapRecord,
    MapUpdate,
    MapWriteResult,
    PinCreate,
    PinOut,
    PinTarget,
    PinUpdate,
    PinWriteResult,
    RegionController,
    RegionCreate,
    RegionOut,
    RegionUpdate,
    RegionWriteResult,
    Scale,
    Shown,
)
from lore.modules.media import api as media

RECORD = "maps.pin"
REGION_RECORD = "maps.region"
# The groups module's link type (maps doesn't depend on it: without it no region has rulers).
CONTROLS = "groups.controls"
LOCATION = "location"
EVENT = "event"
SLOTS = ("valid_from", "valid_to")
MEDIA_CONTEXT = "map"
RASTER = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"})

MAP_VISIBILITY = VisibilityFilter(Map, entity_columns=("location_id",))
PIN_VISIBILITY = VisibilityFilter(MapPin, entity_columns=("target_entity_id", "timeline_id"))
REGION_VISIBILITY = VisibilityFilter(MapRegion, entity_columns=("target_entity_id", "timeline_id"))
PIN_SLOTS = SlotProvider(
    RECORD, MapPin, (SlotDef("valid_from"), SlotDef("valid_to")), timeline_column="timeline_id"
)
REGION_SLOTS = SlotProvider(
    REGION_RECORD,
    MapRegion,
    (SlotDef("valid_from"), SlotDef("valid_to")),
    timeline_column="timeline_id",
)

type Placed = MapPin | MapRegion
"""A pin or a region: what a map shows at image coordinates."""


def _map_location(session: Any, placed: Placed) -> str:
    row = session.get(Map, placed.map_id)
    return "" if row is None else row.location_id


PIN_OVERRIDES = register_validity_record(ValidityRecord(RECORD, MapPin, _map_location))
REGION_OVERRIDES = register_validity_record(ValidityRecord(REGION_RECORD, MapRegion, _map_location))


def _invalid(path: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code=code, message=message)])


def map_out(row: Map) -> MapRecord:
    return MapRecord(
        id=row.id, location_id=row.location_id, media_id=row.media_id, name=row.name,
        description=row.description, width=row.width, height=row.height,
        scale=None if row.scale is None else Scale.model_validate(row.scale),
        sort_key=row.sort_key, visibility=row.visibility, revision=row.revision,
        created_at=row.created_at, updated_at=row.updated_at, deleted_at=row.deleted_at,
    )  # fmt: skip


class Maps:
    def __init__(self, context: VaultContext, policy: VisibilityPolicy = AUTHOR) -> None:
        self.context = context
        self.session = context.session
        self.policy = policy
        self.entities = EntityService(context, policy)

    # --- maps -----------------------------------------------------------------------------------

    def _maps(self) -> Select[Any]:
        return select(Map).where(Map.deleted_at.is_(None), *self.policy.module_rows(MAP_VISIBILITY))

    def map(self, map_id: str) -> Map:
        row: Map | None = self.session.scalars(self._maps().where(Map.id == map_id)).one_or_none()
        if row is None:
            raise NotFoundError(f"No map {map_id}.")
        return row

    def list_maps(self, location_id: str | None = None) -> MapList:
        statement = self._maps()
        if location_id is not None:
            self.entities.load_visible(location_id)
            statement = statement.where(Map.location_id == location_id)
        rows = self.session.scalars(
            statement.order_by(Map.location_id, Map.sort_key.is_(None), Map.sort_key, Map.id)
        )
        return MapList(items=[map_out(row) for row in rows])

    def _first_maps(self, location_ids: Iterable[str]) -> dict[str, Map]:
        """Each location's first map (by ``sort_key``, then creation) the request sees."""
        wanted = sorted(set(location_ids))
        if not wanted:
            return {}
        found: dict[str, Map] = {}
        rows = self.session.scalars(
            self._maps()
            .where(Map.location_id.in_(wanted))
            .order_by(Map.location_id, Map.sort_key.is_(None), Map.sort_key, Map.id)
        )
        for row in rows:
            found.setdefault(row.location_id, row)
        return found

    def _location(self, location_id: str, path: str) -> Entity:
        try:
            entity = self.entities.load_visible(location_id)
        except NotFoundError as error:
            raise _invalid(path, f"No location {location_id}.") from error
        if entity.kind != LOCATION or entity.deleted_at is not None:
            raise _invalid(path, f"{location_id} is not a location.")
        return entity

    def _image(self, media_id: str) -> media.MediaInfo:
        found = media.info(self.session, media_id)
        if found is None or found.trashed:
            raise _invalid("media_id", "No such media item.")
        if found.mime not in RASTER or not found.width or not found.height:
            raise _invalid(
                "media_id", "A map's image must be a picture (png, jpeg, webp, gif, avif)."
            )
        return found

    def create(self, data: MapCreate) -> MapWriteResult:
        location = self._location(data.location_id, "location_id")
        image = self._image(data.media_id)
        assert image.width is not None
        assert image.height is not None
        row = Map(
            location_id=location.id, media_id=image.id, name=data.name,
            description=data.description,
            scale=None if data.scale is None else data.scale.model_dump(),
            width=image.width, height=image.height, sort_key=data.sort_key,
            visibility=data.visibility,
        )  # fmt: skip
        self.session.add(row)
        self.session.flush()
        self._reference_images(location.id)
        return MapWriteResult(map=map_out(row), affected=self._affected([location.id]))

    def _check_revision(self, revision: int, current: int, what: str) -> None:
        if revision != current:
            raise RevisionConflictError(
                f"The {what} was changed meanwhile (revision {current}, the edit is based on "
                f"{revision}).",
                context={"current_revision": current},
            )

    def update(self, map_id: str, data: MapUpdate) -> MapWriteResult:
        row = self.map(map_id)
        self._check_revision(data.revision, row.revision, "map")
        sent = data.model_fields_set - {"revision", "suppress"}
        for name in ("name", "description", "sort_key"):
            if name in sent and (getattr(data, name) is not None or name == "sort_key"):
                setattr(row, name, getattr(data, name))
        if "scale" in sent:
            row.scale = None if data.scale is None else data.scale.model_dump()
        if "visibility" in sent and data.visibility is not None:
            row.visibility = data.visibility
        if "media_id" in sent and data.media_id is not None and data.media_id != row.media_id:
            image = self._image(data.media_id)
            row.media_id, row.width, row.height = image.id, image.width or 1, image.height or 1
        self.session.flush()
        self._reference_images(row.location_id)
        return MapWriteResult(map=map_out(row), affected=self._affected([row.location_id]))

    def trash(self, map_id: str) -> MapWriteResult:
        """The map (and its pins) to the trash; the image is no longer used by it."""
        row = self.map(map_id)
        now = utc_now()
        row.deleted_at = now
        models: tuple[Any, ...] = (MapPin, MapRegion)
        for model in models:
            placed: Any
            for placed in self.session.scalars(
                select(model).where(model.map_id == row.id, model.deleted_at.is_(None))
            ):
                placed.deleted_at = now
        self.session.flush()
        self._reference_images(row.location_id)
        return MapWriteResult(map=map_out(row), affected=self._affected([row.location_id]))

    def _reference_images(self, location_id: str) -> None:
        """The location's ``map`` media references: its live maps' images, each at its most
        visible map's level."""
        media.unreference(self.session, location_id, MEDIA_CONTEXT)
        levels: dict[str, Visibility] = {}
        rank = {"public": 0, "spoiler": 1, "private": 2}
        for media_id, level in self.session.execute(
            select(Map.media_id, Map.visibility).where(
                Map.location_id == location_id, Map.deleted_at.is_(None)
            )
        ):
            if media_id not in levels or rank[level] < rank[levels[media_id]]:
                levels[media_id] = level
        for media_id, level in sorted(levels.items()):
            media.reference(self.session, media_id, location_id, MEDIA_CONTEXT, level)

    # --- reading pins ---------------------------------------------------------------------------

    def _pin_conditions(self, row: Any) -> list[Any]:
        return [row.deleted_at.is_(None), *self.policy.module_rows(PIN_VISIBILITY, row)]

    def _region_conditions(self, row: Any) -> list[Any]:
        return [row.deleted_at.is_(None), *self.policy.module_rows(REGION_VISIBILITY, row)]

    def _pins_of(self, map_row: Map, timeline_id: str | None) -> list[MapPin]:
        return self._placed_of(MapPin, self._pin_conditions, map_row, timeline_id)

    def _regions_of(self, map_row: Map, timeline_id: str | None) -> list[MapRegion]:
        return self._placed_of(MapRegion, self._region_conditions, map_row, timeline_id)

    def _placed_of[T: Placed](
        self, model: type[T], conditions: Any, map_row: Map, timeline_id: str | None
    ) -> list[T]:
        """The map's live pins (or regions): timeless ones and the time-bound ones the timeline
        sees (the prime timeline of the location's dimension by default)."""
        timeless = list(
            self.session.scalars(
                select(model).where(
                    model.map_id == map_row.id,
                    model.timeline_id.is_(None),
                    *conditions(model),
                )
            )
        )
        if timeline_id is None:
            location = self.session.get(Entity, map_row.location_id)
            dimension = None if location is None else location.dimension_id
            prime = None if dimension is None else prime_timeline(self.session, dimension)
            timeline_id = None if prime is None else prime.id
        if timeline_id is None:
            return timeless
        view = TimelineView.for_timeline(self.session, timeline_id)
        bound = self.session.scalars(
            view.select(model, where=lambda row: [row.map_id == map_row.id, *conditions(row)])
        )
        return [*timeless, *bound]

    def _shown_at(
        self, pins: Sequence[Placed], as_of: AsOf, record: str = RECORD
    ) -> dict[str, Shown]:
        """How each pin (or region, ``record``) shows at the cursor (absent: hidden)."""
        shown: dict[str, Shown] = {}
        reader = StateReader(self.context, self.policy, as_of.timeline_id, as_of.t)
        coverage = Coverage(reader.resolver, record, as_of.t)
        coverage.preload(pin for pin in pins if pin.timeline_id is not None)
        followers = [pin for pin in pins if pin.timeline_id is None]
        target_ids = sorted({p.target_entity_id for p in followers if p.target_entity_id})
        targets = {
            e.id: e for e in self.session.scalars(select(Entity).where(Entity.id.in_(target_ids)))
        }
        existence = reader.existence([t for t in targets.values() if t.kind != EVENT])
        happening = self._events_at([t for t in targets.values() if t.kind == EVENT], as_of)
        for pin in pins:
            if pin.timeline_id is not None:
                certainty = coverage.of(pin)
                if certainty is not None:
                    shown[pin.id] = certainty
                continue
            target = targets.get(pin.target_entity_id or "")
            if target is None:
                shown[pin.id] = "certain"
            elif target.kind == EVENT:
                if target.id in happening:
                    shown[pin.id] = "certain"
            else:
                state = existence.get(target.id, "unknown")
                if state in ("exists", "unknown"):
                    shown[pin.id] = "certain"
                elif state == "possible":
                    shown[pin.id] = "possible"
        return shown

    def _events_at(self, events: Sequence[Entity], as_of: AsOf) -> set[str]:
        if not events:
            return set()
        view = TimelineView.for_timeline(self.session, as_of.timeline_id)
        ids = [e.id for e in events]
        rows = self.session.execute(
            view.select(Event, where=lambda row: [row.entity_id.in_(ids)]).with_only_columns(
                Event.entity_id, Event.start_t, Event.end_t
            )
        )
        t = as_of.t
        return {
            entity_id
            for entity_id, start, end in rows
            if start is not None and start <= t <= (start if end is None else end)
        }

    def _pin_outs(
        self, pins: Sequence[MapPin], shown: dict[str, Shown] | None = None
    ) -> list[PinOut]:
        target_ids = sorted({p.target_entity_id for p in pins if p.target_entity_id})
        targets = {
            e.id: e for e in self.session.scalars(select(Entity).where(Entity.id.in_(target_ids)))
        }
        drill = self._first_maps(t.id for t in targets.values() if t.kind == LOCATION)
        outs: list[PinOut] = []
        for pin in pins:
            target = targets.get(pin.target_entity_id or "")
            child = pin.child_map_id
            if child is None and target is not None and target.id in drill:
                child = drill[target.id].id
            outs.append(
                PinOut(
                    id=pin.id,
                    map_id=pin.map_id,
                    target=None
                    if target is None
                    else PinTarget(
                        id=target.id,
                        kind=target.kind,
                        name=target.name,
                        icon=target.icon,
                        color=target.color,
                    ),
                    label=pin.label,
                    display_label=pin.label or (target.name if target is not None else ""),
                    x=pin.x,
                    y=pin.y,
                    icon=pin.icon,
                    color=pin.color,
                    child_map_id=pin.child_map_id,
                    drill_map_id=child,
                    visibility=pin.visibility,
                    timeline_id=pin.timeline_id,
                    overrides_id=pin.overrides_id,
                    valid_from=pin.valid_from_spec,
                    valid_to=pin.valid_to_spec,
                    valid_from_t=pin.valid_from_t,
                    valid_to_t=pin.valid_to_t,
                    time_status=pin.time_status,
                    revision=pin.revision,
                    shown=(shown or {}).get(pin.id, "certain"),
                )
            )
        return outs

    def detail(self, map_id: str, *, timeline_id: str | None, at: str | None) -> MapDetail:
        """The map, its pins (as of the cursor when ``at`` is given) and its breadcrumbs."""
        row = self.map(map_id)
        as_of: AsOf | None = None
        if at is not None:
            if timeline_id is None:
                location = self.session.get(Entity, row.location_id)
                dimension = None if location is None else location.dimension_id
                prime = None if dimension is None else prime_timeline(self.session, dimension)
                if prime is None:
                    raise _invalid("timeline", "`at` needs a timeline here.")
                timeline_id = prime.id
            as_of = resolve_as_of(self.context, self.policy, timeline_id, at)
        elif timeline_id is not None:
            self.entities.load_visible(timeline_id)
        pins = sorted(self._pins_of(row, timeline_id), key=lambda p: (p.y, p.x, p.id))
        regions = sorted(self._regions_of(row, timeline_id), key=lambda r: r.id)
        shown = region_shown = None
        if as_of is not None:
            shown = self._shown_at(pins, as_of)
            pins = [pin for pin in pins if pin.id in shown]
            region_shown = self._shown_at(regions, as_of, REGION_RECORD)
            regions = [region for region in regions if region.id in region_shown]
        return MapDetail(
            **map_out(row).model_dump(), pins=self._pin_outs(pins, shown),
            regions=self._region_outs(regions, region_shown, as_of),
            breadcrumbs=self._breadcrumbs(row),
        )  # fmt: skip

    def _targets(self, placed: Sequence[Placed]) -> dict[str, Entity]:
        ids = sorted({p.target_entity_id for p in placed if p.target_entity_id})
        return {e.id: e for e in self.session.scalars(select(Entity).where(Entity.id.in_(ids)))}

    def _controllers(
        self, target_ids: Iterable[str], as_of: AsOf | None
    ) -> dict[str, list[RegionController]]:
        """Who controls each target: the visible sources of its ``groups.controls`` links (valid
        at the cursor with ``as_of``)."""
        links = LinkService(self.session, self.context.registry, self.policy, self.context.vault)
        found: dict[str, list[RegionController]] = {}
        for target_id in sorted(set(target_ids)):
            try:
                # Only enabled link types are offered: without groups, nobody controls anything.
                items = links.entity_links(target_id, direction="in", types=[CONTROLS], as_of=as_of)
            except NotFoundError:  # the target's module is off
                continue
            found[target_id] = [
                RegionController(
                    id=item.other.id,
                    kind=item.other.kind,
                    name=item.other.name,
                    color=item.other.color,
                )
                for item in items.items
            ]
        return found

    def _region_outs(
        self,
        regions: Sequence[MapRegion],
        shown: dict[str, Shown] | None = None,
        as_of: AsOf | None = None,
    ) -> list[RegionOut]:
        targets = self._targets(regions)
        controllers = self._controllers(targets, as_of)
        return [
            RegionOut(
                id=region.id,
                map_id=region.map_id,
                target=None
                if (target := targets.get(region.target_entity_id or "")) is None
                else PinTarget(
                    id=target.id,
                    kind=target.kind,
                    name=target.name,
                    icon=target.icon,
                    color=target.color,
                ),
                label=region.label,
                display_label=region.label or (target.name if target is not None else ""),
                points=region.points,
                color=region.color,
                controllers=controllers.get(region.target_entity_id or "", []),
                visibility=region.visibility,
                timeline_id=region.timeline_id,
                overrides_id=region.overrides_id,
                valid_from=region.valid_from_spec,
                valid_to=region.valid_to_spec,
                valid_from_t=region.valid_from_t,
                valid_to_t=region.valid_to_t,
                time_status=region.time_status,
                revision=region.revision,
                shown=(shown or {}).get(region.id, "certain"),
            )
            for region in regions
        ]

    def _breadcrumbs(self, row: Map) -> list[MapCrumb]:
        chain: list[str] = []
        current = self.session.get(Entity, row.location_id)
        seen: set[str] = set()
        while current is not None and current.parent_id and current.parent_id not in seen:
            seen.add(current.parent_id)
            parent = self.session.get(Entity, current.parent_id)
            if parent is None or parent.deleted_at is not None:
                break
            chain.append(parent.id)
            current = parent
        visible = self.policy.visible_ids(self.session, chain)
        firsts = self._first_maps(i for i in chain if i in visible)
        crumbs = [
            MapCrumb(map_id=firsts[i].id, name=firsts[i].name, location_id=i)
            for i in reversed(chain)
            if i in firsts
        ]
        return crumbs

    def entity_pins(self, entity_id: str) -> EntityPins:
        """Where an entity is pinned (every timeline's pins; the UI picks)."""
        self.entities.load_visible(entity_id)
        rows = self.session.execute(
            select(MapPin, Map)
            .join(Map, Map.id == MapPin.map_id)
            .where(
                MapPin.target_entity_id == entity_id,
                MapPin.overrides_id.is_(None),
                *self._pin_conditions(MapPin),
                Map.deleted_at.is_(None),
                *self.policy.module_rows(MAP_VISIBILITY, Map),
            )
            .order_by(Map.id, MapPin.id)
        ).all()
        outs = self._pin_outs([pin for pin, _ in rows])
        return EntityPins(
            entity_id=entity_id,
            items=[
                EntityPin(pin=out, map=map_out(m)) for out, (_, m) in zip(outs, rows, strict=True)
            ],
        )

    # --- writing pins ---------------------------------------------------------------------------

    def pin(self, pin_id: str) -> MapPin:
        row = self.session.scalars(
            select(MapPin).where(MapPin.id == pin_id, *self._pin_conditions(MapPin))
        ).one_or_none()
        if row is None:
            raise NotFoundError(f"No pin {pin_id}.")
        self.map(row.map_id)
        return row

    def _check_pin(
        self,
        map_row: Map,
        *,
        target_id: str | None,
        label: str | None,
        child_map_id: str | None,
        timeline_id: str | None,
        valid_from: TimePoint | None,
        valid_to: TimePoint | None,
        what: str = "pin",
    ) -> None:
        if target_id is None and not label:
            raise _invalid("label", f"A {what} without a target needs a label.", "required")
        if target_id is not None:
            try:
                target = self.entities.load_visible(target_id)
            except NotFoundError as error:
                raise _invalid("target_entity_id", f"No entity {target_id}.") from error
            if target.deleted_at is not None:
                raise _invalid("target_entity_id", f"{target_id} is in the trash.")
        if (
            child_map_id is not None
            and self.session.scalar(
                self._maps().where(Map.id == child_map_id).with_only_columns(Map.id)
            )
            is None
        ):
            raise _invalid("child_map_id", f"No map {child_map_id}.")
        if valid_from is None and valid_to is None:
            if timeline_id is not None:
                raise _invalid("timeline_id", f"A {what} without a validity has no timeline.")
            return
        if timeline_id is None:
            raise _invalid("timeline_id", "A validity needs a timeline.", "required")
        try:
            timeline = self.entities.load_visible(timeline_id)
        except NotFoundError as error:
            raise _invalid("timeline_id", f"No timeline {timeline_id}.") from error
        location = self.session.get(Entity, map_row.location_id)
        if timeline.kind != TIMELINE or timeline.deleted_at is not None:
            raise _invalid("timeline_id", f"{timeline_id} is not a timeline.")
        if (
            location is not None
            and location.dimension_id is not None
            and (timeline.dimension_id != location.dimension_id)
        ):
            raise _invalid("timeline_id", "The timeline is not in the map location's dimension.")

    def _check_inside(self, map_row: Map, x: float, y: float) -> None:
        if x > map_row.width:
            raise _invalid("x", f"x must lie on the map (0 to {map_row.width}).")
        if y > map_row.height:
            raise _invalid("y", f"y must lie on the map (0 to {map_row.height}).")

    def add_pin(self, map_id: str, data: PinCreate) -> PinWriteResult:
        map_row = self.map(map_id)
        self._check_inside(map_row, data.x, data.y)
        self._check_pin(
            map_row, target_id=data.target_entity_id, label=data.label,
            child_map_id=data.child_map_id, timeline_id=data.timeline_id,
            valid_from=data.valid_from, valid_to=data.valid_to,
        )  # fmt: skip
        pin = MapPin(
            map_id=map_row.id, target_entity_id=data.target_entity_id, label=data.label,
            x=data.x, y=data.y, icon=data.icon,
            color=data.color.lower() if data.color else None, child_map_id=data.child_map_id,
            visibility=data.visibility, timeline_id=data.timeline_id,
            valid_from_spec=data.valid_from, valid_to_spec=data.valid_to,
        )  # fmt: skip
        self.session.add(pin)
        self.session.flush()
        if pin.timeline_id is not None:
            writer = TimeWriter(self.context)
            self._write_validity(writer, pin, set(SLOTS))
            writer.propagate(path="valid_from")
        return PinWriteResult(
            pin=self._pin_outs([pin])[0], affected=self._pin_affected(map_row, pin)
        )

    def update_pin(self, pin_id: str, data: PinUpdate) -> PinWriteResult:
        pin = self.pin(pin_id)
        self._check_revision(data.revision, pin.revision, "pin")
        if pin.overrides_id is not None:
            raise _invalid("pin_id", "An override changes through the branches module.",
                           "override_not_allowed")  # fmt: skip
        map_row = self.map(pin.map_id)
        sent = data.model_fields_set - {"revision", "suppress"}

        def value(name: str) -> Any:
            return getattr(data, name) if name in sent else getattr(pin, _column(name))

        self._check_pin(
            map_row, target_id=value("target_entity_id"), label=value("label"),
            child_map_id=value("child_map_id"), timeline_id=value("timeline_id"),
            valid_from=value("valid_from"), valid_to=value("valid_to"),
        )  # fmt: skip
        self._check_inside(map_row, value("x"), value("y"))
        for name in ("target_entity_id", "label", "icon", "child_map_id", "timeline_id"):
            if name in sent:
                setattr(pin, name, getattr(data, name))
        for name in ("x", "y", "visibility"):
            if name in sent and getattr(data, name) is not None:
                setattr(pin, name, getattr(data, name))
        if "color" in sent:
            pin.color = data.color.lower() if data.color else None
        if "valid_from" in sent:
            pin.valid_from_spec = data.valid_from
        if "valid_to" in sent:
            pin.valid_to_spec = data.valid_to
        if pin.valid_from_spec is None and pin.valid_to_spec is None:
            pin.valid_from_t = pin.valid_to_t = None
            pin.time_status = None
        self.session.flush()
        changed = {slot for slot in SLOTS if slot in sent or "timeline_id" in sent}
        if changed:
            writer = TimeWriter(self.context)
            self._write_validity(writer, pin, changed)
            if "valid_from" in changed:
                sync_starts(self.context, writer, RECORD, pin)
            writer.propagate(path="valid_from")
        return PinWriteResult(
            pin=self._pin_outs([pin])[0], affected=self._pin_affected(map_row, pin)
        )

    def trash_pin(self, pin_id: str) -> PinWriteResult:
        """The pin (and its branch overrides) to the trash."""
        pin = self.pin(pin_id)
        now = utc_now()
        pin.deleted_at = now
        for override in self.session.scalars(
            select(MapPin).where(MapPin.overrides_id == pin.id, MapPin.deleted_at.is_(None))
        ):
            override.deleted_at = now
        self.session.flush()
        map_row = self.session.get(Map, pin.map_id)
        assert map_row is not None
        return PinWriteResult(
            pin=self._pin_outs([pin])[0], affected=self._pin_affected(map_row, pin)
        )

    def _write_validity(
        self, writer: TimeWriter, pin: Placed, slots: set[str], record: str = RECORD
    ) -> None:
        for slot in sorted(slots):
            spec = pin.valid_from_spec if slot == "valid_from" else pin.valid_to_spec
            writer.set_spec(record, pin.id, slot, spec)

    # --- regions --------------------------------------------------------------------------------

    def region(self, region_id: str) -> MapRegion:
        row = self.session.scalars(
            select(MapRegion).where(MapRegion.id == region_id, *self._region_conditions(MapRegion))
        ).one_or_none()
        if row is None:
            raise NotFoundError(f"No region {region_id}.")
        self.map(row.map_id)
        return row

    def _check_points(self, map_row: Map, points: Sequence[Sequence[float]]) -> None:
        for index, (x, y) in enumerate(points):
            if x > map_row.width or y > map_row.height:
                raise _invalid(
                    f"points.{index}",
                    f"Every point must lie on the map (0 to {map_row.width} by {map_row.height}).",
                )

    def add_region(self, map_id: str, data: RegionCreate) -> RegionWriteResult:
        map_row = self.map(map_id)
        self._check_points(map_row, data.points)
        self._check_pin(
            map_row, target_id=data.target_entity_id, label=data.label, child_map_id=None,
            timeline_id=data.timeline_id, valid_from=data.valid_from, valid_to=data.valid_to,
            what="region",
        )  # fmt: skip
        region = MapRegion(
            map_id=map_row.id, target_entity_id=data.target_entity_id, label=data.label,
            points=[list(point) for point in data.points],
            color=data.color.lower() if data.color else None, visibility=data.visibility,
            timeline_id=data.timeline_id, valid_from_spec=data.valid_from,
            valid_to_spec=data.valid_to,
        )  # fmt: skip
        self.session.add(region)
        self.session.flush()
        if region.timeline_id is not None:
            writer = TimeWriter(self.context)
            self._write_validity(writer, region, set(SLOTS), REGION_RECORD)
            writer.propagate(path="valid_from")
        return RegionWriteResult(
            region=self._region_outs([region])[0], affected=self._pin_affected(map_row, region)
        )

    def update_region(self, region_id: str, data: RegionUpdate) -> RegionWriteResult:
        region = self.region(region_id)
        self._check_revision(data.revision, region.revision, "region")
        if region.overrides_id is not None:
            raise _invalid("region_id", "An override changes through the branches module.",
                           "override_not_allowed")  # fmt: skip
        map_row = self.map(region.map_id)
        sent = data.model_fields_set - {"revision", "suppress"}

        def value(name: str) -> Any:
            return getattr(data, name) if name in sent else getattr(region, _column(name))

        self._check_pin(
            map_row, target_id=value("target_entity_id"), label=value("label"),
            child_map_id=None, timeline_id=value("timeline_id"),
            valid_from=value("valid_from"), valid_to=value("valid_to"), what="region",
        )  # fmt: skip
        if data.points is not None:
            self._check_points(map_row, data.points)
            region.points = [list(point) for point in data.points]
        for name in ("target_entity_id", "label", "timeline_id"):
            if name in sent:
                setattr(region, name, getattr(data, name))
        if "visibility" in sent and data.visibility is not None:
            region.visibility = data.visibility
        if "color" in sent:
            region.color = data.color.lower() if data.color else None
        if "valid_from" in sent:
            region.valid_from_spec = data.valid_from
        if "valid_to" in sent:
            region.valid_to_spec = data.valid_to
        if region.valid_from_spec is None and region.valid_to_spec is None:
            region.valid_from_t = region.valid_to_t = None
            region.time_status = None
        self.session.flush()
        changed = {slot for slot in SLOTS if slot in sent or "timeline_id" in sent}
        if changed:
            writer = TimeWriter(self.context)
            self._write_validity(writer, region, changed, REGION_RECORD)
            if "valid_from" in changed:
                sync_starts(self.context, writer, REGION_RECORD, region)
            writer.propagate(path="valid_from")
        return RegionWriteResult(
            region=self._region_outs([region])[0], affected=self._pin_affected(map_row, region)
        )

    def trash_region(self, region_id: str) -> RegionWriteResult:
        """The region (and its branch overrides) to the trash."""
        region = self.region(region_id)
        now = utc_now()
        region.deleted_at = now
        for override in self.session.scalars(
            select(MapRegion).where(
                MapRegion.overrides_id == region.id, MapRegion.deleted_at.is_(None)
            )
        ):
            override.deleted_at = now
        self.session.flush()
        map_row = self.session.get(Map, region.map_id)
        assert map_row is not None
        return RegionWriteResult(
            region=self._region_outs([region])[0], affected=self._pin_affected(map_row, region)
        )

    # --- affected -------------------------------------------------------------------------------

    def _affected(self, entity_ids: Iterable[str]) -> Affected:
        ids = sorted(set(entity_ids))
        dimensions = self.session.scalars(
            select(Entity.dimension_id).where(Entity.id.in_(ids), Entity.dimension_id.is_not(None))
        )
        affected = Affected(
            entities=ids,
            dimensions=sorted({d for d in dimensions if d is not None}),
            time_changed=False,
            search_changed=False,
        )
        return report_time(self.session, self.context.registry, affected)

    def _pin_affected(self, map_row: Map, pin: Placed) -> Affected:
        return self._affected(
            i for i in (map_row.location_id, pin.target_entity_id) if i is not None
        )


def _column(name: str) -> str:
    return {"valid_from": "valid_from_spec", "valid_to": "valid_to_spec"}.get(name, name)


def purge_maps(context: VaultContext, entity: Entity) -> None:
    """Before an entity is purged: its maps (a location), the pins pointing at it or living in
    it (a timeline) go with it."""
    session = context.session
    for model in (MapPin, MapRegion):
        rows = session.scalars(
            select(model).where(
                or_(model.target_entity_id == entity.id, model.timeline_id == entity.id)
            )
        )
        for row in rows:
            session.delete(row)
    session.flush()
    for row in session.scalars(select(Map).where(Map.location_id == entity.id)):
        session.delete(row)
    session.flush()


__all__ = [
    "MAP_VISIBILITY",
    "PIN_OVERRIDES",
    "PIN_SLOTS",
    "PIN_VISIBILITY",
    "REGION_OVERRIDES",
    "REGION_SLOTS",
    "REGION_VISIBILITY",
    "Maps",
    "map_out",
    "purge_maps",
]
