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
