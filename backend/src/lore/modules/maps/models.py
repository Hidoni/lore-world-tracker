"""The maps module's tables (``docs/modules/maps.md``, Tables).

- ``maps_maps``: an image (a media item) depicting a location; a location may have several.
- ``maps_pins``: a point on a map, at image pixel coordinates (``x``, ``y``: spatial, not time),
  for any entity or none (a label). A pin with an explicit validity is time-bound in its
  ``timeline_id`` (``valid_from``/``valid_to`` slots, branch overrides through ``overrides_id``);
  without one it is timeless and follows its target's existence at the cursor.
- ``maps_regions`` (#154): a polygon on a map (``points``: image pixel coordinates), for an
  entity (usually a location: the territory) or a label, time-bound like a pin. Readers see who
  controls its target (``groups.controls`` links) at the cursor.
"""

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lore.chronology.schema import TimePoint
from lore.core.db.base import (
    Base,
    IdMixin,
    RevisionMixin,
    SoftDeleteMixin,
    TimestampsMixin,
    VisibilityMixin,
)
from lore.core.time import (
    TimeBound,
    moment_column,
    register_time_bound,
    spec_column,
    status_column,
)

RESTRICT = "RESTRICT"
CASCADE = "CASCADE"
SET_NULL = "SET NULL"


class Map(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    __tablename__ = "maps_maps"

    location_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.id", ondelete=RESTRICT))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="", server_default="")
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    scale: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    sort_key: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("ix_maps_maps_location_id", "location_id"),)


class MapPin(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    __tablename__ = "maps_pins"

    map_id: Mapped[str] = mapped_column(ForeignKey("maps_maps.id", ondelete=CASCADE))
    target_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT)
    )
    label: Mapped[str | None] = mapped_column(String)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    icon: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    child_map_id: Mapped[str | None] = mapped_column(ForeignKey("maps_maps.id", ondelete=SET_NULL))
    timeline_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    overrides_id: Mapped[str | None] = mapped_column(ForeignKey("maps_pins.id", ondelete=CASCADE))
    valid_from_spec: Mapped[TimePoint | None] = spec_column()
    valid_from_t: Mapped[int | None] = moment_column()
    valid_to_spec: Mapped[TimePoint | None] = spec_column()
    valid_to_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()

    __table_args__ = (
        Index("ix_maps_pins_map_id", "map_id"),
        Index("ix_maps_pins_target_entity_id", "target_entity_id"),
        Index("ix_maps_pins_timeline_start", "timeline_id", "valid_from_t"),
        Index("ix_maps_pins_overrides_id", "overrides_id"),
    )


class MapRegion(IdMixin, VisibilityMixin, RevisionMixin, TimestampsMixin, SoftDeleteMixin, Base):
    __tablename__ = "maps_regions"

    map_id: Mapped[str] = mapped_column(ForeignKey("maps_maps.id", ondelete=CASCADE))
    target_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete=RESTRICT)
    )
    label: Mapped[str | None] = mapped_column(String)
    points: Mapped[list[list[float]]] = mapped_column(JSON)
    color: Mapped[str | None] = mapped_column(String)
    timeline_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete=RESTRICT))
    overrides_id: Mapped[str | None] = mapped_column(
        ForeignKey("maps_regions.id", ondelete=CASCADE)
    )
    valid_from_spec: Mapped[TimePoint | None] = spec_column()
    valid_from_t: Mapped[int | None] = moment_column()
    valid_to_spec: Mapped[TimePoint | None] = spec_column()
    valid_to_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()

    __table_args__ = (
        Index("ix_maps_regions_map_id", "map_id"),
        Index("ix_maps_regions_target_entity_id", "target_entity_id"),
        Index("ix_maps_regions_timeline_start", "timeline_id", "valid_from_t"),
        Index("ix_maps_regions_overrides_id", "overrides_id"),
    )


# Validity is open on both sides (a pin with only an end was there since the beginning).
for _model in (MapPin, MapRegion):
    register_time_bound(
        TimeBound(_model, start="valid_from_t", end="valid_to_t", open_start=True, open_end=True)
    )
