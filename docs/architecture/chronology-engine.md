# Chronology engine (calendars)

> **Status: normative.** This spec defines the calendar definition format and the calendar
> algorithms. Recurrence is in `recurrence.md`. The surrounding time model (moments, anchors,
> propagation) is in `time-model.md`.

## 1. Purpose and the dual-engine policy

The chronology engine converts between **moments** (integers) and **dates** (calendar fields),
formats dates, does calendar arithmetic, expands recurrences, maps correspondences and (TS only)
computes timeline viewports and ticks.

It is implemented **twice** (ADR-0004):

| Engine | Location | Used for |
|--------|----------|----------|
| Python | `backend/src/lore/chronology/` | Authoritative resolution on writes, propagation, impact previews, window queries (occurrence expansion), validation, exports. |
| TypeScript | `packages/chronology/` (`@lore/chronology`) | Interactive UI (pickers, live calendar preview, timeline ticks, formatting everywhere), and the post-MVP static export with no backend. |

Rules:

1. **Pure and deterministic.** No I/O, no clocks, no randomness, no globals. Inputs are plain
   data and outputs are plain data. Python: no imports from `lore.core`/`lore.modules`. TS: no
   imports from the frontend app or any UI library.
2. **Same behavior, enforced by data.** Shared assets live in `spec/chronology/`:
   - `schema/*.json`: JSON Schemas **exported from the Python Pydantic models** (source of truth
     for structure). TS types are generated from them (`json-schema-to-typescript`) into
     `packages/chronology/src/schema.gen.ts`. CI fails on drift.
   - `presets/*.json`: preset calendars (§13).
   - `conformance/`: test vectors (§14). **Both engines must pass 100% of the vectors.**
3. **Change protocol.** Any behavior change edits this spec, adds or updates vectors, and updates
   **both** engines in the same PR. A PR that touches only one engine's behavior is rejected.
4. **Exact arithmetic only.** Python `int` and `fractions.Fraction`-like rationals (implemented
   on ints; see §2), TS `bigint`. No floating point anywhere, except converting to pixels in the
   TS viewport module.
5. **Schema versions.** The definition carries `schema_version`. **Only the Python side upgrades
   old versions** (a DB data migration rewrites stored definitions). The TS engine accepts only
   the current version, because the server always sends upgraded documents.

## 2. Numeric utilities (both engines)

`lore.chronology.numbers` and `@lore/chronology` `numbers.ts` (vectors: `cases/numbers/`). Errors
carry a stable code shared by both engines: `invalid_number`, `invalid_key`, `division_by_zero`.

- Moment and signed integer strings: strict parse/format (`parse_moment`/`parseMoment`,
  `format_moment`, `parse_signed`, `format_signed`). Reject leading zeros, `-0`, `+`, whitespace,
  non-ASCII digits and more than 1000 digits; moments reject negatives.
- Sortable keys (`time-model.md` §2.3): `sortable_key` / `from_sortable_key`, which rejects every
  string `sortable_key` cannot produce (`invalid_key`). Python needs these for persistence; TS
  has them for the static data source.
- Rationals `{num, den}`: normalize, add, sub, mul, div, compare, floor, frac, from-int. Python
  uses `fractions.Fraction` (exact, always normalized; never built from a float). TS has
  `BigRational` (`{num: bigint, den: bigint}`) and `rational*` functions. A zero denominator or
  divisor is `division_by_zero`.
- Big-number display (`format_integer` / `formatInteger`, options = the calendar `display`
  values of §3.11): below `scientific_threshold` digits, digit grouping by 3 with the configurable
  separator (`''` disables it). From the threshold on, scientific notation with
  `significant_digits` significant digits rounded **half to even** on the exact digits, trailing
  zeros of the mantissa dropped (`1 × 10^15`, not `1.000 × 10^15`), a carry moving to the
  exponent (`9.9996…` → `1 × 10^17`), and no grouping in the mantissa: `3.17 × 10^99`, plain-text
  form `3.17e99`. Negative numbers get a leading `-`.
- Floor division and modulo with **floor semantics** (`floor_div`/`floorDiv`,
  `floor_mod`/`floorMod`): `⌊a / b⌋`, and the modulo has the sign of the divisor
  (`-1 mod 7 = 6`, `1 mod -7 = -6`). TS `bigint` `/` and `%` truncate, so it must use the helpers.

## 3. Calendar definition (schema v1)

### 3.1 Top-level shape

The normative structure is `lore.chronology.schema.CalendarDefinition` (exported to
`spec/chronology/schema/calendar-definition.json`); the shapes in this section summarize it. The
models check structure only (shapes, id and number patterns, size limits). The rules in this
section that relate parts to each other are checked by compilation (§11). Structural conventions:

- Every model rejects unknown members. In-world integers (counts, years, moments) are canonical
  decimal strings. Small structural integers (`numbering_start`, cycle `length`/`number_start`/
  `anchor.index`, display options) are JSON integers.
- Ids are at most 64 characters: level, template, era, cycle and overlay ids match
  `^[a-z][a-z0-9_]*$`; slot ids (named children) and regime ids match `^[a-z][a-z0-9_-]*$`. Names
  are 1–200 characters.
- Optional members have defaults: `numbering_start` 1, `intercalary` false, `cycle_excluded` [],
  `exceptions` [], `cycles` [], `eras` [], `overlays` [], cycle `mode` `"continuous"`,
  `number_start` 1, `anchor.index` 0, era `abbr_position` `"suffix"`, and the `display` values
  shown in §3.11.

```jsonc
{
  "schema_version": 1,
  "levels":   [Level, …],          // fine → coarse; shared by all regimes
  "regimes":  [Regime, …],         // ≥ 1; regime 0 has "starts_at": null
  "eras":     [Era, …],            // optional
  "overlays": [Overlay, …],        // optional
  "formats":  Formats,             // optional; defaults generated
  "display":  DisplayOptions       // optional
}
```

### 3.2 Levels

```jsonc
{ "id": "day", "label": "day", "plural": "days", "abbr": "d",
  "numbering_start": 1,            // number given to the first regular child in its parent (days 1-based, hours 0-based)
  "default_template": "day" }      // template used by "run" children that omit "template"
```

- Level ids match `^[a-z][a-z0-9_]*$` and must be unique. At most 20 levels. `base` (the exact
  precision) and `intercalary` (a key of `formats`) are reserved (`level.invalid_id`).
- **Level 0** (the finest) is made of **base units**. The **last level** is the **top level**
  (e.g. `year`). Its units form an infinite sequence indexed by the **year number `Y`**
  (astronomical: …, −1, 0, 1, 2, …). The top level has no `numbering_start`, because `Y` is used
  directly. The top level does not have to be called "year", e.g. the Mayan Long Count's top level
  is the *bakʼtun*.

### 3.3 Regimes

```jsonc
{
  "id": "gregorian", "name": "Gregorian",
  "starts_at": TimePoint | null,       // null for regime 0; increasing for later regimes
  "templates": { "<template id>": Template, … },
  "top": TopPattern,
  "alignment": { "fields": DateFieldsInput, "at": TimePoint },
  "cycles": [Cycle, …]                 // parallel cycles (weeks, …)
}
```

A calendar with no reform has exactly one regime. Each regime is a complete, self-contained
structure with its own epoch (derived from its alignment). The **active regime** at moment `t` is
the last regime whose `starts_at` resolves to `≤ t`. Regime 0 is active before every other regime.

### 3.4 Templates

A template is the layout of **one unit at one level**, as an ordered list of children at the
level directly below. (For level 0, the children are base units.)

```jsonc
// Uniform: N identical children (numbered)
{ "level": "month", "uniform": { "count": "30", "template": "day" } }   // "template" optional → child level's default_template
{ "level": "second", "uniform": { "count": "1" } }                       // level 0: count of base units (no child template)

// Sequence: explicit children
{ "level": "year", "sequence": [
    { "id": "frostfall", "template": "m30", "name": "Frostfall", "abbr": "Fro" },
    { "id": "thawing",   "template": "m31", "name": "Thawing" },
    { "id": "midyear",   "template": "d1",  "name": "Midyear's Day", "intercalary": true, "cycle_excluded": ["week"] },
    { "run": { "count": "3", "template": "m30" } },                       // 3 unnamed, numbered months
    { "id": "bloom",     "template": "m30", "name": "Bloom" }
] }
```

Child semantics:

- **Named slot** (`id`, `template`, `name`, optional `abbr`): `id` is the stable **slot id**,
  unique within the template. Use the **same id for the same conceptual unit across templates**
  (e.g. `frostfall` in both common and leap year templates) so that "keep typed dates" (D1)
  and arithmetic carry over.
- **Run** (`run: {count, template?}`): `count` unnamed children.
- **Intercalary** (`intercalary: true`, named slots only): the unit exists and has length, but it
  gets **no regular number**, and it is skipped by regular ordinals and by "add N units at this
  level" arithmetic (§9). It must have an `id` (it can only be addressed by slot id).
- **`cycle_excluded: [cycle ids]`**: the unit and all its descendants at those cycles' levels are
  excluded from those cycles (e.g. Midyear's Day has no weekday).
- **Numbering**: non-intercalary children (named or run) are numbered consecutively from the
  child level's `numbering_start`, in order.

Validation: level-0 templates must be `uniform` with `count ≥ 1` and no child template. Children
must belong to the level directly below. Every template's length must be `> 0`. Template ids
match `^[a-z][a-z0-9_]*$`. At most 500 templates per regime, at most 10,000 children per sequence,
and `count ≤ 10^1000`.

**Template length** `L(T)` (in base units) = sum of the children's lengths. Computed once at
compile time with memoization (templates form a DAG by level).

### 3.5 Top pattern (which template each year uses)

```jsonc
"top": {
  "pattern": { "kind": "fixed", "template": "year" }
           | { "kind": "cycle", "templates": ["year_odd", "year_even"], "start": "1" }
           | { "kind": "rules", "default": "year_common",
               "rules": [ { "when": Predicate, "template": "year_leap" }, … ] },
  "exceptions": [ { "year": "1582", "template": "year_reform" }, … ]
}
```

- `cycle`: the template for year `Y` is `templates[(Y − start) mod len]` (floor mod). The user's
  alternating odd/even example is `["year_odd","year_even"]` with `start = 1`.
- `rules`: the first rule whose predicate matches `Y` wins, else `default`. Predicates:

  ```jsonc
  { "mod": "4", "eq": "0" }        // Y mod 4 == 0   (floor mod; eq in [0, mod))
  { "all": [P, …] } | { "any": [P, …] } | { "not": P }
  ```

  Gregorian leap years:
  `{"any":[{"all":[{"mod":"4","eq":"0"},{"not":{"mod":"100","eq":"0"}}]},{"mod":"400","eq":"0"}]}`.
  Non-periodic conditions are deliberately not expressible. Use `exceptions` for one-off years.
- **Period** `P`: `1` for fixed, `len(templates)` for cycle, `lcm` of all `mod` values for rules
  (≥ 1). Validation: `P ≤ 1,000,000`.
- `exceptions`: explicit per-year template overrides (≤ 100,000; years unique). They break
  periodicity locally and are handled by the delta mechanism in §5.2.

### 3.6 Alignment

`alignment = { "fields": {...}, "at": TimePoint }` declares that the **start** of the unit
denoted by `fields` (astronomical year, no era) happens at the moment `at`. For example,
"1 Frostfall 1 AF 00:00 is the moment of event X's start" or "is `t = 435…`". From it the
engine derives the regime's **epoch** `E` (the moment year 0 starts). `E` may be negative or larger
than `D`. `at` may be absolute, a relative anchor, or a calendar anchor in **another** calendar.
It may not be a calendar anchor in this calendar (circular; detected when the compile context
carries the calendar's `calendar_id`).

### 3.7 Parallel cycles

```jsonc
{ "id": "week", "level": "day", "length": 7,
  "names": ["Moonday", "Twosday", …], "abbrs": ["Mo", …],   // optional; else numbers
  "number_start": 1,                                         // display number = index + number_start
  "mode": "continuous" | { "reset": "year" },                // reset level must be coarser than "level"
  "anchor": { "fields": { "year": "1", "month": "frostfall", "day": "1" }, "index": 0 },
  "continue_from_previous_regime": false }
```

- **continuous**: `index(u) = (counted_ordinal(u) − counted_ordinal(anchor_unit) + anchor.index) mod length`,
  where `counted_ordinal` counts units of `level` from year 0, **skipping excluded units**.
- **reset at level R**: `index(u)` = (number of non-excluded `level`-units in the containing
  `R`-unit before `u`) + `anchor.index`, mod `length`. Here `anchor.fields` is ignored and only
  `anchor.index` (default 0) is used.
- Excluded units have **no** cycle value (`null`).
- `continue_from_previous_regime: true` (in regime ≥ 1) derives the anchor so that the first
  unit of the new regime continues the previous regime's sequence, like weekdays across the
  1582 reform.
- Several cycles may share a level (e.g. Tzolkʼin numbers 1–13 and names ×20).

### 3.8 Eras

```jsonc
"eras": [
  { "id": "bc", "name": "Before Christ", "abbr": "BC", "start": null,
    "numbering": { "direction": "backward", "first": "1" }, "abbr_position": "suffix" },
  { "id": "ad", "name": "Anno Domini",   "abbr": "AD", "start": TimePoint,
    "numbering": { "direction": "forward",  "first": "1" }, "abbr_position": "prefix" }
]
```

- Eras partition time. Era 0 has `start: null` (−∞), and later starts must resolve strictly
  increasing. Era starts are time points (D3: anchorable to events, e.g. "Third Age begins at the
  Defeat of X").
- `forward`: `era_year = Y − Y(start) + first`, where `Y(start)` is the year containing the era's
  start moment. An era starting mid-year (as Japanese eras do) has a partial first year.
- `backward`: counts down towards the next era's start.
  `era_year = Y_end − Y + first − 1`, where `Y_end` is the first year starting at or after the
  next era's start. BC/AD without year zero: 1 AD is `Y = 1`, `Y = 0` is "1 BC", `Y = −1` is
  "2 BC".
- Without eras, years are shown astronomically (`0`, `−5`).
- An era start given as a calendar anchor of **this** calendar must use the `local` anchor form
  (§3.10) with astronomical years.

### 3.9 Overlays (astronomical cycles)

```jsonc
{ "id": "moon", "name": "Silver Moon",
  "period": { "num": "2551443", "den": "1" },          // base units, rational, > 0
  "epoch": TimePoint,                                    // a moment where phase = 0
  "phases": [ { "name": "New Moon", "from": {"num":"0","den":"1"} },
              { "name": "Waxing Crescent", "from": {"num":"1","den":"16"} }, … ] }  // sorted, first from = 0
```

`phase(t) = frac((t − epoch) / period)` is an exact rational in `[0, 1)`. The phase name is the
last phase with `from ≤ phase`. Overlays never affect date structure. Seasons can be modeled as an
overlay whose period is the tropical year.

### 3.10 Time points inside definitions

Alignment `at`, regime `starts_at`, era `start` and overlay `epoch` are **time points**
(`time-model.md` §5). They may also use one extra anchor kind that is only valid inside a
definition:

```jsonc
{ "kind": "local", "fields": { "year": "1", "month": "jan", "day": "1" }, "regime": "julian" }
```

meaning "this date in this calendar (astronomical year)". The schema has two time point types:
`TimePoint` (no `local`, used everywhere outside definitions and for `alignment.at`) and
`DefinitionTimePoint` (with `local`, for `starts_at`, era `start` and overlay `epoch`). The engine resolves `local` anchors
itself after compiling the structure, which is why `alignment.at` cannot be `local`. Every other
anchor kind is resolved by the server (`time-model.md` §7) and passed to the engine as a moment
(§4).

### 3.11 Formats and display options

```jsonc
"formats": {
  "year":   "{era_year} {era}",
  "month":  "{month.name} {era_year} {era}",
  "day":    "{cycle.week}, {day} {month.name} {era_year} {era}",
  "minute": "{day} {month.name} {era_year} {era}, {hour:pad2}:{minute:pad2}",
  "intercalary": { "month": "{month.name} {era_year} {era}" }      // used when the unit at that level is intercalary
},
"display": { "circa": "c. ", "digit_group": ",", "scientific_threshold": 16, "significant_digits": 4,
             "range_separator": " – " }
```

Tokens (in braces, `{{`/`}}` escape a literal brace):

| Token | Value |
|-------|-------|
| `{<level>}` | regular number of the unit (empty for intercalary). Modifiers: `:pad2`, `:pad3`, `:ordinal` (1st/2nd…). |
| `{<level>.name}` / `{<level>.abbr}` / `{<level>.id}` | named slot info (falls back to number). |
| `{year}` | astronomical year number. |
| `{era_year}`, `{era}`, `{era.name}` | era-relative year, era abbreviation, era name. |
| `{cycle.<id>}`, `{cycle.<id>.abbr}`, `{cycle.<id>.n}` | cycle name (or number), abbreviation, number. |
| `{overlay.<id>}`, `{overlay.<id>.fraction}` | phase name, phase as a decimal with 2 digits (display only). |
| `{base}` | base-unit remainder below level 0. |

Missing formats are generated from the levels: the top-level number, then
`{<level>.name}` for levels with named slots, and numbers otherwise, coarse to fine. Unknown tokens
are validation errors.

## 4. Compilation

```
compile(definition, context) -> CompiledCalendar | [ValidationError]
context = {
  base_unit: {singular, plural, abbr},
  dimension_duration: int,
  resolved: { "<JSON pointer of a time point>": int, … }   // all non-local anchors, resolved by the server
}                                                           // (lore.chronology.schema.CompileContext)
```

Steps:

1. Structural validation (JSON Schema plus the semantic checks listed in §11).
2. Per regime: compute template lengths, child prefix sums, per-level **regular** and **total**
   unit counts per template, and per-cycle **counted** unit counts per template (excluding
   excluded units).
3. Per regime: the top pattern's period `P`, the per-period template sequence, prefix sums of
   lengths `S[0..P]` and the cycle length `C = S[P]`, per-level count prefix arrays over the
   period, and the exception table (sorted, with cumulative deltas).
4. Derive each regime's epoch from its alignment (§5.4).
5. Resolve `local` anchors (era starts, regime starts, overlay epochs) with the compiled structure.
6. Validate cross-regime and era ordering. Derive the `continue_from_previous_regime` cycle anchors.

Costs: `O(Σ template sizes + P)` time and memory. Compiled calendars are immutable and cacheable,
keyed by (definition hash, context hash): SHA-256 of the canonical JSON of the definition and of
the whole compile context (resolved anchors, base unit, `D`). Python computes the per-period
template sequence of a `rules` pattern bit-parallel (one byte per year in a big integer), so a
period of 1,000,000 years compiles in well under a second (`perf` test).

Unit counts: for every template and every level below it, the compiled template records the
total and the **regular** number of descendant units at that level. A unit is regular unless it
is itself intercalary; the children of an intercalary unit are regular at their own level (the
single day of an intercalary "Midyear" month is a regular day).

## 5. Moment ⇄ fields (single regime)

Notation: `rel = t − E`. `tmpl(Y)` is the template for year `Y`. `L` is length.

### 5.1 Year start without exceptions

```
k = floor(Y / P);  i = Y mod P           # floor semantics
rel_start(Y) = k·C + S[i]
```

### 5.2 Exceptions

For each exception year `Y_e`, `Δ_e = L(exception template) − L(tmpl(Y_e))`. Then

```
rel_start(Y) = k·C + S[i] + Σ_{Y_e < Y} Δ_e − Σ_{Y_e < 0} Δ_e
```

(prefix sums over the sorted exceptions; the second term keeps year 0 at `rel = 0`).

### 5.3 Year containing a moment

Let `cum(Y) = Σ_{Y_e < Y} Δ_e − Σ_{Y_e < 0} Δ_e`, so that `rel_start(Y) = regular_start(Y) + cum(Y)`.
`cum` is constant between consecutive exception years. Precompute, for each exception `e`
(sorted by `Y_e`), its actual start `A_e = rel_start(Y_e)` and `cum_after(e) = cum(Y_e + 1)`.
Also precompute `cum_before_all = −Σ_{Y_e < 0} Δ_e`.

```
year_of(rel):
  e = last exception with A_e ≤ rel                          # binary search over A_e
  if e exists and rel < A_e + L(template_e): return Y_e      # rel falls inside an exception year
  c = cum_after(e) if e exists else cum_before_all           # offset valid in the gap after e
  return regular_year_of(rel − c)                            # lands strictly between exceptions

regular_year_of(r):
  k = floor(r / C); s = r − k·C
  i = max index in [0, P) with S[i] ≤ s                      # binary search
  return k·P + i
```

Correctness: inside the gap between exception `e` and the next exception, `rel_start(Y) =
regular_start(Y) + c`, and the binary search guarantees `A_e + L(template_e) ≤ rel < A_next`.

Implementations must satisfy, for every `t`: `rel_start(Y) ≤ rel < rel_start(Y) + L(tmpl*(Y))`
with `Y = year_of(rel)`, where `tmpl*` honors exceptions. This is a property test in both engines.

### 5.4 Epoch from alignment

`E = resolved(at) − rel_start(Y_a) − offset_in_year(fields_a)`, where `offset_in_year` descends
the alignment fields (§5.5) from the year template.

### 5.5 Descending into a unit

Given template `T` and an offset `0 ≤ o < L(T)`:

- **uniform**: child index `c = o div L(child)` and remainder `o mod L(child)`. The child's
  regular number is `c + numbering_start`.
- **sequence**: binary-search the child prefix sums. The child's regular number is its ordinal
  among non-intercalary siblings (if not intercalary).

Repeat to level 0. The remainder at level 0 is the **base remainder**
(`0 ≤ base < L(level-0 unit)`).

### 5.6 `to_fields(t)` output

```jsonc
{
  "regime": "gregorian",
  "levels": {
    "year":  { "n": "2024" },
    "month": { "n": "3", "id": "mar", "name": "March", "intercalary": false },
    "day":   { "n": "15" },
    "hour":  { "n": "14" }, "minute": { "n": "30" }, "second": { "n": "0" }
  },
  "base": "0",
  "era":      { "id": "ad", "year": "2024", "abbr": "AD", "name": "Anno Domini" },
  "cycles":   { "week": { "index": 4, "name": "Friday", "n": 5 } },      // null when excluded
  "overlays": { "moon": { "phase": {"num":"3","den":"8"}, "name": "Waxing Gibbous" } }
}
```

In JSON (conformance vectors), every level appears top level first; an unnamed unit is
`{"n"}`, a named slot `{"n", "id", "name", "intercalary"}` with `"n": null` for an intercalary
unit; `era` is `null` and `cycles`/`overlays` are `{}` when the calendar has none. Python:
`lore.chronology.calendar.to_fields` returns `DateFields` (`as_json()` gives this shape).

### 5.7 `from_fields(fields, precision, era?, regime?, overflow)` → moment

1. Convert an era year to `Y` if `era` is given (inverse of §3.8).
2. Pick the regime: an explicit `regime`, or try each regime from latest to earliest and keep the
   results whose moment falls inside that regime's validity. **0 results** means the error
   `reform_gap`. **More than 1** means the error `reform_ambiguous` (the caller must pass
   `regime`).
3. `t = E + rel_start(Y) + Σ offsets of the chosen children` for every level from the top down to
   `precision`. Children are addressed by **slot id** or **regular number**.
4. `overflow = "reject"` (default for user input): an unknown slot id, a number out of range,
   or a missing level is the error `invalid_date` (with the offending level).
   `overflow = "constrain"`: numbers are clamped to `[numbering_start, max]`. An unknown slot id
   falls back to the regular number the slot had in the regime's **default template for that
   level** if one exists, else `invalid_date`. That template is the parent level's
   `default_template` (the slot is a child of a parent-level unit): e.g. Lastmonth (month 12 of
   the year level's default template) in a short exception year becomes its last month. A slot
   that is intercalary there, or missing, stays `invalid_date`; so does any unknown slot when the
   parent level has no `default_template`. The top level (year) is never constrained.

`precision` is a level id. Fields name every level from the top down to `precision` and none
below; any other key, a missing level or a level below the precision is `invalid_date` naming
that level. Numbers address regular units only (intercalary units only by slot id). Python:
`lore.chronology.calendar.from_fields`, raising `DateError(code, level)`. Until `local` regime
starts are resolved (#14), regimes with a `local` start never activate.

### 5.8 Unit bounds and ordinals

- `unit_bounds(t, level) → (start, end)` for the unit containing `t`.
- `ordinal(t, level)` = signed count of **regular** units of `level` between the start of year 0
  and the unit containing `t`. If `t` is inside an intercalary unit, the result is the ordinal of
  the preceding regular unit plus the flag `intercalary: true`. Computed from per-period count
  prefixes, exception count deltas and per-template count prefixes. `O(log P + depth·log width)`.
- `from_ordinal(level, m) → (start, end)`: the inverse, by binary search over the same prefix
  structures.
- `counted_ordinal(t, cycle)`: the same, counting units at the cycle's level excluding
  excluded ones.

## 6. Date field input rules (for pickers and anchors)

- Calendar anchors store `fields` as strings (`time-model.md` §5.1): numbers or slot ids. Named
  units should be stored by **slot id** and unnamed units by **number**.
- The API accepts either form. Engines normalize named units to slot ids when storing a
  user-entered anchor (Python: `normalize_fields`, which also canonicalizes numbers, e.g. `05`
  → `5`, and rejects invalid dates).
- For a level whose parent template varies (e.g. months of odd vs even years), pickers must
  offer the children of the template **actually used** by the chosen parent.
- `options(fields_prefix, level)` lists the valid children for the next level, including
  intercalary slots and their names. Pickers use it.

## 7. Regimes and reform semantics

- Each regime converts independently (own epoch). `to_fields(t)` uses the active regime at `t`.
- `from_fields` follows §5.7 step 2. Dates in a reform **gap** (e.g. Gregorian 10 October 1582
  when the switch happens after Julian 4 October) are invalid unless the caller forces a regime,
  which gives proleptic interpretation.
- Unit bounds and ordinals across a regime boundary: units are clipped at regime boundaries for
  bounds, and ordinals are computed in the regime active at `t` (they are not continuous across
  regimes unless the definitions make them so).
- Ticks and recurrence expansion process each regime's validity interval separately.

## 8. Cycles, eras and overlays at runtime

- `cycle_value(t, cycle)` per §3.7.
- `era_of(t)` per §3.8. The inverse `era_year → Y` is also provided.
- `overlay_phase(t, overlay)` per §3.9, plus `next_phase_at(t, overlay, phase_from)`, which
  returns the first moment `≥ t` at which the phase equals `phase_from`, as
  `ceil((epoch + (n + phase_from)·period))` for the smallest valid `n`.

## 9. Arithmetic

### 9.1 Uniform levels

A level is **uniform** if every template of that level, in every regime, has the same length
(typically day and finer). Adding `n` units of a uniform level adds `n · length` base units
exactly.

### 9.2 `add(t, duration, overflow = "constrain")`

For a calendar duration `{amounts, sign}`, process the levels present in `amounts` from
**coarsest to finest**:

- **variable level `X`**: decompose the current moment into fields (active regime). Compute
  `m = ordinal(level X) + sign·amount` and locate the unit with `from_ordinal`. Then re-apply the
  original finer positions inside the new unit, level by level from coarse to fine. Use the same
  **slot id** if it exists in the new parent, else the same **regular number** constrained to the
  last valid number. A position that was intercalary and doesn't exist in the new parent becomes the
  last regular child before its original index (or the first child). Finally re-apply the base
  remainder, constrained to the finest unit's length.
- **uniform level**: add `sign · amount · length`.

With `overflow = "reject"`, any constraining step raises `invalid_date`. Base durations add
exactly. Results outside `[0, D]` are returned as-is; callers enforce bounds (hard rule in
`time-model.md` §7.2).

### 9.3 `diff(t1, t2, largest, smallest)`

Returns `{amounts per level from largest to smallest, base_remainder, sign}` such that
`add(t1, amounts) ≤ t2 < add(t1, amounts + 1·smallest)` (for `t1 ≤ t2`; otherwise compute
`diff(t2, t1)` and negate). Greedy per level: estimate with ordinals, then correct with at most a
few `add` probes. Used for ages ("34 years, 2 months") and "N years ago".

## 10. Formatting

- `format(t | fields, precision, calendar, options) → string` uses `formats[precision]`, or
  `formats.intercalary[<level>]` when the deepest named unit at or above `precision` is
  intercalary, else a generated default.
- `approximate` points get the `display.circa` prefix.
- `format_span(start_tp, end_tp)` collapses shared coarse components:
  `12 – 15 Frostfall 1023`, `Frostfall – Bloom 1023`, `1023 – 1025`. Open ends render as `?`.
- Large numbers: digit grouping, and scientific notation once the digit count reaches
  `scientific_threshold`.
- The **Absolute** virtual calendar formats as `t = <grouped or scientific> <abbr>`.
- **Text parsing** of formatted dates is post-MVP. MVP input uses structured pickers.

## 11. Validation errors

`compile` returns all errors at once as `{code, path, message}`, where `path` is a JSON pointer
(Python: `lore.chronology.calendar.compile_calendar` for models, `validate_calendar` for raw JSON
documents). Codes (stable identifiers; the conformance vectors in `cases/validate/` cover every
one):

`level.duplicate_id`, `level.invalid_id`, `level.too_many`, `template.unknown_level`,
`template.child_level_mismatch`, `template.unknown_template`, `template.zero_length`,
`template.level0_not_uniform`, `template.duplicate_slot_id`, `template.intercalary_without_id`,
`template.too_large`, `top.template_wrong_level`, `top.unknown_template`, `top.period_too_large`,
`top.duplicate_exception`, `top.bad_predicate`, `alignment.invalid_fields`,
`alignment.self_reference`, `cycle.unknown_level`, `cycle.names_length_mismatch`,
`cycle.bad_reset_level`, `cycle.anchor_invalid`, `era.start_not_increasing`,
`era.local_anchor_uses_era`, `regime.first_has_start`, `regime.start_not_increasing`,
`regime.duplicate_id`, `overlay.bad_period`, `overlay.phases_unsorted`, `format.unknown_token`,
`anchor.unresolved` (a non-local time point without a resolved value in the context; absolute
anchors need one too, so the engine takes every moment from the context),
`template.unknown_cycle` (a `cycle_excluded` id that is not a cycle of the regime),
`cycle.duplicate_id`, `regime.missing_start` / `era.missing_start` (an item after the first
without a start), `era.first_has_start`, `era.duplicate_id`, `overlay.duplicate_id`,
`format.unknown_level` (a `formats` key that is not a level), `schema.invalid` (any other JSON
Schema violation, at the offending member).

Rules behind the codes, where §3 leaves room:

- **Schema violations with dedicated codes:** more than 20 levels (`level.too_many`), a level id
  not matching its pattern (`level.invalid_id`), a count of `"0"` (`template.zero_length`), more
  than 500 templates, more than 10,000 children or a count over 1000 digits
  (`template.too_large`), `intercalary` on a run (`template.intercalary_without_id`), and `era`
  on a local anchor (`era.local_anchor_uses_era`).
- **Template references:** a child template comes from the child's `template`, else the child
  level's `default_template` (`template.unknown_template` at the run/uniform member when neither
  names an existing template). It must be a template of the level directly below
  (`template.child_level_mismatch`).
- **Fields** (alignment, cycle anchors) go from the top level down without gaps, the year is a
  number, and each value is a slot id or a regular number of the template actually used by its
  parent. A cycle anchor's fields stop exactly at the cycle's level. A continuous cycle needs
  `anchor.fields` unless `continue_from_previous_regime` (invalid in regime 0); `anchor.index`
  must be `< length`; a reset level must be coarser than the cycle's level.
- **Ordering:** regime and era starts must increase strictly among the starts that are not
  `local`; `local` starts are checked when they are resolved (#14). Overlay phases start at 0,
  increase strictly and stay below 1.
- **Format tokens:** the §3.11 table. `:pad2`/`:pad3`/`:ordinal` apply to number tokens
  (`{<level>}`, `{year}`, `{era_year}`, `{base}`), not to `.name`/`.abbr`/`.id`. Cycle and overlay
  tokens must name an existing cycle (of any regime) or overlay. Unbalanced braces are
  `format.unknown_token`.

Errors report the root cause only: an engine does not add errors derived from an already invalid
part (e.g. no epoch error when the alignment fields are invalid). Structural (JSON Schema)
violations are reported before semantic checks run.

## 12. Viewport and ticks (TypeScript only)

`@lore/chronology/viewport` (pure, unit-tested):

- `Viewport = { start: bigint, span: bigint (> 0), widthPx: number }`.
- `toPx(t)`: `(t − start) · round(widthPx·1024) / span`, computed in `bigint` and converted to
  `number`, divided by 1024. Values far off-screen are clamped to ±1e7 px.
- `fromPx(x)`, `zoomAt(x, factor: Rational)` (keeps the moment under `x` fixed), `panBy(dx)`,
  `fit(start, end, paddingPx)`, `clamp(D)`. Span bounds: min 10 base units, max `D·1.25`.
- `ticks(compiledCalendar, viewport, {minSpacingPx, maxTicks})` returns
  `{major: Tick[], minor: Tick[]}`, with `Tick = {t, label, level, multiple}`:
  1. For each level from fine to coarse, and for each "nice" multiple of that level
     (sub-day levels: 1, 2, 5, 10, 15, 30 and divisors of the parent; variable levels: 1, 2, 3, 6;
     the top level: 1, 2, 5 × 10^k for any `k`), estimate the pixel spacing from the level's mean
     unit length. Pick the first (level, multiple) with spacing ≥ `minSpacingPx`.
  2. Generate ticks by walking ordinals aligned to the multiple (e.g. years divisible by
     `10^k`) inside the viewport. For each regime's validity interval separately.
  3. Major ticks are the boundaries of the next coarser level (or the next multiple
     for top-level decades/centuries). Labels use short level formats ("Frostfall", "1023",
     "14:00", "1.2 × 10^90").
  4. Never generate more than `maxTicks`. Increase the multiple instead.
- Python does not implement ticks.

## 13. Presets

`spec/chronology/presets/<id>.json` = `{id, name, description, definition, requires}`. Presets are
written with a level named `second` as level 0 (`uniform.count = 1`) and absolute alignment
values expressed in seconds relative to a parameter. Instantiation for a dimension takes
`seconds_per_base_unit` (rational):

- `1/k` (base finer than a second): set the level-0 count to `k`.
- `k` (base coarser than a second): drop levels finer than the first level whose length in
  seconds is a multiple of `k`, and make that level the new level 0 with `count = length/k`. If no
  level qualifies, return the error `preset.incompatible_base_unit`.

Required presets (MVP): `gregorian` (proleptic; BC/AD without year 0; continuous Monday-first
week; moon and seasons overlays), `julian`, `julian-gregorian` (two regimes, 1582 reform, week
continuity), `simple-360` (12 × 30), `shire-reckoning` (Yule/Lithe intercalary days excluded from
the week, years always start on the same weekday), `alternating-years` (the brief's odd/even
example), `mayan` (Long Count levels kin → winal → tun → kʼatun → bakʼtun as top; Tzolkʼin 13-number
and 20-name cycles and a 365-name Haabʼ cycle), `lunisolar-metonic` (19-year cycle of 12/13-month
years with 29/30-day months). A user's first calendar is typically instantiated from a preset and
then edited.

## 14. Conformance suite

Layout (the full format, every op's input and expected output, and the runner contract are in
`spec/chronology/conformance/README.md`):

```
spec/chronology/conformance/
  README.md
  calendars/<name>.json      # {description, definition, context}: context includes base unit and resolved anchors
  cases/<area>/<name>.json   # {description, calendar, generated, verification, cases: [{id, op, input, expected, note?}]}
```

Case kinds (`op`): `validate`, `to_fields`, `from_fields`, `unit_bounds`, `ordinal`,
`from_ordinal`, `cycle_value`, `era_of`, `overlay_phase`, `add`, `diff`, `format`,
`format_span`, `options`, `expand` / `series_bounds` / `occurrence` / `count_in_window`
(`recurrence.md`), `map` (correspondences), `preset_instantiate`. Expected values are exact.
Errors are `{"error": "<code>"}`.

Rules:

- Every bug fix in either engine adds a vector reproducing it.
- Vectors are hand-verified for the core presets (cross-checked against known real-world dates for
  Gregorian/Julian). Generated vectors (from the Python engine) are allowed for regression
  coverage but must be labeled `"generated": true` and reviewed.
- Each engine has a runner (`pytest` parametrized and `vitest` `describe.each`) that loads every
  file. Ops an engine doesn't implement yet are listed per runner with the implementing issue and
  must fail as "not implemented" (strict expected failures), so no vector is silently skipped. CI runs both on every PR that touches `spec/chronology`, `backend/src/lore/chronology` or
  `packages/chronology`.
- Property tests (hypothesis / fast-check) are in addition to the vectors: round-trip
  `from_fields(to_fields(t)) == unit start`, year-start monotonicity, `add`/`diff` consistency
  and ordinal round-trips.
