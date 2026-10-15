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
  worldline (`implicit: true`), with exact subjective starts and ends (#120).
- `PUT /m/worldlines/entities/{id}/segments`: replaces the ordered list atomically (`seq` is the
  list's order; validation: the kind can have a worldline, each timeline is one of the segment's
  dimension, anchors stay in that dimension, `start ≤ end` after resolution, rates > 0).
  Propagation runs; segments anchored to events move with them. An empty list returns to the
  implicit worldline. Full shapes: `api.md`.
- `GET /m/worldlines/entities/{id}/personal-timeline?include=participations,existence,jumps`:
  items in subjective order with `subjective_t` (exact), formatted age (calendar `diff` in the
  personal clock dimension's default calendar), segment ids and jump markers.
- `GET /m/worldlines/entities/{id}/presence?dimension=&timeline=&t=`: segments covering a moment
  (can be several).
- Visibility: readers see the segments whose own visibility, dimension and timeline they see;
  subjective time and ages count only those, jump and anchor events they can't see are left out,
  and ages are formatted only in a default calendar they see.
- `POST /m/worldlines/entities/{id}/time-travel` (wizard helper): `{departure: {event_id | time point},
  destination: {dimension, timeline | new_branch: {name, branch_point}, arrival: TimePoint}}`
  splits/creates segments, optionally creates a branch (`branches` module required for
  `new_branch`) and departure/arrival events, all in one transaction.
  - Implementation (#121, `travel.py`): the last segment (in worldline order) covering the
    departure is cut there (its end anchored to the departure event, so it moves with it), the
    rest of it is no longer lived, and the new segment (arrival to `until`, default the end of
    time, at `rate`) comes right after it; later segments stay. An implicit worldline becomes
    explicit first. The new branch's parent defaults to the destination's prime, its branch
    point to the arrival. Created events are instants (branch-only in a branch); the entity
    takes part in its departure and arrival events with roles `departs`/`arrives` and the
    segment in `data.segment_id`. Errors of the rewritten segments name the wizard's fields.
- Personal timeline items carry `assignment` (`chosen`, `implied`, `ambiguous`, `absent`, §11.4);
  items at the same subjective moment keep worldline order.

## UI

Implemented in `frontend/src/modules/worldlines/` (#122).

- **Worldline panel** on pages of kinds with `can_have_worldline`: an ordered segment list
  (dimension, span, rate, note) with add, edit, split, reorder (move up/down) and remove actions,
  plus a **Time travel…** wizard and **Clear worldline** (back to the implicit worldline). The list
  is saved as a whole (`PUT …/segments`); errors of one segment show in its dialog. An implicit
  worldline is shown as a note ("lives its lifespan in order"); adding a segment replaces it.
- **Time travel… wizard:** the departure (a moment, optionally recording a departure event, or an
  existing event), the destination (dimension and timeline, or a new branch when `branches` is
  active), arrival, optional "stays until", rate and an optional arrival event; one
  `POST …/time-travel`.
- **Personal timeline view** (`/m/worldlines/entities/{id}`): a horizontal axis of subjective time
  (age) with experienced events in order, jumps drawn as breaks in the axis annotated with where
  they lead (a moment, a dimension and timeline), and a **List view** (a table) for accessibility. Ambiguous
  participations are marked "which visit?".
- **Participants:** on an event's participants section, a time traveler that several segments
  cover gets a "Which visit" select; choosing one sets the participation's `data.segment_id`
  (`core/events/visit-choice.tsx`, shown only when `worldlines` is active).
- **Timeline layer** (`timelineLayers`, `worldlines.jumps`): a **Jumps** popover chooses entities;
  for each, an arc from departure to arrival when both are in the viewed dimension, and an edge
  marker at the end that is here when the jump leads to or comes from another dimension.
- **Age displays:** the character life panel shows the lived age ("lived 150 seconds") from the
  personal timeline when the character has an explicit worldline.

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
entity: an effect that starts before its cause isn't reported when someone takes part in both
and lives the cause first (`consistency.md` §6). Jump events must span the segment end (departure)
or start (arrival) they document. A self-encounter needs a real overlap (a split's shared end
isn't one) and belongs to the timeline of the two segments. A causal loop is a cycle of
`core.causes` links, reported once.

## Disabling / removal notes

Disabling falls back to implicit worldlines everywhere (segments are kept but ignored) and hides
the panel, view and rules.

## Future ideas

Subjective calendars (a traveler's personal calendar), memory/knowledge tracking ("what does X
know at subjective age N"), animated journeys on maps.
