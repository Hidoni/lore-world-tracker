# Module: `correspondences` — Cross-dimension time

> Relates moments between dimensions whose time flows independently, possibly at different rates
> (portals, travelers, Narnia-style realms) (D7). The math is in the chronology engines and the
> tables are core (`time-model.md` §12, `data-model.md` §5.7). This module provides API, UI and
> rules. Covers R-XD-1…3.

## Summary

| | |
|---|---|
| Module id | `correspondences` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M9 |

## Tables

Core: `correspondences`, `correspondence_points`. Sync points are time slots (`sync_point.a`,
`sync_point.b`) and take part in propagation, so they can be anchored to events.

## API

- `GET|POST /m/correspondences` (`{dimension_a_id, dimension_b_id, name, extrapolation,
  rate_before?, rate_after?, points: [{a: TimePoint, b: TimePoint, note}]}`)
- `GET|PATCH|DELETE /m/correspondences/{id}` (points are replaced as a whole on PATCH and
  validated for strict monotonicity after resolution)
- `GET /m/correspondences/map?from_dimension=&to_dimension=&t=`: the mapped moment, the path used
  (list of correspondence ids), and `defined: false` when outside the mapping/extrapolation or the
  target bounds.
- `GET /m/correspondences/map-batch` (POST body with many moments), used by timeline dimension
  lanes.

### Implemented (#118)

- Core: `correspondences` and `correspondence_points` (each point keeps the dimension of each
  side, `a_dimension_id`/`b_dimension_id`, and its `position`), the `sync_point` slot provider
  (slots `a` and `b`, each resolving in its own dimension: `SlotDef.dimension_column`),
  `lore.core.time.correspondences` (compiling stored points through the engine, the graph of
  dimensions and shortest-path mapping) and the hard rule `core.correspondence.non_monotonic`
  (subjects: both dimensions), which refuses a change that moves an anchor event so the sync
  points no longer increase in both dimensions.
- The module: the API above (`lore.modules.correspondences`), and the warning
  `correspondences.inconsistent_paths`: a correspondence and the shortest other path between its
  dimensions disagree at one of its sync points by a whole base unit or more (compared exactly,
  without the flooring of each step).
- A sync point may only be anchored to its own side's dimension (`422`); cross-dimension anchors
  in general (`time-model.md` §5.2) are not resolved through correspondences yet.
- The sample world's "The Drowned Gate": Aetheria ↔ The Dreaming, from the Sundering, a day here
  a year there.

## UI

- **Correspondence editor** (from the dimension overview page): choose the other dimension, then
  list sync points with a `TimePointPicker` per side (each in its own dimension's calendars),
  extrapolation settings and rates (`BigNumberInput` rationals with helpers like "1 day here = 1
  year there"). A preview chart plots the piecewise mapping (log scale option) and a conversion
  tester.
- **Event pages:** "Concurrently in…" section listing the mapped moment in each reachable
  dimension (formatted in that dimension's default calendar). It is hidden when undefined.
- **Timeline view:** "Add dimension lane" shows another dimension's events mapped onto this
  axis (warped), with a secondary tick row in the other dimension's calendar.
- **Dimension overview:** a small graph of connected dimensions.
- Implementation (#119, `frontend/src/modules/correspondences`): the dimension overview gets a
  Correspondences section (`dimensionSections`) listing the dimension's correspondences, the
  connected dimensions (this one in the middle, the rest of its connected group around it; a node
  opens that dimension) and, for authors, new / edit / delete. The editor previews a draft as
  soon as every sync point's moments are known in the browser (absolute or calendar anchors;
  relative ones resolve on save): the TS engine validates it like the server (points moving
  backwards are flagged before saving), the chart plots the mapping between the sync points
  (widened when extrapolating; linear or log scale via `toLogPx`; hovering shows the pair) and
  the tester maps a moment either way. The rate helper measures one level of each side's first
  display calendar at the first sync point ("1 month there" is that month), and sets both rates.
  "Concurrently in…" (event pages, side) maps the event's start to every reachable dimension in
  the browser, through the same shortest paths as `GET /map`, and is hidden when nothing
  corresponds. Dimension lanes are core (`frontend.md` §9.5).

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `core.correspondence.non_monotonic` | hard (core) | sync points not strictly increasing in both dimensions |
| `correspondences.inconsistent_paths` | warning | two paths between the same dimensions disagree at a sync point by more than rounding |

## Disabling / removal notes

Disabling hides correspondences, the "concurrently in" displays and dimension lanes. Cross-
dimension causality checks fall back to "skip".

## Future ideas

Non-linear interpolation (curves), correspondences that differ per timeline, travel-time
calculators for worldline jumps.
