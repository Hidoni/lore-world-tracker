# Chronology conformance suite

Language-neutral test vectors that **both** chronology engines must pass
(`chronology-engine.md` §1 and §14, ADR-0004). The Python runner is
`backend/tests/chronology/test_conformance.py` and the TypeScript runner is
`packages/chronology/test/conformance.test.ts`. Both load every file below. `make test-chronology`
runs both, and so does the CI `chronology` job.

## Layout

```
conformance/
  README.md                  this file: the format and every op
  calendars/<name>.json      a calendar: definition + compile context
  cases/<area>/<name>.json   a case file: cases of one area against (at most) one calendar
```

Every `.json` file under `calendars/` is a calendar file, and every `.json` file under `cases/` is
a case file. Runners fail on files of any other shape.

## Calendar files

```jsonc
{
  "description": "what this calendar is and why it exists",
  "definition": CalendarDefinition,   // spec/chronology/schema/calendar-definition.json
  "context": CompileContext           // spec/chronology/schema/compile-context.json
}
```

The calendar's name is its file name without `.json`. `context.resolved` holds the resolved moment
of **every non-local time point** of the definition (absolute anchors included), keyed by JSON
pointer, e.g. `"/regimes/0/alignment/at"`. Runners validate both members against the schemas.

## Case files

```jsonc
{
  "description": "what these cases cover",
  "calendar": "gregorian-seconds",    // a calendars/ name, or null for calendar-free ops
  "generated": false,                 // true: produced by an engine, reviewed (see Rules)
  "verification": "how the expected values were established",
  "cases": [
    {
      "id": "leap-day-2024",          // unique within the file; [a-z0-9-]+
      "op": "to_fields",              // one of the ops below
      "input": { … },                 // op-specific
      "expected": …,                  // op-specific result, or {"error": "<code>"}
      "note": "optional explanation or source"
    }
  ]
}
```

A case is identified as `<area>/<file>::<id>` (e.g. `conversions/gregorian-seconds::unix-epoch`)
in both runners.

### Conventions

- Integers that are in-world quantities (moments, years, counts, offsets, ordinals) are canonical
  decimal **strings** (`time-model.md` §2.2), in inputs and outputs. Small structural integers
  (cycle indexes, `sign`) are JSON numbers, as in the schemas.
- Results are compared **exactly** (deep equality, including key sets). An optional member that
  does not apply is present with value `null` (or `{}` for maps), never omitted.
- Errors are `{"error": "<code>"}`, with the code from the specs (`invalid_date`,
  `reform_gap`, `reform_ambiguous`, `not_found`, `rule.too_complex_to_count`, …). Messages and
  extra details are not compared.
- `calendar_id` members inside inputs (durations, rules) may hold any id. Runners resolve them to
  the case file's calendar.
- Rules, end specs and correspondences in inputs are schema-valid documents
  (`spec/chronology/schema/`). Their non-local time points are resolved through an input member
  `resolved` (JSON pointer into that document → moment), like `context.resolved` for calendars.

## Ops

Ops are listed with their spec section. The calendar comes from the case file unless the op is
marked *calendar-free* (`calendar: null`).

### `validate` (chronology-engine §4, §11), calendar-free

- input: `{"definition": CalendarDefinition, "context": CompileContext}`
- expected: `{"errors": [{"code": "<code>", "path": "<JSON pointer>"}, …]}`, `[]` when valid.

The errors are compared as a **set** of `(code, path)` pairs; order and messages are ignored.
`path` points at the offending member. The input documents are raw JSON: schema violations are
reported first (with the dedicated codes of chronology-engine §11 where one exists, otherwise
`schema.invalid`), and semantic checks run only on schema-valid documents. An engine reports the
root cause of a problem and not the errors derived from it (e.g. no epoch error because the
alignment fields are invalid).

### `to_fields` (§5.6)

- input: `{"t": "<moment>"}`
- expected:

  ```jsonc
  {
    "regime": "<regime id>",
    "levels": {                           // every level, top to level 0
      "year":  { "n": "2024" },           // unnamed unit: regular number only
      "month": { "n": "3", "id": "mar", "name": "March", "intercalary": false },  // named slot
      "day":   { "n": "15" }              // "n": null for an intercalary unit
    },
    "base": "0",                          // remainder below level 0
    "era": { "id": "ad", "year": "2024", "abbr": "AD", "name": "Anno Domini" } | null,
    "cycles": { "<cycle id>": { "index": 4, "name": "Friday" | null, "n": 5 } | null },   // {} without cycles
    "overlays": { "<overlay id>": { "phase": Rational, "name": "Waxing Gibbous" } }       // {} without overlays
  }
  ```

### `from_fields` (§5.7)

- input: `{"fields": DateFields, "precision": "<level id>", "era": "<era id>" | absent,
  "regime": "<regime id>" | absent, "overflow": "reject" | "constrain" | absent}` (default
  `reject`)
- expected: `{"t": "<moment>"}` (the start of the unit at `precision`) or an error
  (`invalid_date`, `reform_gap`, `reform_ambiguous`).

### `unit_bounds` (§5.8)

- input: `{"t": "<moment>", "level": "<level id>"}`
- expected: `{"start": "<moment>", "end": "<moment>"}` (half-open, clipped at regime boundaries)

### `ordinal` (§5.8)

- input: `{"t": "<moment>", "level": "<level id>"}`
- expected: `{"ordinal": "<signed>", "intercalary": false}`: the regular units of `level` between
  the start of year 0 and the unit (the first regular unit of year 0 is `"0"`); inside an
  intercalary unit, the ordinal of the preceding regular unit with `"intercalary": true`

### `from_ordinal` (§5.8)

- input: `{"level": "<level id>", "ordinal": "<signed>"}`
- expected: `{"start": "<moment>", "end": "<moment>"}`

### `options` (§6)

- input: `{"fields": DateFields, "level": "<level id>"}`: `fields` name every level from the top
  down to the level just above `level` (`{}` for the top level)
- expected: `{"options": [Option, …]}` in template order, where an option is a named slot
  `{"kind": "slot", "value": "<slot id>", "n": "<number>" | null, "name": "<name>", "intercalary": false}`
  (`n` is `null` for an intercalary slot) or a run of unnamed children
  `{"kind": "range", "first": "<number>", "last": "<number>"}` (inclusive; a run may hold up to
  10^1000 children, so they are never listed one by one). The top level's single option is
  `{"kind": "range", "first": null, "last": null}` (any year). Invalid parents, or `fields` that
  don't stop right above `level`, are `invalid_date`.

### `cycle_value` (§3.7, §8)

- input: `{"t": "<moment>", "cycle": "<cycle id>"}`
- expected: `{"index": 0, "name": "Moonday" | null, "n": 1}`, or `null` for an excluded unit;
  `{"error": "unknown_cycle"}` for a cycle the active regime doesn't have

### `era_of` (§3.8, §8)

`from_fields` inputs may carry `"era": "<era id>"`; the year is then era-relative (§3.8).

- input: `{"t": "<moment>"}`
- expected: `{"id": "<era id>", "year": "<era year>", "abbr": "<abbr>", "name": "<name>"}`, or
  `null` for a calendar without eras

### `overlay_phase` (§3.9, §8)

- input: `{"t": "<moment>", "overlay": "<overlay id>"}`
- expected: `{"phase": Rational, "name": "<phase name>"}`, or `{"error": "unknown_overlay"}`

### `next_phase_at` (§8)

- input: `{"t": "<moment>", "overlay": "<overlay id>", "phase": Rational}`
- expected: `{"t": "<moment>"}`: the first moment at or after `t` at which the overlay is at
  `phase` (`ceil` of the exact instant), or `{"error": "unknown_overlay"}` /
  `{"error": "invalid_date"}` (a phase outside `[0, 1)`)

### `add` (§9.2)

- input: `{"t": "<moment>", "duration": Duration, "overflow": "constrain" | "reject" | absent}`
  (default `constrain`)
- expected: `{"t": "<integer>"}` (may lie outside `[0, D]`; callers enforce bounds) or
  `{"error": "invalid_date"}` (a constraining step under `reject`, or an unknown level)

### `diff` (§9.3)

- input: `{"t1": "<moment>", "t2": "<moment>", "largest": "<level id>", "smallest": "<level id>"}`
- expected: `{"amounts": {"<level id>": "<n>", …}, "base": "<n>", "sign": 1 | -1}` (every level
  from `largest` to `smallest`; `sign` is `1` when `t1 = t2`), or `{"error": "invalid_date"}` for
  an unknown level or a `largest` finer than `smallest`

### `format` (§3.11, §10)

- input: `{"t": "<moment>", "precision": "<level id>" | "base", "approximate": false}`
- expected: `{"text": "<string>"}`, or `{"error": "invalid_date"}` for an unknown precision

### `format_span` (§10)

- input: `{"start": {"t", "precision", "approximate"} | null, "end": {"t", "precision", "approximate"} | null}`
  (`null` = open end, rendered `?`)
- expected: `{"text": "<string>"}`

### `format_absolute` (§10, time-model §3), calendar-free

- input: `{"t": "<moment>", "base_unit": {"singular", "plural", "abbr"}, "display": DisplayOptions | absent, "approximate": false}`
  (`display` absent = the default options)
- expected: `{"text": "t = <number> <abbr>"}`

### `preset_instantiate` (§13), calendar-free

- input: `{"preset": "<preset id>", "seconds_per_base_unit": Rational, "origin": "<moment>" | absent}`
  (`origin` absent = `0`; presets load from `spec/chronology/presets/`)
- expected: `{"definition": CalendarDefinition}` (the preset's JSON with the §13 edits, compared
  exactly) or `{"error": "preset.incompatible_base_unit"}`

The calendar files `calendars/preset-<id>.json` are the presets instantiated with one-second base
units and the origin at `t = 10^14`. They are written out (so runners need no preset support to
load them), and the Python tests check they equal the instantiation.

### Recurrence ops (recurrence.md §4)

The calendar is the case file's (null for files with only interval rules). Common input members
(the rule context `ctx`):

```jsonc
{
  "rule": RecurrenceRule,
  "series_start": "<moment>",           // resolved series start
  "end": EndSpec,                       // occurrence duration: duration | instant | unknown
  "resolved": { "<JSON pointer into rule>": "<moment>" }   // limit.until and exclusions
}
```

`D` is the calendar context's `dimension_duration`, or an input member `"dimension_duration"` for
calendar-free files. Occurrences are `{"key": "<k or k.j>", "start": "<moment>", "end": "<moment>"}`.

- `expand`: ctx + `{"window": ["<w0>", "<w1>"], "max_items": 100}` →
  `{"items": [occurrence, …], "truncated": false, "estimated_count": "<n>" | null}`; a truncated
  result has no items and a count (recurrence.md §5.1), an untruncated one `estimated_count: null`
- `series_bounds`: ctx → `{"first_start": "<moment>" | null, "last_start": … | null, "last_end": … | null, "count": "<n>" | null}`
  (`null` where the series is unbounded; `first_start: null` when it has no occurrence)
- `occurrence`: ctx + `{"key": "<key>"}` → occurrence or `{"error": "not_found"}`
- `count_in_window`: ctx + `{"window": ["<w0>", "<w1>"]}` → `{"count": "<n>", "exact": true}`
  (occurrences overlapping the window; `exact: false` marks an estimate, recurrence.md §5.4)
- `occurrence_number`: ctx + `{"key": "<key>"}` → `{"number": "<n>"}` (1-based among the
  occurrences that happen) or `{"error": "not_found"}`
- `occurrence_at`: ctx + `{"t": "<moment>"}` → `{"key": "<key>" | null}` (recurrence.md §4)

Errors also include `rule.too_complex_to_count` (§5.4) and `rule.too_many_positions` (§2.3).

### `map` (time-model §12.2), calendar-free

- input:

  ```jsonc
  {
    "correspondence": { "extrapolation": "none" | "rate", "rate_before": Rational | null,
                        "rate_after": Rational | null,
                        "points": [{"a": "<moment>", "b": "<moment>"}, …] },   // resolved sync points
    "direction": "ab" | "ba",
    "t": "<moment>",
    "target_duration": "<moment>"        // D of the target dimension
  }
  ```

- expected: `{"t": "<moment>"}`, or `{"t": null}` when there is no corresponding moment, or the
  validation error of an invalid correspondence (`{"error": "correspondence.non_monotonic"}`,
  `correspondence.bad_rate`, `correspondence.missing_rate`; the first one found)

### `compose` (time-model §12.3), calendar-free

- input: `{"path": [{"correspondence": …, "direction": "ab" | "ba", "target_duration": "<moment>"}, …],
  "t": "<moment>"}` (each step as in `map`)
- expected: `{"t": "<moment>"}` after flooring at every step, or `{"t": null}` as soon as a step
  has no corresponding moment

### Numeric utilities (chronology-engine §2), calendar-free

Integer inputs named `n`, `a`, `b` are decimal strings that runners convert **without**
validation (they may be deliberately out of range); `text` and `key` go through the strict parsers.
Rationals in inputs (`a`, `b`, or the members `num`/`den` themselves) are parsed and normalized
like `rational_normalize`. Errors: `invalid_number`, `invalid_key`, `division_by_zero`.

| op | input | expected |
|----|-------|----------|
| `parse_moment` | `{"text"}` | `{"value": "<canonical>"}` |
| `parse_signed` | `{"text"}` | `{"value": "<canonical>"}` |
| `format_moment` | `{"n"}` | `{"text"}` |
| `format_signed` | `{"n"}` | `{"text"}` |
| `sortable_key` | `{"n"}` | `{"key"}` |
| `from_sortable_key` | `{"key"}` | `{"n"}` |
| `floor_div` | `{"a", "b"}` | `{"value"}` |
| `floor_mod` | `{"a", "b"}` | `{"value"}` |
| `rational_normalize` | `{"num", "den"}` | `{"num", "den"}` |
| `rational_from_int` | `{"n"}` | `{"num", "den"}` |
| `rational_add` / `_sub` / `_mul` / `_div` | `{"a": Rational, "b": Rational}` | `{"num", "den"}` |
| `rational_compare` | `{"a", "b"}` | `{"value": -1 \| 0 \| 1}` (a JSON number) |
| `rational_floor` | `{"a"}` | `{"value"}` |
| `rational_frac` | `{"a"}` | `{"num", "den"}` |
| `format_integer` | `{"n", "digit_group"?, "scientific_threshold"?, "significant_digits"?, "plain"?}` (absent = the defaults `","`, `16`, `4`, `false`) | `{"text"}` |

### Adding ops

Later issues add ops by documenting them here first. Runners reject unknown ops, so a vector can't be silently skipped.

## Runners and pending ops

Each runner has a dispatch table (op → engine call) and an explicit **pending** list (op → the
issue that implements it in that engine). A case whose op is pending must fail with "not
implemented": pytest marks it `xfail(strict=True)` and vitest uses `test.fails`. When an issue
implements an op it adds the handler **and** removes the op from its engine's pending list; a
pending op that passes (or fails for another reason) breaks the run. Every op is either handled
or pending in each runner.

When an engine implements an op but not yet a feature some of its cases need (e.g. the `cycles`
member of `to_fields` before that engine has cycles), the runner lists a **pending case rule**:
a predicate over the case (or an explicit list of case ids) with the issue that adds the feature. Matching cases run normally
and must still fail (`test.fails` / `xfail(strict=True)`); once the feature lands they pass, which
breaks the run until the rule is removed.

## Rules (chronology-engine §14)

- Every bug fix in either engine adds a vector reproducing it.
- Vectors are hand-verified, cross-checked against known dates for real-world calendars. Each case
  file says how in `verification` (and cases may cite a source in `note`).
- Vectors generated by an engine are allowed for regression coverage only when labeled
  `"generated": true` and reviewed.
- Property tests (hypothesis / fast-check) complement the vectors and live with each engine.
