# Time model

> **Status: normative.** This is the most important document in the project. Time is the
> backbone of the product (see `docs/product/vision.md`). If code and this spec disagree, either
> the code is wrong or the spec must be updated in the same PR, with the reasoning in the PR body.
> Calendar internals are in `chronology-engine.md` and recurrence internals in `recurrence.md`.

## 1. Overview

```
Vault
 └─ Dimension  (time spec: base unit + duration D)
     ├─ Calendars      (lenses: moment ⇄ date; never own time)
     ├─ Timelines      (prime + branches; each branch forks from a parent at a branch point)
     │    └─ time-bound records: events, facts, temporal links, worldline segments, …
     └─ present moment (narrative "now", optional)

Moment t  = integer number of base units since inception, 0 ≤ t ≤ D   (canonical)
Time point = anchor (absolute | calendar date | relative to a time slot) + precision + approximate
```

Key consequences:

- Everything is ordered and compared by **resolved moments** (integers).
- What the user *typed* is preserved in the **anchor** (D1: calendar edits keep typed dates).
- Anchors can depend on other records (D3); the system keeps a **dependency graph** and
  **propagates** changes transactionally.
- Every time-bound record lives on a **timeline** (D7), so alternate timelines are first class
  from day one, even before the branching UI exists.

## 2. Moments

### 2.1 Definition

A **moment** `t` is an integer with `0 ≤ t ≤ D`, the number of base units elapsed since the
dimension's inception. `t = 0` is the inception, `t = D` is the end ("heat death").

A **span** is `(start, end)` with `start ≤ end`. Occupancy is half-open: the span covers moments
`start ≤ x < end`. When `start = end` the span is an **instant**, and it still "happens at" `start`.
Overlap test: `a.start < b.end && b.start < a.end`. Instants are a special case: an instant at
`x` overlaps a span if `span.start ≤ x < span.end`, and two instants overlap if equal.

### 2.2 Representation

| Layer | Type | Rule |
|-------|------|------|
| Python | `int` | arbitrary precision; never `float`. |
| TypeScript | `bigint` | never `number` for time, except pixel coordinates after viewport projection. |
| JSON / API | decimal string | `^(0|[1-9][0-9]*)$` for moments; signed `^(0|-?[1-9][0-9]*)$` for offsets/years (canonical: no `-0`, no leading zeros). |
| SQLite | `SortableBigInt` (TEXT) | see §2.3. Comparisons in SQL work directly on the encoded text. |

Limits: `D ≤ 10^1000 − 1` (at most 1000 decimal digits). Every moment, duration and offset obeys
the same bound. That is far beyond any physical heat-death figure, even in Planck times.

### 2.3 Sortable key encoding (normative)

For an integer `n ≥ 0` with decimal string `s` (no leading zeros, `"0"` for zero):

```
key(n) = zero_pad(len(s), 4) + s          e.g. 0 → "00010", 7 → "00017", 1023 → "00041023"
```

Byte-wise comparison of keys equals numeric comparison. Columns must use SQLite's default
`BINARY` collation. Decoding strips the 4-character prefix. The SQLAlchemy `TypeDecorator`
`SortableBigInt` encodes bound parameters too, so `column < some_int` works in queries. Negative
values cannot be encoded, and the type rejects them. Signed quantities (offsets, years) are never
stored as sortable keys.

### 2.4 Rationals

Rates, periods and slopes that are not integral are exact **rationals**:
`{"num": "<signed int>", "den": "<positive int>"}`, always normalized (gcd 1, den > 0). Engines
provide add/sub/mul/div/floor/compare. Rounding to moments always uses **floor** unless a spec
says otherwise.

## 3. Dimensions

A dimension is an entity (kind `dimension`) whose extension row holds the time spec:

| Field | Type | Notes |
|-------|------|-------|
| `base_unit` | `{singular, plural, abbr}` | Cosmetic names, e.g. second/seconds/s. |
| `duration` | moment string | `D ≥ 1`. |
| `default_calendar_id` | id or null | Required once a calendar exists; used for display/input defaults. |
| `present` | time point or null | Narrative "now"; default as-of cursor (§10.6). |

Rules:

- **R-DIM-3:** `D` may change only if every resolved moment of every time-bound record, calendar
  anchor and sync point in the dimension stays within `[0, new D]`. The service reports the
  offending records otherwise.
- Renaming the base unit is cosmetic.
- **Refining the base unit** (e.g. seconds → milliseconds, multiplying every moment by 1000) is
  a post-MVP maintenance tool (`M13`). It must rewrite absolute anchors, base durations,
  recurrence intervals and calendar leaf counts atomically.
- **R-DIM-5:** events cannot be created in a dimension that has no calendar. The dimension wizard
  creates the first calendar (usually from a preset).
- Creating a dimension also creates its **prime timeline** in the same transaction.

Every dimension also has a **virtual "Absolute" calendar** (id `absolute`, not stored). It
displays raw base units (`t = 1,234,567 s`, with scientific notation for huge values) and accepts
absolute input. It does **not** satisfy R-DIM-5.

## 4. Timelines and branches (alternate timelines)

### 4.1 Model

A **timeline** is an entity (kind `timeline`, so it has a page for the "what if" premise) with an
extension row:

| Field | Notes |
|-------|-------|
| `dimension_id` | Owning dimension. |
| `parent_timeline_id` | Null for the prime timeline. |
| `branch_point` | Time point (anchorable, e.g. "start of the Assassination"); null for prime. Resolved into `branch_t`. |
| `is_prime` | Exactly one per dimension. |

Constraints: a branch point must resolve inside `[0, D]`, and its anchor may only reference
records visible in the **parent** timeline (otherwise a branch could depend on itself).
Timelines form a tree per dimension. Deleting a timeline with descendants requires deleting
(or re-parenting, post-MVP) the descendants first.

### 4.2 Lineage and cut-offs

For a timeline `T`, its **lineage** is the list of `(timeline, cutoff)` pairs:

```
L0 = (T, +∞)
L1 = (parent(T), b(T))
L2 = (parent(parent(T)), min(b(T), b(parent(T))))
…   cutoff_{i+1} = min(cutoff_i, b(L_i.timeline))
```

where `b(X)` is the resolved branch moment of `X`.

### 4.3 Visibility of time-bound records

Every **time-bound record** has `timeline_id`, a **start moment** `s(r)` and optionally
`overrides_id`. A record `r` is **visible in `T`** iff, for some lineage entry `(L, c)`,
`timeline_id(r) = L` and `s(r) < c` (strictly less: records starting exactly at the branch moment
belong to the diverging future). The start moment per record type:

| Record type | start moment `s(r)` |
|-------------|---------------------|
| event | `start_t` (for a series: `series_start_t`) |
| fact, temporal link | `valid_from_t`, where null = −∞ (always inherited) |
| worldline segment | `start_t` |
| module records with validity (e.g. map pins) | their `valid_from_t` (null = −∞) |

Timeless records (links without validity, entity rows themselves) are not timeline-bound. They are
visible in every timeline, subject to entity visibility (§4.6).

### 4.4 Overrides

A branch may change an inherited record that **spans the branch point**. Within the branch's
lineage that means `s(r) < cutoff < end(r)` (with `end = valid_to_t` for validity records, where
null = +∞). It does this by creating an **override row** in the same table:

- `overrides_id` always points to the **root** row (the original, non-override row), never to
  another override.
- The override's start must equal the root's start. The shared past is immutable, so only things
  after the branch point may differ: end, validity end, recurrence limits/exceptions, value
  (facts), role/data (links), rate/end (segments).
- Records entirely before the cut-off cannot be overridden or deleted in a branch.
- **Resolution:** among the root and all its override rows whose timelines are in `lineage(T)`
  and which are visible per §4.3, the row with the **smallest lineage depth** wins. Exactly one
  row per root is returned.
- A branch "removing" an inherited spanning record means overriding it so it ends at the branch
  moment.

Records **created** in a branch that start before the branch moment contradict the shared past.
They are allowed, but rule `core.branch.shared_past_modified` (warning) reports them.

### 4.5 `TimelineView` (implementation contract)

All queries over time-bound tables go through one generic helper:

```python
view = TimelineView.for_timeline(session, timeline_id)        # computes lineage once
stmt = view.select(Event)                                       # lineage visibility + override resolution
stmt = stmt.where(view.overlaps(Event, window_start, window_end))
```

The generated SQL uses a `VALUES` CTE for the lineage
(`timeline_id, cutoff_key, depth`), filters `start_key < cutoff_key`, and resolves overrides with
`ROW_NUMBER() OVER (PARTITION BY COALESCE(overrides_id, id) ORDER BY depth) = 1`. Tables register
with the helper by declaring their start/end columns. **Do not hand-roll lineage SQL elsewhere.**
Until the branching UI ships (M9), every dimension has only its prime timeline, but the helper is
still used everywhere so that M9 doesn't have to rewrite queries.

### 4.6 Entities and timelines

Entity rows are not time-bound. An entity has `origin_timeline_id`:

- `NULL` means it was created in a prime timeline (or is multiversal/timeless) and is visible in
  every timeline.
- Otherwise the entity was created inside that branch and is visible only in that timeline and
  its descendants (**branch-only entity**, R-TL-3).

An entity visible in a timeline may still not *exist* there at a given moment (§10.4). For
example, a character born after the branch point is never born in the branch unless the branch
gives them an existence fact.

**Per-timeline notes:** `entity_timeline_notes(entity_id, timeline_id, body)` lets a branch carry
extra rich text for an entity ("In this timeline she became a pirate") without forking the shared
page body (M9).

## 5. Time points and anchors

### 5.1 Schema (v1)

The normative structure is the Pydantic models in `lore.chronology.schema`, exported as JSON
Schemas to `spec/chronology/schema/` (`chronology-engine.md` §1). The shapes below are summaries.

```jsonc
// TimePoint
{
  "anchor": Anchor,
  "precision": "day",          // a level name of the relevant calendar, or "base"
  "approximate": false          // "circa"
}

// Anchor — one of:
{ "kind": "absolute", "t": "4350000000000000000" }

{ "kind": "calendar",
  "calendar_id": "01a0…",
  "fields": { "year": "1023", "month": "frostfall", "day": "12", "hour": "14" },
  "era": "af",                 // optional: year is era-relative
  "regime": "gregorian"        // optional: force a regime (reform gaps/overlaps)
}

{ "kind": "relative",
  "ref": { "type": "event", "id": "01a0…", "slot": "end", "occurrence": "57" },  // occurrence optional
  "offset": Duration             // may be negative; may be zero
}

// Duration — one of:
{ "kind": "base", "units": "-86400" }                       // signed, exact
{ "kind": "calendar", "calendar_id": "01a0…",
  "amounts": { "month": "3", "day": "2" }, "sign": 1 }       // amounts ≥ 0, sign ±1
```

Field values in `fields` are **strings**. They match `^(0|-?[1-9][0-9]*)$` (a number in that
level's numbering, canonical like every integer string) or `^[a-z][a-z0-9_-]*$` (a **slot id**: a stable id of a named child in the parent
template, such as a month or an intercalary day). Months and other named slots should be stored
by slot id. That way "keep typed dates" (D1) survives reordering and renumbering. The calendar engine
defines what is valid (`chronology-engine.md` §6).

### 5.2 Anchor semantics

| Kind | Resolves to | Depends on |
|------|-------------|------------|
| `absolute` | `t` | nothing |
| `calendar` | `from_fields(calendar, fields, era, regime)`, which is the **start** of the unit at `precision` | the calendar (definition and its own anchors) |
| `relative` | `resolve(ref) + offset`. A calendar offset is applied by calendar arithmetic starting from `resolve(ref)` (`chronology-engine.md` §9). | the referenced slot (and the offset's calendar) |

- A calendar anchor must specify every level from the top level down to `precision`. Levels
  below `precision` must be absent. The resolved moment is the start of that unit.
- A relative anchor's `ref.occurrence` targets one occurrence of a recurring event: the
  occurrence's computed (or materialized) start/end.
- Relative anchors may point at any **referenceable slot** (§6), in the same dimension or, with
  care, another dimension. Cross-dimension refs are allowed only through a correspondence (M9)
  and are resolved by mapping the moment. They are rarely needed.

### 5.3 Precision (D2)

A time point with precision level `P` denotes **some moment inside the `P`-unit that starts at
the resolved moment**:

- **Stored moment** = start of the unit (used for sorting, overlap, queries).
- **Uncertainty extent** = `[t, end of that P-unit)`. Precision `base` means `[t, t+1)` (exact).
- **Display** shows the time point at precision `P` ("Frostfall 1023", "1023").
- **Relative anchors:** default precision is the coarser of the target's precision and the finest
  unit present in the offset. The uncertainty extent is the target's extent shifted by the
  offset. The user may override precision explicitly.
- **Absolute anchors:** precision `base` unless the user picks a calendar level for display. In
  that case the extent is computed in the dimension's default calendar.

### 5.4 Approximate (circa)

`approximate: true` adds no numeric width. It marks the point as uncertain: displays get a "c."
prefix (calendar-configurable), timelines draw soft edges, and consistency rules downgrade
violations involving the point to **possible** (see `consistency.md` §4).

Explicit uncertainty ranges ("between 1020 and 1025") are **post-MVP**. The schema reserves
an optional `"range": {"earliest": TimePoint, "latest": TimePoint}` member that v1 must reject.

### 5.5 Event ends

```jsonc
"end": { "kind": "time_point", "time_point": TimePoint }   // explicit end
"end": { "kind": "duration",   "duration": Duration }      // start + duration (calendar arithmetic if calendar duration)
"end": { "kind": "instant" }                                // end = start
"end": { "kind": "end_of_time" }                            // end = D
"end": { "kind": "unknown" }                                // end = start for queries; displayed as open ("1023 – ?")
```

The end of a duration is computed from the start's resolved moment. The precision of an end given by
a duration is the coarser of the start's precision and the duration's finest unit.

## 6. Time slots

A **time slot** is a named time point owned by a record. The slot registry (core, extensible by
modules) declares, per record type, the table, slots, spec/resolved/status columns, and whether
others may reference the slot.

| Record type | Table | Slots | Referenceable |
|-------------|-------|-------|---------------|
| `event` | `events` | `start`, `end` | yes (incl. occurrences) |
| `event` (series) | `events` | `recurrence_until`, `exclusion:<i>.from`, `exclusion:<i>.to` | no |
| `entity_field` | `entity_time_fields` | `<field key>` (time-point fields), `fact:<fact id>` | no |
| `timeline` | `timelines` | `branch_point` | yes |
| `fact` | `entity_facts` | `valid_from`, `valid_to` | yes |
| `link` | `links` | `valid_from`, `valid_to` | yes |
| `segment` | `worldline_segments` | `start`, `end` | yes |
| `dimension` | `dimensions` | `present` | no |
| `calendar` | `calendars` | `alignment`, `era:<id>`, `regime:<id>` | no (internal) |
| `sync_point` | `correspondence_points` | `a`, `b` | no |
| module records | module tables | declared by the module | declared |

Each slot is persisted as three columns: `<slot>_spec` (JSON time point or end spec),
`<slot>_t` (`SortableBigInt`, last good resolved moment) and a shared `time_status` per record (or
per slot where needed).

**Resolution status** values: `ok`, `trashed_ref` (target is in the trash; still resolves),
`unresolved_ref` (target purged), `cycle`, `invalid_date` (fields no longer form a valid date),
`out_of_bounds` (outside `[0, D]`), `calendar_error` (calendar definition invalid). A slot that
is not `ok` keeps its **last good** `*_t`, so reads never break, and it raises a structural
finding.

## 7. Resolution and propagation (D3)

### 7.1 Dependency graph

Nodes are **time slots** and **calendars**. Edges are stored in `time_dependencies`:

| Column | Meaning |
|--------|---------|
| `dependent_type`, `dependent_id`, `dependent_slot` | the slot (or calendar) that depends |
| `target_kind` | `slot` or `calendar` |
| `target_type`, `target_id`, `target_slot` | the referenced slot (when `target_kind = slot`) |
| `target_calendar_id` | the referenced calendar (when `target_kind = calendar`) |

Edges are rewritten whenever a slot's spec is written. A calendar depends on the slots used in its
alignment, era boundaries and regime switch points. A slot depends on a calendar when it uses a
calendar anchor or a calendar-unit offset/duration. An event's `end` slot depends on its own `start`
slot when the end is a duration.

### 7.2 Write algorithm (inside the service transaction)

1. Validate and store the new specs. Rewrite the outgoing dependency edges of the changed nodes.
2. **Cycle check:** search from the changed nodes along outgoing edges. If any changed node can
   reach itself, reject the write with `409 time_cycle` and the cycle path.
3. Collect the **affected set** = reverse-dependency closure of the changed nodes (BFS over
   `time_dependencies` by target).
4. Topologically sort the affected subgraph (Kahn's algorithm).
5. Resolve each node in order with the chronology engine, using already-updated values. Write
   `*_t` and status. Changed resolved values of an event series also refresh
   `series_start_t/series_end_t` (`recurrence.md` §6).
6. Run **hard structural checks** on every affected record: within `[0, D]`, `end ≥ start`, valid
   fields, no cycle. Hard checks cannot be disabled. A failure rejects the whole transaction with
   `422 time_constraint` and the list of offending records, unless the operation is a calendar
   proposal apply with explicit per-record strategies (§7.4).
7. Record the changeset and recompute consistency findings for affected records.

Compiled calendars are cached per (calendar id, definition revision) for the life of the request,
and in an LRU cache across requests.

### 7.3 Deleting referenced records

- **Trash (soft delete):** dependents keep resolving against the trashed record. Their status
  becomes `trashed_ref` and a warning finding (`core.time.anchor_to_trashed`) is raised.
- **Purge (permanent delete):** before purging, every dependent anchor is **frozen**. It is
  converted to an `absolute` anchor at its last resolved moment, with the original spec kept in
  `frozen_from` for history, and an info finding is raised. Undoing the purge changeset restores
  everything.

### 7.4 Calendar edit proposals (D1)

1. `POST /calendars/{id}/proposals {definition}` compiles the new definition and fails fast on
   invalid definitions. It then computes the affected set (everything transitively depending on
   the calendar) and returns, per record, `old_t`, `new_t`, the old/new display strings and the
   new status. The proposal is stored server-side for 1 hour so apply is fast and deterministic.
2. Per affected record, the user chooses a **strategy**:
   - `keep_date` (default): keep the anchor and accept `new_t`.
   - `pin_moment`: convert the anchor to `absolute` at `old_t` (precision preserved).
   - `constrain` (only for `invalid_date`): move to the nearest valid date (the engine's
     constrain semantics, e.g. day 31 becomes 30).
3. `POST /calendars/{id}/proposals/{pid}/apply {strategies, default_strategy}` re-validates that
   nothing changed since the preview (compares revisions; `409` if stale), then saves the
   definition, applies the strategies, propagates and records a single changeset (undoable).
   Records left in `invalid_date` without a strategy make the apply fail with `422`.

### 7.5 Recurrence-rule edits

Changing an event's recurrence rule can make **materialized occurrences** (modified, cancelled or
referenced occurrences) point at keys that no longer exist or now land elsewhere. The same
proposal/apply pattern applies (`recurrence.md` §8): per materialized occurrence the user may
**re-key** (keep its moment and find the occurrence key now at that moment), **keep key** (move
with the rule), or **detach** (turn it into a standalone event).

## 8. Durations

- **Base durations** are exact signed integers of base units.
- **Calendar durations** are `{calendar_id, amounts, sign}`. Their length depends on where they
  are applied. Application is defined in `chronology-engine.md` §9: apply levels from coarsest
  to finest; variable levels use ordinal arithmetic with **constrain** overflow (31 Jan + 1 month
  becomes the last day of February), reckoned in the regime in force at the starting moment;
  uniform levels add exact base units.
- Negative calendar durations apply the same algorithm in reverse.
- Differences between moments in calendar units ("age 34 years, 2 months") use
  `chronology-engine.md` §9.3 (`diff` with a largest unit).

## 9. Events

### 9.1 Event rows

An event is an entity (kind `event`). Its time-bound row(s) live in `events` (`data-model.md`
§5.3). The **home row** is in the event's own timeline, and branches may add override rows (§4.4).
Main columns: `timeline_id`, `start_spec/start_t`, `end_spec/end_t`, `time_status`, `importance`
(1–5), `category`, `recurrence` (JSON or null), `series_start_t/series_end_t`, `series_entity_id`
and `occurrence_key` (for materialized occurrences), `occurrence_state`.

### 9.2 Sub-events

An event's `parent_id` is either an event (sub-event) or a misc entry (organizational filing;
see `docs/modules/misc.md`). Parent rules for sub-events:

- The parent must be visible in the child's timeline (the child may live in a branch while its
  parent is inherited).
- A sub-event of a **specific occurrence** has the **materialized occurrence entity** as parent.
- Rule `core.event.subevent_outside_parent` (warning) checks that the child's span lies within
  the parent's span (the occurrence's span for occurrence parents). The check is precision-aware.

### 9.3 Causality

`core.causes` links connect cause → effect, many-to-many, with an optional description. Causes and
effects can be in different timelines (if visible to each other) or dimensions (time travel,
portals). Rule `core.event.effect_before_cause` (warning) compares starts. Across dimensions it
maps through a correspondence when one exists, and is skipped otherwise. For entities with
worldlines it uses subjective order where relevant (`consistency.md`).

### 9.4 Participants

`core.participant` links connect event → any entity, with a free-text `role` (suggestions:
attacker, defender, victim, witness, leader, …) and an optional `segment_id` (§11.4). Modules add
semantic link types such as `locations.event_site`.

### 9.5 Recurrence (summary)

An event with a `recurrence` rule is a **series**. Its own start/end describe the **first
occurrence's** start and the occurrence duration. Occurrences are computed on demand by the
chronology engine and **never stored in bulk**. Only **materialized occurrences** are stored.
These are separate event entities with `series_entity_id`, `occurrence_key` and
`occurrence_state ∈ {modified, cancelled, referenced}`, created when the user changes, cancels,
annotates or attaches sub-events/links to a single occurrence. Details: `recurrence.md`.

## 10. Temporal world state (D4)

### 10.1 Validity periods

Facts, links and module records may carry `valid_from` and `valid_to` time points (each optional;
null = unbounded). They are half-open `[from, to)` and stored with resolved keys. A record with any
validity bound is **time-bound** and must have a `timeline_id`. A link with no bounds is timeless
(`timeline_id NULL`).

### 10.2 Facts (temporal fields)

`entity_facts(entity_id, field_key, value, valid_from/valid_to, timeline_id, overrides_id,
visibility, source_event_id?, note)`:

- `field_key` refers to a field of the entity's kind whose definition has `temporal: true`
  (built-in or custom), or to `core.exists` (§10.4), or to `core.name` (names over time).
- The entity's static field value (in `entities.fields`) is the **timeless default**, shown when
  no fact covers the as-of moment.
- Single-valued fields: overlapping facts for the same field in the same timeline view are a
  warning (`core.fact.overlap`). Multi-valued fields (`multiple: true`) may overlap.
- `source_event_id` optionally records the event that caused the change. The event page lists
  "changes caused".

### 10.3 Temporal links

Links whose type allows validity (`temporal: optional|required`) may have bounds, e.g.
`characters.spouse_of` "from the Wedding (end) until the Death of Ana (start)". Bounds are normal
time points, so they are live-linked to events.

### 10.4 Existence

Existence is stored as facts with `field_key = "core.exists"` and `value = true`. An entity can
have several existence intervals (a city destroyed and rebuilt). Kind-specific labels: born/died
(characters), founded/dissolved (groups), founded/destroyed (locations), emerged/extinct (species,
languages). Semantics in timeline `T` at moment `t`:

- If the entity has **no** `core.exists` facts visible in `T`, its existence is **unknown**. It is
  treated as existing for filtering, and the UI shows "existence not specified".
- Otherwise it exists iff some visible `core.exists` fact covers `t`.

The UI offers shortcuts: "create birth event and anchor existence start to it".

### 10.5 As-of resolution

`state(entity, T, t)` returns:

1. **Existence** per §10.4 (`exists | not_exists | unknown | possibly`).
2. **Fields:** for each temporal field, the visible fact covering `t` (latest `valid_from` wins on
   overlap, flagged), else the static value.
3. **Links:** timeless links plus temporal links visible in `T` whose validity covers `t`.
4. **Name:** a `core.name` fact covering `t`, if any, else the entity name.

**Precision-awareness:** if `t` lies inside the uncertainty extent of a relevant bound, the item is
returned with `certainty: "possible"`. The UI renders it de-emphasized.

### 10.6 Time cursor

The UI's time context is `(dimension, timeline, cursor)`, where `cursor` is a moment or `null`
("all time"). The default cursor is the dimension's present moment if set, else `null`. In
all-time mode entity pages show static values plus full histories of temporal fields, and lists and
graph show everything. The cursor is part of the URL (`?tl=…&at=…`) so views can be shared and
bookmarked.

## 11. Worldlines (personal timelines, D7)

### 11.1 Model

`worldline_segments(id, entity_id, seq, dimension_id, timeline_id, start_spec/start_t,
end_spec/end_t, rate, departure_event_id?, arrival_event_id?, overrides_id, note, visibility)`

- Segments are ordered by `seq` (subjective order), which need not match absolute order.
- `rate` (rational, default 1) is subjective base units per absolute base unit of the segment's
  dimension. Subjective time is measured in the base unit of the entity's **personal clock
  dimension**: its home dimension, or for multiversal entities the dimension of segment 1.
- Between consecutive segments there is a **jump** (time travel, dimension travel). Optional
  departure/arrival events document it.
- Segments are time-bound records (timeline inheritance and overrides apply).

### 11.2 Implicit worldline

An entity without explicit segments has an implicit worldline: its existence intervals in its
home dimension's timeline context, in chronological order, rate 1. Most entities never need explicit
segments.

### 11.3 Subjective time

```
subj_start(seg_1) = 0
subj_start(seg_i) = subj_start(seg_{i-1}) + (end(seg_{i-1}) − start(seg_{i-1})) × rate(seg_{i-1})
subj(t within seg_i) = subj_start(seg_i) + (t − start(seg_i)) × rate(seg_i)
```

All arithmetic is exact (rationals). Displays floor to the subjective unit. "Age at event" uses
subjective time when a worldline exists, else `diff(birth, t)`.

### 11.4 Participation and presence

- `where(entity, dimension, timeline, t)` returns **all** segments covering `t`. A time traveler
  can be present twice.
- A participation link may carry `segment_id`. If omitted and exactly one segment covers the
  event's start, that segment is implied. If several cover it, the participation is
  ambiguous (warning `core.worldline.ambiguous_participation`). If none does, the entity is absent
  (warning `core.worldline.absent_participant`).

### 11.5 Personal timeline view

Lists the entity's participations and existence changes sorted by **subjective** time, shows jumps
as discontinuities and shows subjective age. Paradox-aware rules (e.g. "met own past self",
"caused own birth") are informational. See `consistency.md` §6.

## 12. Cross-dimension correspondences (D7)

### 12.1 Model

`correspondences(id, dimension_a_id, dimension_b_id, name, extrapolation, rate_before, rate_after,
note, visibility)` and `correspondence_points(id, correspondence_id, a_spec/a_t, b_spec/b_t)`.

- Sync points are time points (anchorable, e.g. "the Portal opened" in A ⇔ "the Arrival" in B).
- After resolution, points sorted by `a_t` must be **strictly increasing in both `a_t` and
  `b_t`** (hard rule). Time flows forward in both dimensions.
- `extrapolation`: `none` (mapping undefined outside `[a_first, a_last]`) or `rate` (use
  `rate_before`/`rate_after` rationals; they default to the adjacent segment's slope, and a
  single-point correspondence must give them explicitly).

### 12.2 Mapping

For `a` in `[a_i, a_{i+1}]`:

```
map_ab(a) = b_i + floor((a − a_i) × (b_{i+1} − b_i) / (a_{i+1} − a_i))
```

`map_ba` is the same formula with roles swapped. Base units may differ between dimensions; the
slopes absorb the conversion. Results outside the target dimension's `[0, D]` mean "no
corresponding moment".

Details (Python: `lore.chronology.correspondence`; vectors in `cases/correspondences/`):

- Sync points are sorted by `a`; they must then increase strictly in both coordinates
  (`correspondence.non_monotonic` at the offending point). Rates are slopes in B units per A unit
  and must be positive (`correspondence.bad_rate`). With `extrapolation: rate`, a missing rate is
  the slope of the adjacent segment, and a single sync point needs both rates
  (`correspondence.missing_rate`). Every error is reported.
- The mapping is defined on `[a_first, a_last]` (inclusive; a single point maps only itself
  without extrapolation). Outside, `rate` extrapolation uses `b_first + floor((a − a_first) ×
  rate_before)` and `b_last + floor((a − a_last) × rate_after)`; `map_ba` uses the swapped points
  and the inverse rates (`1/rate`).
- Every result is floored, so both directions are monotonic non-decreasing. A round trip
  `a → b → a′` gives `a′ ≤ a` and `a − a′ < 1 + 1/s` A units, `s` being the slope where `a` maps:
  it is off by less than one unit of the other side plus one unit of this side (slope 5/2:
  `1 → 2 → 0`). Composed paths add the errors of their steps.

### 12.3 Composition and consistency

Dimensions and correspondences form a graph. `map(A → C)` composes along the shortest path
(`compose(path, t)`: each step maps with its own direction and target `D` and floors; any undefined
step makes the result undefined). Choosing the path is the server's job. If two
distinct paths between the same dimensions disagree at any sync point by more than rounding, rule
`core.correspondence.inconsistent_paths` warns. Correspondences apply to **all timelines** of both
dimensions (they describe how time flows, not history).

## 13. Worked examples

**Dimension.** "Aetheria", base unit second, `D = 10^110`.

**Calendar.** "Imperial Reckoning": second → minute (60) → hour (60) → day (24) → month →
year. Odd years use months Frostfall, Thawing, Bloom (30/31/30 days). Even years use Ember, Ash,
Cinder (31/30/31). It has a continuous 7-day week, eras BF/AF without year zero, and the alignment
"1 Frostfall 1 AF 00:00 = t 435,000,000,000,000,000".

**Calendar anchor.** "Founding of the Empire":
`{"kind":"calendar","calendar_id":C,"fields":{"year":"1","month":"frostfall","day":"1"},"era":"af"}`,
precision `day`. It resolves to the alignment moment.

**Relative anchor.** "Funeral" starts at `relative(ref = Assassination.end, offset = +3 days)`.
Moving the Assassination moves the Funeral in the same transaction.

**Calendar edit.** Frostfall gains a day. The proposal lists 412 events anchored in this calendar
whose moments shift, plus 37 dependents (relative anchors, link validity). The author pins 3
"astronomically fixed" events with `pin_moment`, and the rest keep their dates.

**Branch.** "What if the Emperor survived" branches from prime at the Assassination's start.
"The Succession War" (started earlier, spans the branch point) gets an override in the branch
ending at the branch moment. Everything after the branch point in the branch is new content.

**Worldline.** Captain Vey lives 1990–2020 in prime (segment 1, rate 1). At 2020 she jumps to
1950 in branch "Vey's Return" (segment 2, 1950–1980). Her subjective age at the end of segment 2
is 60 years. A battle in 1960 lists her with `segment_id = 2`.

**Correspondence.** Aetheria ↔ Dreamrealm: one sync point (Portal opened ⇔ Arrival) with
`rate_after = 365` (one Aetherian day is one Dreamrealm year, both in seconds). The event page of
the Portal shows "Concurrently in Dreamrealm: Year 1, Day 1".

## 14. Deferred / future

- Explicit uncertainty ranges (D2 follow-up; schema member reserved).
- Base-unit refinement tool (§3).
- Per-timeline calendar variants (eras that differ by branch). For now calendars are
  dimension-level, and their anchors resolve in the **prime** timeline.
- Time zones / local times (a calendar regime offset per location).
- Branch re-parenting and merging.
- Log-scale ("cosmic") timeline axis (frontend only).
