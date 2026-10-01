# Module: `worldlines` — Personal timelines (time travel)

> Entities, characters above all, whose own experience of time differs from the world's:
> time travelers, dimension hoppers, beings in stasis (D7). The model (segments, subjective time,
> implicit worldlines) is in `time-model.md` §11 and the table is core. This module provides API,
> UI and rules. Covers R-WL-1…4.

## Summary

| | |
|---|---|
| Module id | `worldlines` |
| Depends on | – (UI focuses on `characters`; any kind with capability `can_have_worldline`) |
| Default enabled | yes |
| Milestone | M9 |

## Tables

Core: `worldline_segments`. Segment `start`/`end` are time slots (propagated, anchorable), and
segments are timeline-bound (branch inheritance and overrides apply).

## API

- `GET /m/worldlines/entities/{id}/segments`: explicit segments, or the computed implicit
  worldline (`implicit: true`).
- `PUT /m/worldlines/entities/{id}/segments`: replaces the ordered list atomically (validation:
  `seq` contiguous, each segment `start ≤ end`, within bounds, rates > 0). Propagation runs.
- `GET /m/worldlines/entities/{id}/personal-timeline?include=participations,existence,jumps`:
  items in subjective order with `subjective_t` (exact), formatted age (calendar `diff` in the
  personal clock dimension's default calendar), segment ids and jump markers.
- `GET /m/worldlines/entities/{id}/presence?dimension=&timeline=&t=`: segments covering a moment
  (can be several).
- `POST /m/worldlines/entities/{id}/time-travel` (wizard helper): `{departure: {event_id | time point},
  destination: {dimension, timeline | new_branch: {name, branch_point}, arrival: TimePoint}}`
  splits/creates segments, optionally creates a branch (`branches` module required for
  `new_branch`) and departure/arrival events, all in one transaction.

## UI

- **Worldline panel** on pages of kinds with `can_have_worldline`: an ordered segment list
  (dimension, timeline, start, end, rate, jump events) with add, split and reorder actions, plus a
  **Time travel…** wizard.
- **Personal timeline view** (`/m/worldlines/entities/{id}`): a horizontal axis of subjective time
  (age) with experienced events in order, jumps drawn as discontinuities annotated with "to 1950,
  Branch 'Vey's Return'", and existence changes. A list mode is available for accessibility.
- **Participant dialog:** when an entity with explicit segments is added to an event that several
  segments cover, the dialog asks which visit (segment) it is.
- **Timeline layer:** for selected entities, jump arcs from departure to arrival moments
  (within the same dimension; cross-dimension jumps show edge markers).
- **Age displays:** wherever "age at event" is shown, subjective age is used if a worldline
  exists.

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `worldlines.absent_participant` | warning | participation not covered by any segment |
| `worldlines.ambiguous_participation` | warning | several segments cover it and no `segment_id` is set |
| `worldlines.jump_event_mismatch` | warning | departure/arrival events don't coincide with segment end/start |
| `worldlines.self_encounter` | off (info) | two segments of the same entity overlap in the same timeline (meets itself) |
| `worldlines.causal_loop` | off (info) | a causal chain reaches back to its own cause (bootstrap paradox) |

When a worldline exists, `core.event.participant_not_existing` defers to these rules, and
`core.event.effect_before_cause` uses subjective order for events experienced by the same
entity.

## Disabling / removal notes

Disabling falls back to implicit worldlines everywhere (segments are kept but ignored) and hides
the panel, view and rules.

## Future ideas

Subjective calendars (a traveler's personal calendar), memory/knowledge tracking ("what does X
know at subjective age N"), animated journeys on maps.
