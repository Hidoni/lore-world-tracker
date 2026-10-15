# Module: `maps` — Interactive maps

> Image-based maps attached to locations, with pins for locations, events or any entity,
> drill-down into nested maps, and time-aware pins that follow the as-of cursor. Covers R-MAP-1.

## Summary

| | |
|---|---|
| Module id | `maps` |
| Depends on | `locations`, `media` |
| Default enabled | yes |
| Milestone | M10 |

## Kinds

None. Maps belong to locations.

## Tables

`maps_maps`:

| Column | Notes |
|--------|-------|
| `id` | |
| `location_id` → entities | the location this map depicts (a location can have several maps: political, topographic, historical…) |
| `media_id` | image (via media module) |
| `name`, `description` | |
| `width`, `height` | image pixel size (copied from media at creation) |
| `scale` JSON NULL | optional `{units_per_pixel: decimal string, unit: "km"}` |
| `sort_key`, `visibility`, `revision`, timestamps, `deleted_at` | |

`maps_pins`:

| Column | Notes |
|--------|-------|
| `id`, `map_id` | |
| `target_entity_id` NULL | location/event/character/any; NULL = label-only pin |
| `label` NULL | defaults to the target's name |
| `x`, `y` | image pixel coordinates (REAL; spatial, not time) |
| `icon`, `color` | defaults from the target kind |
| `child_map_id` NULL | drill-down target (default: the target location's first map) |
| `visibility` | |
| `timeline_id` NULL, `overrides_id`, `valid_from/to spec+t`, `time_status` | explicit validity (optional). Without it the pin follows the **target's existence** at the cursor |
| `revision`, timestamps, `deleted_at` | |

## API

- `GET|POST /m/maps/maps?location=`, `GET|PATCH|DELETE /m/maps/maps/{id}`
- `GET /m/maps/maps/{id}?timeline=&at=`: map plus pins visible as of the moment (existence-aware)
- `POST /m/maps/maps/{id}/pins`, `PATCH|DELETE /m/maps/pins/{id}`
- `GET /m/maps/entities/{id}/pins`: where an entity is pinned (for "show on map")

## UI

- **Map panel** on location pages (map switcher if several), and a full-screen map page
  `/m/maps/maps/{id}`.
- Leaflet with `CRS.Simple` and an image overlay (bounds = image size). Markers use kind icons
  and colors. Clustering kicks in when crowded.
- View mode: hover shows a tooltip, click opens a popover (name, summary, dates, "open page",
  "drill into map"). Breadcrumbs show nested maps (continent → country → city).
- Edit mode: click to add a pin (entity search with "create location here"), drag to move,
  per-pin validity/visibility, "pin all child locations" helper (places unplaced children in a
  tray to drag in).
- Layers: toggle by kind. Time cursor integration: pins not existing at the cursor are hidden or
  ghosted (toggle).
- Entity pages of pinned entities get "Show on map".

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `maps.pin_target_missing` | warning | pin target trashed/hidden |
| `maps.pin_outside_map_location` | off | pinned location is not inside the map's location tree |

## Visibility, publish

Pins are reader-visible iff the pin, the map, the map's location and the target (if any) are
visible. Publish copies only maps with visible media.

## Disabling / removal notes

Disabling hides maps and pins. Data and media are kept.

## Implementation notes (#128)

- **Maps** copy their image's size at creation (and when the image changes) and record the use
  with `media.api.reference(media_id, location_id, "map", visibility)`: the location's live maps'
  images, each at its most visible map's level. Readers then see the image exactly when they see a
  map using it, and the media collection never takes it. Only raster images are accepted.
- **Pins** are within the image (`0 ≤ x ≤ width`, `0 ≤ y ≤ height`); one without a target needs a
  label. A validity needs a timeline of the map location's dimension; such a pin is a time-bound
  record (`TimelineView`, slots `maps.pin`: `valid_from`, `valid_to`) and branches override its
  `valid_to` through `POST /m/branches/overrides` (`record_type: maps.pin`). Without a validity a
  pin is timeless and follows its target at the cursor: existence facts (`possible` shows it as
  possible, `unknown` shows it), an event while it happens (start to end, inclusive), a label
  always.
- `GET /m/maps/maps/{id}` returns the pins of `timeline` (default: the prime timeline of the
  location's dimension) and, with `at`, only those there then. `drill_map_id` is `child_map_id` or
  the target location's first map (by `sort_key`, then creation); `breadcrumbs` list the first map
  of each ancestor location, outermost first.
- **Rules:** `maps.pin_target_missing` also reports a private target on a pin and map that
  aren't private (readers lose the pin).
- **Purge:** purging an entity removes the pins pointing at it or living in it (a timeline) and
  the maps of it (a location). Trashing a map trashes its pins; trashing a pin trashes its
  overrides.
- **Publish:** `published_maps` lists the maps readers see; their images are copied by the media
  module's contributor (#140 wires both).
- The sample world has a map of Thalassa (pins: the city of Varn drilling into its map, the
  Sundering, a label) and one of Varn (the Spire, the Old Harbor until the Sundering).

## Future ideas

Deep-zoom tiling for very large images; polygons/regions for territories over time (linked to
`groups.controls`); paths/routes for journeys, animated along time or worldlines; distance
measurement using `scale`; fantasy-map generators.
