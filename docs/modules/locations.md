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

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `locations.event_at_nonexistent_location` | warning | event's site doesn't exist at the event start |
| `locations.child_outside_parent_existence` | warning | child location exists outside the parent's existence |

## Search, graph, visibility

Standard entity indexing. In the graph, location nodes are colored by kind and `connected_to`
edges are dashed.

## Disabling / removal notes

Disabling hides locations, `event_site`/`resides_in`/`origin`/`connected_to` links, and the
`maps` module (dependency). Removal would convert locations to `misc` (category "Location").

## Future ideas

Distance/travel-time model between connected locations; territories over time (with maps);
climate/seasons per location tied to calendar overlays.
