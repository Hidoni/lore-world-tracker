# Module: `maps` — Interactive maps

> Image-based maps attached to locations, with pins for locations, events or any entity,
> drill-down into nested maps, time-aware pins that follow the as-of cursor, and regions
> (territories over time, colored by who controls them). Covers R-MAP-1.

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

`maps_regions` (#154):

| Column | Notes |
|--------|-------|
| `id`, `map_id` | |
| `target_entity_id` NULL | the place the region is (whose `groups.controls` controllers color it); NULL = label-only region |
| `label` NULL | defaults to the target's name |
| `points` JSON | the outline: `[[x, y], …]` image pixels, 3 to 2000 corners, in order |
| `color` NULL | NULL: the first controller's color, else the target's |
| `visibility` | |
| `timeline_id` NULL, `overrides_id`, `valid_from/to spec+t`, `time_status` | explicit validity, as for pins |
| `revision`, timestamps, `deleted_at` | |

## API

- `GET|POST /m/maps/maps?location=`, `GET|PATCH|DELETE /m/maps/maps/{id}`
- `GET /m/maps/maps/{id}?timeline=&at=`: map plus pins visible as of the moment (existence-aware)
- `POST /m/maps/maps/{id}/pins`, `PATCH|DELETE /m/maps/pins/{id}`
- `POST /m/maps/maps/{id}/regions`, `PATCH|DELETE /m/maps/regions/{id}` (#154); the map's
  `regions` come with its pins, each with its `controllers`
- `GET /m/maps/entities/{id}/pins`: where an entity is pinned (for "show on map")

## UI

- **Map panel** on location pages (map switcher if several), and a full-screen map page
  `/m/maps/maps/{id}` (`/m/maps/maps/{id}/pins/{pin}` opens it with that pin selected and
  centered). Drilling into a map of another location from the panel opens the page.
- Leaflet with `CRS.Simple` and an image overlay (bounds = image size). Markers use kind icons
  and colors. Clustering kicks in when crowded.
- Deep zoom (#162): a map whose image's longer side is above 8,192 px (`tile_levels` not null)
  is drawn as the media module's tiles (a Leaflet tile layer: zoom `z ≤ 0` shows tile level
  `-z`, closer zooms enlarge level 0) over the image's 1280 px thumbnail, shown while tiles load.
  The CRS puts the image's top left at the origin of Leaflet's pixel grid (transformation
  `(1, 0, -1, height)`), so tiles line up with Leaflet's; the furthest zoom out reaches the
  coarsest level. A static export shows the image whole.
- View mode: hover shows a tooltip, click opens a popover (name, summary, dates, "open page",
  "drill into map"). Breadcrumbs show nested maps (continent → country → city).
- Edit mode: click to add a pin (entity search with "create location here"), drag to move,
  per-pin validity/visibility, "pin all child locations" helper (places unplaced children in a
  tray to drag in).
- Layers: toggle by kind (pins without a target form the "Labels" layer). Time cursor
  integration: pins not existing at the cursor are hidden or ghosted (toggle, "Ghost what isn't
  there"). Ghost mode also loads the pins of the cursor's timeline at any time; pins only
  possibly there (`shown: possible`) are faded in both modes. Without a cursor every pin shows.
- "As a list" (#145, outside edit mode) shows the map as a list for keyboard and screen-reader
  use: the pins shown (the same layers and time cursor), by label, with their kind, whether they
  are there at the cursor, a link to the pinned entity and "Drill into map".
- Entity pages of pinned entities get a "Show on map" side panel (one entry per pin) that opens
  the map at the pin; it is left out on entities pinned nowhere.
- Edit mode (#130; authors, "Edit map"): every pin of the map shows, whenever it stands, and
  markers don't cluster. A click on the map opens "Add a pin" (an entity found by name, a new
  location created there as a child of the map's location, or a label); pins drag to move; a click
  on a pin opens its editor (label, icon, color, the map it drills into, validity with time point
  pickers in the cursor's timeline or the dimension's prime one, visibility, remove). The tray
  beside the map lists the location's child locations not pinned on it yet: drag one onto the map,
  or place it in the middle. The location panel's "New map" names the map and picks or uploads its
  image (the media module's image picker).
- Regions (#154) are filled polygons under the pins, in their own color, else their first
  controller's (who has a `groups.controls` link to the region's place, at the cursor), else the
  place's. They follow the time cursor like pins (hidden or ghosted: faded and dashed) and toggle
  together as the **Regions** layer. A click opens a popover: who controls the place (links), the
  region's dates, "open page". "As a list" lists them after the pins, with their controllers.
- Region editing (the edit mode, "Edit map"): **Draw region**, click the corners, **Finish
  region** (3 corners at least), then pick its place or write a label (the "Add a pin" dialog).
  A click on a region opens its editor (place, label, color, when it stands, visibility,
  **Redraw** the outline, remove); the selected region's corners drag. Leaflet-geoman was
  considered and left out: clicks, draggable corner markers and plain polygons cover it without
  another plugin.
- Leaflet and its clustering plugin load with the first map shown (frontend.md §12); the canvas
  is `modules/maps/views/map-canvas.tsx`, the pin filtering `modules/maps/pins.ts`.

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `maps.pin_target_missing` | warning | pin target trashed/hidden (regions' targets aren't checked) |
| `maps.pin_outside_map_location` | off | pinned location is not inside the map's location tree |

## Visibility, publish

Pins and regions are reader-visible iff the pin (region), the map, the map's location and the
target (if any) are visible. A region's controllers are the visible ones only. Publish copies only maps with visible media.

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
- **Regions** (#154) are checked and stored like pins: corners within the image (`422` path
  `points.<i>`), a target or a label, a validity in a timeline of the location's dimension
  (record type `maps.region`, slots `valid_from`/`valid_to`; branches override `valid_to`), else
  following the target at the cursor. `controllers` are the visible sources of `groups.controls`
  links to the target (valid at the cursor with `at`, at any time without); maps doesn't depend
  on groups, so without it they are empty. Trashing a map trashes its regions; purging removes
  them with their map, target or timeline.
- **Rules:** `maps.pin_target_missing` also reports a private target on a pin and map that
  aren't private (readers lose the pin).
- **Purge:** purging an entity removes the pins pointing at it or living in it (a timeline) and
  the maps of it (a location). Trashing a map trashes its pins; trashing a pin trashes its
  overrides.
- **Publish:** `publish_maps` keeps the maps readers see (their pins follow); their images are
  copied by the media module's contributor. A map's image is visible to readers at its most
  visible map's level, so a private map sharing a public map's image doesn't hide it.
- The sample world has a map of Thalassa (pins: the city of Varn drilling into its map, the
  Sundering, a label, the Kingdom of Varn as a region) and one of Varn (the Spire, the Old Harbor
  until the Sundering).

## Future ideas

Regions that change shape over time (today a new
outline is a new region with its own validity); paths/routes for journeys, animated along time or worldlines; distance
measurement using `scale`; fantasy-map generators.
