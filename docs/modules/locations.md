# Module: `locations` — Locations

> Places from galaxies to rooms, nested inside each other, and usable as event sites. Covers
> R-LOC-1.

## Summary

| | |
|---|---|
| Module id | `locations` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M6 |

## Kinds

| Kind | Label / plural | Icon | Allowed parents | Capabilities |
|------|----------------|------|-----------------|--------------|
| `location` | Location / Locations | `map-pin` | `location`, `misc` | body, existence (founded/destroyed), multiversal (e.g. "the Void Between Worlds") |

### Fields (`location`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `location_type` | `enum` | no | public | universe, galaxy, star_system, star, planet, moon, plane, continent, ocean, region, country, province, city, town, village, district, building, room, landmark, natural_feature, other |
| `type_detail` | `text` | no | public | free refinement ("fortress-monastery") |
| `population` | `integer` | **yes** | public | |
| `climate` | `text` | yes | public | |
| `area` | `measurement` | no | public | |
| `coordinates` | `text` | no | public | free-form (real geo is a non-goal) |

Name changes over time use `core.name` facts.

## Link types

| Key | Source → target | Labels | Symmetric | Temporal | Data |
|-----|-----------------|--------|-----------|----------|------|
| `locations.event_site` | event → location | took place at / site of | no | never | – |
| `locations.resides_in` | any (not location) → location | resides in / residents | no | optional | `{kind: home|base|prison|exile|other}` |
| `locations.origin` | any → location | originates from / origin of | no | never | – |
| `locations.connected_to` | location ↔ location | connected to | yes | optional | `{kind: road|river|sea_route|portal|tunnel|other}`. Portals may cross dimensions. |

Political control lives in `groups.controls` (groups module).

## Tables

None.

## API

- `GET /m/locations/tree?dimension=&root=&depth=`: lazily expandable containment tree with types
  and child counts.
- `GET /m/locations/{id}/events?include_descendants=true&timeline=&from=&to=`: events at this
  location (and its sub-locations), time-ordered ("what happened here").
- `GET /m/locations/{id}/residents?timeline=&at=`: residents as of a moment.

## UI

- Sidebar section "Locations" (containment tree, type icons).
- Location page panels: **Contents** (child locations by type), **Events here** (time-ordered,
  with descendants toggle), **Residents** (as-of), **Connections**.
- A **location tree view** page (`/m/locations/tree`): a collapsible outline with filters by type.
- Event page: a "Location" quick field (sets `locations.event_site`).

Implementation (#90): `backend/src/lore/modules/locations/` and `frontend/src/modules/locations/`.

- The tree endpoint reads the core tree (`/tree` with `group_by=location_type`), so roots,
  visibility and the trash work as in the sidebar. "Events here" looks for visible, live
  locations below the location through visible parents only (a hidden location hides what it
  contains), up to 5,000, and lists each event once with all of its listed sites.
- `resides_in` accepts any source kind; "not a location" is a convention for now.
- UI: the kind's config sets `iconBy` (an icon per type) for the sidebar tree and lists. The panels are
  Contents (`/m/locations/tree?root=`), Events here (the time context's timeline, with an
  "Include places inside" toggle), Residents and Connections (marking ends in other
  dimensions). The tree page is `/v/<vault>/m/locations/tree`, linked from Contents and the
  command palette, with a type filter that keeps ancestors of matches. The event page's
  "Location" side panel sets, replaces and removes `event_site` links.
- The sample world has The Shimmering Reach (galaxy) → … → Hall of Tides (room) and The Void
  Between Worlds (plane) with event sites, an origin, a resident and a portal.
- Consistency rules (#106): below.

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `locations.event_at_nonexistent_location` | warning | event's site doesn't exist at the event start |
| `locations.child_outside_parent_existence` | warning | child location exists outside the parent's existence |

Implemented in `lore.modules.locations.consistency` (#106, `consistency.md` §6): an event's
start within its `event_site`'s existence; each existence period of a location within the
existence of its parent location (one finding per pair and timeline).

## Search, graph, visibility

Standard entity indexing. In the graph, location nodes are colored by kind and `connected_to`
edges are dashed.

## Disabling / removal notes

Disabling hides locations, `event_site`/`resides_in`/`origin`/`connected_to` links, and the
`maps` module (dependency). Removal would convert locations to `misc` (category "Location").

## Future ideas

Distance/travel-time model between connected locations; territories over time (with maps);
climate/seasons per location tied to calendar overlays.
