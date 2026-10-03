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

`count` counts **generated** occurrences (starting at or after the series start, before `D`):
excluded ones still use up the count, as with RFC 5545 `COUNT` and `EXDATE` (product decision,
2026-10-02). The series ends at the start of the `count`-th generated occurrence, so exclusions
only ever remove occurrences and never add one at the end (a branch excluding a year doesn't
lengthen the series).

**Exclusions** skip the occurrences whose start lies in `[from, to)`. Their time points are
resolved by the server and passed as `resolved["/exclusions/<i>/from"]` and `…/to` (missing:
`anchor.unresolved`). `to < from` is `rule.bad_exclusion`; `to = from` excludes nothing.
Overlapping ranges merge. An excluded occurrence has no occurrence (`occurrence(key)` is
`not_found`), no number, and isn't counted by `series_bounds` or `count_in_window`.

### 2.1 Periods

- `freq.level = L`: a period is one unit of level `L` (a year, a month, a day…). Intercalary
  units at level `L` are **not** periods (they have no regular ordinal).
- `freq.cycle = C` (only for **continuous** cycles, else `rule.cycle_not_continuous`): a period
  is one round of the cycle, i.e. `length` consecutive counted units starting at cycle index 0
  (e.g. a week from Moonday). Excluded units belong to no round. Round `r` holds the counted units
  `a − i + r·length … a − i + (r+1)·length − 1`, where `a` is the anchor unit's counted ordinal and
  `i` its anchor index, so round 0 is the round of the anchor unit and the round ordinal is what
  `mod` filters test (both `of: number` and `of: ordinal`). With `select: null`, each round's
  occurrence is at the series start's cycle index (the index of the counted unit before it when
  the start lies in an excluded unit), then its finer fields.

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

- `mod`: `eq` must be below `mod` (`rule.bad_filter`); floor modulo, so negative years work.
- `in`: a number matches the period's regular number, a slot id its slot (`rule.unknown_slot` for a
  slot id that no template of the level has).
- `cycle`: the cycle must be at the period's level (`rule.bad_filter`). Values name cycle
  positions by **value id** (the cycle's optional `ids`, `chronology-engine.md` §3.7; product
  decision 2026-10-02: ids survive renaming the display names) or by the cycle number `n`
  (`index + number_start`); unknown values are `rule.unknown_slot`. An excluded unit has no value
  and never matches.
- Cycle rounds have no number or slot: only `mod`, `all`, `any` and `not` apply to them
  (`rule.bad_filter`).

### 2.3 Selectors (positions inside a period)

```jsonc
{ "path": [ LevelSelector, … ] }      // each finer than the one before; cartesian product, time-ordered

// LevelSelector — one of:
{ "level": "month", "values": ["frostfall", "3"] }        // slot ids or regular numbers
{ "level": "day",   "values": ["1", "15", "-1"] }         // negative = from the end (-1 = last regular child)
{ "level": "day",   "cycle": { "id": "week", "values": ["moonday"], "nth": ["1", "-1"] } }
                                                          // units whose cycle value matches; optional nth within the parent
{ "level": "day",   "all": true }                         // every regular unit
```

- **Levels.** The first selector of a level period is at any level below the period; each next
  selector is at a level below the previous one (`rule.bad_selector_level` otherwise). A selector
  may **skip levels** (product decision, 2026-10-02): it then chooses among all the units of its
  level inside the parent unit, e.g. day 256 of the year, the last day of the year or the first
  Monday of the year. Levels skipped between selectors follow from the chosen unit. For cycle
  rounds, the first selector is at the cycle's level and chooses units of the round.
- **Values.** A number counts the **regular** units of the level inside the parent, from the
  level's `numbering_start` (`"1"` = the first day, `"0"` = the first hour of a 0-based level);
  negative numbers count from the end (`"-1"` = the last regular unit). A slot id picks every
  unit of the level with that slot inside the parent, intercalary slots included
  (`rule.unknown_slot` if no template of the level has it). In a round, values name cycle positions
  (value ids or cycle numbers, negative from the end). Positions that don't exist in a given
  parent are simply absent.
- **`all`** picks every regular unit (intercalary units are never picked by `all`).
- **Cycle matches** pick the units whose cycle value is one of `values` (the cycle must be at the
  selector's level, else `rule.bad_selector_level`; excluded units never match). `nth` applies
  **per value** (product decision, 2026-10-02, like RFC 5545 `BYDAY=1MO,1FR`): `nth: ["1"]` with
  `values: [moonday, fireday]` is the first Moonday and the first Fireday. `"0"` is
  `rule.bad_nth`; an `nth` beyond the matches selects nothing.
- Duplicate positions count once; positions are time-ordered, and `j` (§3) is the index in that
  order. A period may hold at most 100,000 positions (`rule.too_many_positions`).

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
| Day 256 of every year | `freq year`, `select {path:[{level:day, values:["256"]}]}` |
| Last day of the year | `freq year`, `select {path:[{level:day, values:["-1"]}]}` |
| First and last Moonday of the year | `freq year`, `select {path:[{level:day, cycle:{id:week, values:[moonday], nth:["1","-1"]}}]}` |
| Fridays the 13th | `freq day`, `filters [{cycle:week, in:[fireday]}, {in:["13"]}]` |
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
  syntactically: every selector has one value (a number, or a slot id at the level directly below
  the previous selector or the period: slot ids are unique only within one template), a cycle
  match has one value and one `nth`, and there is no `all`. Otherwise the key is `k.j`, where `j` is the 0-based time-ordered index inside the period.
  Interval rules: `k = (t − series_start) / every`.
- Keys are stable under edits that do not change the period structure (renaming, changing the
  duration, moving the time of day). Edits that change the structure trigger reconciliation (§8).
- Periods rejected by filters or with no selected positions **consume** their `k`. Keys can
  therefore skip numbers.
- The **occurrence number** (1-based count of actual occurrences up to this one: excluded and
  filtered ones don't count) is shown in the
  UI ("58th Festival"). It is computed by `occurrence_number(rule, key)` (§5.4). The key is never
  shown as the number.

## 4. Engine API (both engines)

```
series_bounds(rule, ctx)                  -> { first_start, last_start?, last_end?, count? }
expand(rule, ctx, window=[w0, w1), max_items)
                                          -> { items: [{key, start, end}], truncated: bool, estimated_count? }
occurrence(rule, ctx, key)                -> {key, start, end} | not_found
occurrence_at(rule, ctx, t)               -> key of the occurrence starting at t, else of the latest-starting one whose span contains t | none
next_occurrences(rule, ctx, after_t, n)   -> [{key, start, end}]       (editor previews)
occurrence_number(rule, ctx, key)         -> n (1-based)
count_in_window(rule, ctx, window)        -> { count, exact: bool }
validate_rule(rule, ctx)                  -> [ValidationError]

ctx = { compiled calendar (calendar rules), series_start_t, duration spec, D,
        resolved times for limit.until and exclusions }
```

- `occurrence_at(t)` (product decision, 2026-10-02): an occurrence starting exactly at `t`
  wins; otherwise the latest-starting occurrence whose half-open span contains `t` (several can,
  when occurrences are longer than the gaps between them). An instant matches only at its own
  start. Excluded occurrences and those beyond the limit never match.
- `occurrence_number(key)` is the 1-based number among the occurrences that happen (excluded and
  filtered ones don't count); `not_found` like `occurrence(key)`.
- `count_in_window(window)` counts the occurrences overlapping the window (time-model §2.1). It is
  exact for interval rules and for calendar rules that can be counted (§5.4); with a calendar
  duration, the occurrences starting before the window are checked one by one (at most 10,000,
  else the result counts them all and is not exact). Rules that can't be counted fall back to
  the sampled estimate of §5.1 with `exact: false`.

## 5. Algorithms

### 5.1 Occurrence duration and window widening

Calendar durations vary per occurrence (a "1 month" festival). `duration_upper_bound(duration)`
returns a safe upper bound from the calendar's maximum unit lengths. `expand` searches for starts in
`[w0 − upper_bound + 1, w1)` (exact durations use their length; an empty window `w0 = w1` searches
`[…, w0]`) and then keeps occurrences that overlap the window per `time-model.md` §2.1 (instants
included).

**Truncation.** `expand` never returns a partial list: when more than `max_items` occurrences
overlap the window, the result is `truncated: true` with no items and `estimated_count`. Without
truncation `estimated_count` is null. How the count is found:

- Interval rules with a fixed duration: exact arithmetic (more than `max_items × 4` periods are
  never visited).
- Calendar rules visit the window's periods while there are at most `max(10,000, max_items × 4)`
  of them, so sparse rules (Fridays the 13th over daily periods) stay exact. Once more than
  `max_items × 4` occurrences are found, the visit stops and the rest is extrapolated from the
  occurrences per visited period.
- More periods than that, or the early stop above: `count_in_window` (exact whenever the rule can
  be counted, §5.4), else the period count times the occurrences per period sampled over 64
  evenly spaced periods.

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

Everything is built on two primitives over the positions of all periods `k ≥ 0` (no bounds or
exclusions applied): `G(t)`, the number of positions starting before `t`, and `position(i)`, the
`i`-th position. The count limit is `position(G(series_start) + count)`; generated occurrences
before `t` are `G(min(t, D + 1)) − G(series_start)`; excluded ones are the same differences at the
ends of the exclusion ranges; occurrence numbers and window counts follow, and the first, last and
next occurrences are `position(G(t) + 1)` / `position(G(t + 1))`, skipping exclusion ranges.

- **Interval rules:** `G(t) = max(0, ⌈(t − series_start) / every⌉)`.
- **Calendar rules:** `G(t) = S(k_t) + ` the positions of `t`'s own period before `t`, where
  `S(k)` sums the positions of periods `0 … k−1`.
  - **Constant periods.** Without filters, cycle selectors or rounds, a period's positions depend
    only on its unit's template. When every template of the level holds the same number `c`,
    `S(k) = c·k` (`c = 0`: the rule never occurs, found at once).
  - **Super-period.** Otherwise the engine looks for the smallest number `M` of top-pattern
    periods (`P` years each) after which everything the positions depend on repeats: `M·U ≡ 0`
    (mod `interval`) for `U` regular units of the level per top period (counted units and
    `length·interval` for cycle rounds), `M·U ≡ 0` (mod `m`) for every `mod` filter on ordinals
    (and on round numbers), `M·P ≡ 0` (mod `m`) for `mod` filters on year numbers, and `M·U_c ≡ 0`
    (mod `length`) for every continuous cycle the rule uses (filters, selectors, rounds), with
    `U_c` its counted units per top period. Reset cycles and everything structural repeat with
    `P` anyway. The super-period is `Q = M·U / interval` periods (rounds: divided by the cycle
    length too). An `in` filter on year numbers is not periodic, nor is a level without regular
    units in the pattern.
  - **Exceptions.** Periods overlapping a calendar exception year (plus one on each side) are
    counted one by one. Between them, each clean stretch is periodic with period `Q`, but its
    ordinals and cycle phases may be shifted by the exceptions before it, so every stretch longer
    than `2Q` gets the prefix sums of its own first `Q` periods; shorter ones are enumerated.
  - **Limits.** Enumerating more than 1,000,000 periods in all (a super-period, exception
    periods and short stretches) makes the rule uncountable. Uncountable rules (and every rule
    when `k ≤ 10,000`, where it is cheaper) count by enumerating periods from `k = 0`, which is
    allowed up to 100,000 periods (the spec's iteration shortcut); beyond that, count limits,
    occurrence numbers and searches are `rule.too_complex_to_count`, and estimates are sampled.
  - **Caching.** Counters and enumerated prefixes are cached on the compiled regime per (rule,
    series start), at most 64 each (least recently used first out): a daily rule with a weekday
    filter enumerates its 146,097-day super-period once.
- A count limit of 10^12 on a yearly rule takes milliseconds (`Q = 400` Gregorian years).

### 5.5 Series bounds cache

On every write of the series, or re-resolution of its start, limit, exclusions or calendar, the
server stores `series_start_t` (first occurrence start) and `series_end_t` (end of the last
occurrence, or `D` for `never`) in `events`. Window queries use these columns to select candidate
series (`series_start_t < w1 AND series_end_t > w0`) before expanding.

### 5.6 Searches and limits (`lore.chronology.recurrence`, `@lore/chronology` `recurrence/`)

- `occurrence(key)`: keys are canonical (`0`, `12`; never `012` or `1.0` for single-occurrence
  rules); a key whose period yields no occurrence, or whose start is before the series start,
  after `until`/the count limit/`D`, or excluded, is `not_found`.
- `next_occurrences(after_t, n)`: the first `n` occurrences starting at or after `after_t`.
- Searches for the next or previous occurrence first look at the 64 periods around the moment,
  then jump by counting (§5.4), so far or sparse occurrences (and rules that never occur) are
  found without scanning.
- `series_bounds`: `first_start` is the first occurrence, `null` with `count = 0` when there is
  none; with `never`, `last_start`, `last_end` and `count` are `null`. With `until` or `count`,
  `last_*` describe the last occurrence and `count` is the exact number of occurrences that
  happen (exclusions applied).

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
(each selector strictly finer than the previous one or the period, §2.3), `rule.unknown_slot`,
`rule.bad_nth`, `rule.bad_time_fields`, `rule.until_before_start`, `rule.too_complex_to_count`,
`rule.series_end_not_duration` (series `end` must be duration/instant/unknown),
`rule.bad_exclusion` (an exclusion ending before it starts),
`rule.series_start_not_occurrence` (warning: the series start doesn't match the rule; the first
occurrence will be later). Evaluating a rule can also fail with `rule.too_many_positions` (a
period holding more than 100,000 positions, §2.3), which depends on the calendar's data rather
than the rule alone.

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
