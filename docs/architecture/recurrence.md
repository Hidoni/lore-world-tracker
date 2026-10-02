# Recurrence

> **Status: normative.** Recurring events (holidays, birthdays, comets, councils every seventh
> year…) must work across cosmic durations **without ever storing occurrences in bulk** (brief,
> R-REC-1). This spec defines the rule format, occurrence identity, the expansion/counting
> algorithms (implemented in both chronology engines) and how single occurrences are customized.

## 1. Concepts

- A **series** is an event entity whose `events.recurrence` is non-null.
- The series' `start` time point is the **series start**. The first occurrence is the first
  generated occurrence at or after it.
- The series' `end` spec defines the **occurrence duration**. For series it must be `duration`,
  `instant` or `unknown`. An explicit end date is converted by the UI into a duration relative to
  the start ("6 days").
- **Occurrences** are computed on demand by `expand`, `occurrence` and related functions.
- A **materialized occurrence** is a separate event entity linked to its series. It exists only
  when the user customizes, cancels or references a single occurrence (§7).

## 2. Rule schema (v1)

Normative structure: `lore.chronology.schema.RecurrenceRule` (exported to
`spec/chronology/schema/recurrence-rule.json`). Rules carry `"schema_version": 1` (optional; an
absent version means 1, `data-model.md` §10). Optional members default as shown below
(`interval` `"1"`, `filters` [], `select` null, `missing` `"skip"`, `time` null, `exclusions` [],
filter `of` `"number"`).

```jsonc
// Calendar rule (RRULE-like, generalized to any calendar)
{
  "kind": "calendar",
  "calendar_id": "01a0…",
  "freq": { "level": "year" } | { "cycle": "week" },      // the period unit
  "interval": "1",                                          // every N periods (≥ 1)
  "filters": [PeriodFilter, …],                             // which periods qualify (AND)
  "select": Selector | null,                                // positions inside a period; null = "same position as the series start"
  "missing": "skip" | "constrain",                          // for select = null: when the start's position doesn't exist in a period (default "skip")
  "time": null | { "fields": { "hour": "9", "minute": "0" } }, // finer positions; null = same as the series start
  "limit": Limit,
  "exclusions": [ { "from": TimePoint, "to": TimePoint, "note": "…" }, … ]   // skip occurrences starting in [from, to)
}

// Fixed-interval rule (calendar-independent)
{
  "kind": "interval",
  "every": "2397422120",                                    // base units, ≥ 1
  "limit": Limit,
  "exclusions": [ … ]
}

// Limit
{ "kind": "never" } | { "kind": "count", "count": "100" } | { "kind": "until", "until": TimePoint }
```

`until` is **inclusive** (product decision, 2026-10-02): an occurrence starting exactly at the
resolved `until` is kept, as with RFC 5545 `UNTIL`. No occurrence starts after `D`, whatever the limit.

### 2.1 Periods

- `freq.level = L`: a period is one unit of level `L` (a year, a month, a day…). Intercalary
  units at level `L` are **not** periods (they have no regular ordinal).
- `freq.cycle = C` (only for **continuous** cycles): a period is one round of the cycle, i.e.
  `length` consecutive counted units starting at cycle index 0 (e.g. a week from Moonday).
  Excluded units belong to no round.

Period ordinals use `ordinal(t, L)` (or the cycle-round ordinal), as defined in
`chronology-engine.md` §5.8. With `p0` = ordinal of the period containing the series start, the
candidate periods are `p0 + k·interval` for `k = 0, 1, 2, …`. A series starting inside an
intercalary `L` unit has `p0` = the regular unit before it (so period 0 lies before the start and
yields no occurrence).

**Regimes** (product decision, 2026-10-02): ordinals and periods are reckoned in the regime in
force at the series start, extended proleptically past its end, like calendar arithmetic
(`chronology-engine.md` §9.2). A yearly series on Julian 25 December keeps falling on Julian
25 December after the 1582 reform (Gregorian 4 January from 1583 to 1600). To follow a reform, end
the series and start a new one in the new regime.

### 2.2 Period filters

```jsonc
{ "mod": "2", "eq": "1", "of": "number" | "ordinal" }   // e.g. odd years: of=number (astronomical Y for the top level)
{ "in": ["3", "frostfall"] }                             // period's number or slot id ∈ list
{ "cycle": "week", "in": ["moonday"] }                   // for unit periods at a cycle's level: cycle value ∈ list
{ "all": [F, …] } | { "any": [F, …] } | { "not": F }
```

`number` is the regular number within the parent (for the top level, the astronomical year
`Y`). `ordinal` is the global regular ordinal of the level. Note that "odd years" in **era**
numbering can differ from astronomical parity. The UI explains which one it uses and offers both.

### 2.3 Selectors (positions inside a period)

```jsonc
{ "path": [ LevelSelector, … ] }      // applied from the period's child level downward; cartesian product, time-ordered

// LevelSelector — one of:
{ "level": "month", "values": ["frostfall", "3"] }        // slot ids or regular numbers
{ "level": "day",   "values": ["1", "15", "-1"] }         // negative = from the end (-1 = last regular child)
{ "level": "day",   "cycle": { "id": "week", "values": ["moonday"], "nth": ["1", "-1"] } }
                                                          // children whose cycle value matches; optional nth within the parent
{ "level": "day",   "all": true }                         // every regular child
```

Examples:

| Description | Rule essentials |
|-------------|-----------------|
| Every year on 1 Frostfall | `freq year`, `select null` (start on 1 Frostfall) |
| Every 3rd month on day 10 | `freq month`, `interval 3`, `select {path:[{level:day, values:["10"]}]}` |
| First Moonday of each month | `freq month`, `select {path:[{level:day, cycle:{id:week, values:[moonday], nth:["1"]}}]}` |
| Last day of every month | `freq month`, `select {path:[{level:day, values:["-1"]}]}` |
| 1st and 15th of each month | `freq month`, `select {path:[{level:day, values:["1","15"]}]}` |
| Odd years only, on Midsummer (intercalary) | `freq year`, `filters [{mod:2, eq:1, of:number}]`, `select {path:[{level:month, values:[midsummer]}]}` |
| Every Moonday and Fireday | `freq {cycle: week}`, `select {path:[{level:day, cycle:{id:week, values:[moonday, fireday]}}]}` |
| Every 7 years, starting from the series start | `freq year`, `interval 7` |
| A comet every 2,397,422,120 s | `kind interval`, `every 2397422120` |

`select: null` with `missing: "skip"` mirrors RFC 5545. A series starting on 29 February
recurs only in leap years. `missing: "constrain"` uses the constrain semantics of
`chronology-engine.md` §9.2 instead (28 February in common years).

With `select: null`, the series start's positions below the period level are re-applied inside each
period exactly like calendar arithmetic re-applies them (`chronology-engine.md` §9.2: slot id, then
regular number, the intercalary fallback, then the base remainder). With `missing: "skip"`, any
step that would have to constrain (including a slot id whose number exists but whose id doesn't,
e.g. Frostfall in an even alternating year) skips the period; with `"constrain"` the step
constrains. Skipped periods consume their `k` (§3).

### 2.4 Time of day

Selected positions resolve to the **start** of the deepest selected unit. Finer positions come from
`time.fields`, or by default from the series start's finer fields (e.g. 09:00). The occurrence
start is the start of that finer position (precision = the series start's precision).

- `time.fields` name a **contiguous** run of levels strictly below the period level (and below the
  deepest selected level), e.g. `{hour, minute}`; values are regular numbers or slot ids, resolved
  with `missing` (`skip` rejects, `constrain` clamps like `from_fields`). Levels between the
  selected positions and the time fields come from the series start; levels below the time fields
  start at their first unit (base remainder 0).
- Without `time`, every finer position of the series start is re-applied, down to the base
  remainder (constrained like §9.2), so occurrences keep the start's exact offset in the unit.

## 3. Occurrence identity

- **Key** `k` for rules that can produce at most one occurrence per period. This is decided
  syntactically: no selector produces multiple values, `nth` has one value, and there is no
  `all`. Otherwise the key is `k.j`, where `j` is the 0-based time-ordered index inside the period.
  Interval rules: `k = (t − series_start) / every`.
- Keys are stable under edits that do not change the period structure (renaming, changing the
  duration, moving the time of day). Edits that change the structure trigger reconciliation (§8).
- Periods rejected by filters or with no selected positions **consume** their `k`. Keys can
  therefore skip numbers.
- The **occurrence number** (1-based count of actual occurrences up to this one) is shown in the
  UI ("58th Festival"). It is computed by `occurrence_number(rule, key)` (§5.4). The key is never
  shown as the number.

## 4. Engine API (both engines)

```
series_bounds(rule, ctx)                  -> { first_start, last_start?, last_end?, count? }
expand(rule, ctx, window=[w0, w1), max_items)
                                          -> { items: [{key, start, end}], truncated: bool, estimated_count? }
occurrence(rule, ctx, key)                -> {key, start, end} | not_found
occurrence_at(rule, ctx, t)               -> key of the occurrence whose span contains t (or that starts at t) | none
next_occurrences(rule, ctx, after_t, n)   -> [{key, start, end}]       (editor previews)
occurrence_number(rule, ctx, key)         -> n (1-based)
count_in_window(rule, ctx, window)        -> { count, exact: bool }
validate_rule(rule, ctx)                  -> [ValidationError]

ctx = { compiled calendar (calendar rules), series_start_t, duration spec, D,
        resolved times for limit.until and exclusions }
```

## 5. Algorithms

### 5.1 Occurrence duration and window widening

Calendar durations vary per occurrence (a "1 month" festival). `duration_upper_bound(duration)`
returns a safe upper bound from the calendar's maximum unit lengths. `expand` searches for starts in
`[w0 − upper_bound + 1, w1)` (exact durations use their length; an empty window `w0 = w1` searches
`[…, w0]`) and then keeps occurrences that overlap the window per `time-model.md` §2.1 (instants
included).

**Truncation.** `expand` never returns a partial list: when more than `max_items` occurrences
overlap the window, the result is `truncated: true` with no items and `estimated_count`. The count
is exact when the window has at most `max_items × 4` candidate periods (they are all evaluated) and
for interval rules with a fixed duration. Otherwise it is the candidate count times the share of
candidates that have an occurrence, sampled over 64 evenly spaced candidates (exact for rules that
never skip a period); #21 replaces the sampling with super-period averages (§5.4). Without
truncation `estimated_count` is null.

### 5.2 `expand` for calendar rules

1. Clamp the search range to `[series_start, series_last_start]` (from cached series bounds;
   `D` for `never`).
2. Find period ordinals `p_lo`/`p_hi` covering the range, and the first/last `k` aligned to
   `interval`.
3. If `(k_hi − k_lo + 1)` exceeds `max_items × 4`, return `truncated: true` with
   `estimated_count = (k_hi − k_lo + 1) × avg_per_period` (avg measured over one rule
   super-period, §5.4) and **no items**. The timeline draws a band.
4. Otherwise iterate `k`, locate the period (`from_ordinal`), apply filters, selectors and the time
   of day, and compute starts and ends. Drop starts before `series_start`, after `until`, beyond the
   count limit (§5.4) or inside exclusions. Stop at `max_items`.

Never iterate from the series start. Every step jumps directly to the window with ordinal
arithmetic.

### 5.3 `expand` for interval rules

`k_lo = max(0, ceil((w0 − upper − series_start) / every))`,
`k_hi = floor((w1 − 1 − series_start) / every)`, clamped by limits. O(1) per item, and the count
is exact.

### 5.4 Counting (count limits, occurrence numbers, estimates)

- **Interval rules:** trivial arithmetic.
- **Calendar rules:** occurrences per period depend only on the period's position in the
  calendar's top-level cycle (`P` years), the rule's interval and its filter moduli. The rule
  **super-period** is the smallest whole number of top-level cycles in which the number of
  candidate periods is divisible by `interval` and all filter moduli align. Engines precompute
  the per-super-period occurrence count and prefix counts by enumerating one super-period. This is
  allowed only if it contains ≤ 1,000,000 candidate periods, otherwise the error
  `rule.too_complex_to_count` applies to count limits and occurrence numbers, and estimates fall
  back to sampling.
- Calendar **exceptions** (years with explicit templates) are non-periodic. Counting adds
  per-exception corrections by enumerating the affected periods.
- `nth occurrence` (for `limit.count`): full super-periods × count + enumeration of the
  remainder.
- MVP shortcut: implementations may compute count limits by plain iteration when
  `count ≤ 100,000`. The super-period method is required above that (both engines, same results).

### 5.5 Series bounds cache

On every write of the series, or re-resolution of its start, limit, exclusions or calendar, the
server stores `series_start_t` (first occurrence start) and `series_end_t` (end of the last
occurrence, or `D` for `never`) in `events`. Window queries use these columns to select candidate
series (`series_start_t < w1 AND series_end_t > w0`) before expanding.

### 5.6 Searches and limits (Python: `lore.chronology.recurrence`)

- `occurrence(key)`: keys are canonical (`0`, `12`; never `012` or `1.0` for single-occurrence
  rules); a key whose period yields no occurrence, or whose start is before the series start or
  after `until`/`D`, is `not_found`.
- `next_occurrences(after_t, n)`: the first `n` occurrences starting at or after `after_t`.
- `series_bounds`: `first_start` is the first occurrence (`k = 0`, or later when period 0 is
  skipped or its start lies before the series start), `null` with `count = 0` when there is none;
  with `never`, `last_start`, `last_end` and `count` are `null`. With `until`, `count` is exact:
  arithmetic when no period can be skipped (`missing: constrain` without `time`), otherwise counted
  period by period.
- The first, last and next occurrences are searched within 100,000 candidate periods, and
  counting period by period is limited to 100,000 candidates (`rule.too_complex_to_count` beyond,
  until #21's super-periods). A series whose start position doesn't come back within 100,000
  periods is treated as having no further occurrence.

## 6. Recurrence and timelines

- A series is a time-bound record with start moment `series_start_t`. Branches inherit series
  that start before the cut-off **including their occurrences after the cut-off**: the festival
  keeps happening in the branch unless the branch changes it.
- A branch may **override** a series (`time-model.md` §4.4) only by changing `limit` (e.g.
  `until` = the branch moment − 1 base unit, meaning the festival was abolished: `until` is
  inclusive, and an occurrence starting at the branch moment belongs to the branch's future) or
  by adding `exclusions` starting at or after the cut-off. Occurrences before the cut-off must be identical. The service
  validates this.
- Materialized occurrences created in a branch (for occurrences after the cut-off) are
  branch-only entities.

## 7. Materialized occurrences

A materialized occurrence is an **event entity** with:

| Column (in `events`) | Value |
|-----------------------|-------|
| `series_entity_id` | the series event |
| `occurrence_key` | `k` or `k.j` |
| `occurrence_state` | `referenced` (unchanged time; has sub-events/links/notes), `modified` (time or duration changed), `cancelled` (did not happen) |
| `original_start_t` | the computed start when materialized (used for reconciliation) |
| `start_spec` | `referenced`: `relative(ref = {event: series, slot: start, occurrence: key}, 0)`; `modified`: any user anchor |
| `end_spec` | `referenced`: `relative(ref = {series, end, occurrence: key}, 0)`; `modified`: any end spec |

Behavior:

- Creating a sub-event, link, note, or field value for "the 57th Festival" **materializes** that
  occurrence (`referenced`) via `POST …/events/{series}/occurrences/{key}` (get-or-create,
  idempotent).
- Name and fields fall back to the series' values unless set. The page shows "Occurrence #58 of
  <series>". Participants shown = the series' participants plus the occurrence's own.
- **Window merging** (server and static data source): computed occurrences whose key has a
  materialized row are replaced by that row (`modified` rows are drawn at their own time; rows moved
  *into* the window are found by also querying materialized occurrences that overlap the window).
  `cancelled` occurrences are omitted and shown only in "show cancelled" mode.
- Deleting a materialized occurrence reverts it to the computed one, after confirmation when it
  has sub-events, which are then moved to trash.

## 8. Rule-change reconciliation (R-REC-6)

When a series' rule, start or calendar changes, as part of the same proposal/apply pattern as
calendar edits (`time-model.md` §7.4–7.5), each materialized occurrence gets one of these statuses:

| Status | Meaning | Strategies offered |
|--------|---------|--------------------|
| `unchanged` | `occurrence(key)` exists and starts at `original_start_t` | – |
| `moved` | key exists but its computed start changed | `keep_key` (default; moves with the rule), `rekey` (find `occurrence_at(original_start_t)`), `detach` |
| `orphaned` | key no longer exists | `rekey` (nearest occurrence at/after the original start), `detach` (default; becomes a standalone event with absolute anchors), `trash` |

Rekeying onto a key that is already materialized is a conflict, and the user must pick another
strategy for one of them.

## 9. Validation

`validate_rule` errors: `rule.unknown_calendar`, `rule.bad_freq_level`,
`rule.cycle_not_continuous`, `rule.bad_interval`, `rule.bad_filter`, `rule.bad_selector_level`
(selectors must descend strictly below the period level, in order), `rule.unknown_slot`,
`rule.bad_nth`, `rule.bad_time_fields`, `rule.until_before_start`, `rule.too_complex_to_count`,
`rule.series_end_not_duration` (series `end` must be duration/instant/unknown),
`rule.series_start_not_occurrence` (warning: the series start doesn't match the rule; the first
occurrence will be later).

Errors are `{code, path, message, severity}` (`severity` is `warning` only for
`rule.series_start_not_occurrence`, path `""`). Paths point into the rule, except
`rule.series_end_not_duration` (`/end`) and a calendar duration without a calendar
(`rule.unknown_calendar` at `/end/duration/calendar_id`), which point into the series. An
unresolved `limit.until` is `anchor.unresolved`. Engines refuse to evaluate a rule with errors.

## 10. UI notes (for M5)

- The recurrence editor offers presets (yearly on this date, monthly on this day, weekly on these
  days, every N base units…) and an advanced mode exposing filters and selectors.
- It always shows a live preview of the next 10 occurrences (`next_occurrences`) and a
  natural-language summary ("Every year on 1 Frostfall, odd years only, until the Fall of the
  Empire").
- The timeline draws a series as a band when `expand` is truncated, and as individual occurrences
  otherwise. Materialized occurrences with sub-events get a marker.
