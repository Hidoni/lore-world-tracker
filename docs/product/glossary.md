# Glossary

Canonical vocabulary for code, docs, UI and issues. **Use these exact terms.** If you need a new
term, add it here in the same PR.

## Storage & structure

| Term | Meaning |
|------|---------|
| **Vault** | A self-contained universe on disk: a folder holding `vault.json`, the SQLite database `lore.db`, a `media/` folder and `backups/`. The unit of backup, export and sharing. One installation can host many vaults. |
| **Entity** | Any lore object stored in the generic `entities` table: dimension, timeline, calendar, event, character, location, … Every entity has a **kind**. |
| **Kind** | The type of an entity (`event`, `character`, …). Core kinds come from core, others from modules; users can define **custom kinds** (`custom.<slug>`). |
| **Module** | A toggleable feature package (backend + frontend) that contributes kinds, fields, link types, API routes, UI panels/views, consistency rules, etc. Enabled per vault. |
| **Core** | Everything that is not a module: vaults, entities/links/fields framework, dimensions, timelines, calendars, events, time engine, search, history, visibility, consistency framework, timeline view. Core never imports modules. |
| **Field** | A structured property of an entity declared by its kind (or a custom field). Values live in `entities.fields` (JSON). |
| **Temporal field / fact** | A field value that is valid only for a period, stored as an **entity fact** with validity bounds (e.g. a title held from 1020 to 1035). |
| **Link** | A typed, directed relationship between two entities (`source → target`) with optional role, data, validity period and visibility. |
| **Link type** | The definition of a link's semantics: key, labels (forward/inverse), allowed source/target kinds, symmetry, temporal policy, cardinality. Defined by core/modules or by the user. |
| **Parent** | An entity's single organizational/structural parent (`entities.parent_id`), e.g. sub-event → event, city → country, sub-group → group, anything → misc entry. Drives the navigation tree. |
| **Mention** | A reference to an entity inside rich text (an `entityLink` mark). Mentions are derived data. |
| **Backlink** | An incoming link or mention, shown on the target entity's page. |
| **Multiversal entity** | An entity with no home dimension (`dimension_id IS NULL`); it exists vault-wide and can appear in every dimension. |
| **Changeset** | An atomic group of recorded row-level changes produced by one write operation. Powers history, recent changes and undo. |

## Time

| Term | Meaning |
|------|---------|
| **Dimension** | The highest-level lore entity. Owns a time spec (base unit + duration), calendars and timelines. |
| **Base unit** | The smallest tracked unit of time in a dimension (e.g. "second"). All absolute time values are integer counts of base units. |
| **Duration of a dimension (`D`)** | Number of base units from the dimension's inception (`t = 0`) to its end (`t = D`). Arbitrary-precision integer (can be astronomically large). |
| **Moment (`t`)** | An absolute time: integer `0 ≤ t ≤ D`, the number of base units elapsed since inception. **The canonical representation of time.** |
| **Span** | A pair of moments `start ≤ end`. Occupancy is half-open `[start, end)`; `start = end` is an instant. |
| **Timeline** | One version of a dimension's history. Every dimension has exactly one **prime** timeline; **branches** fork from a parent timeline at a **branch point**. |
| **Branch point** | The moment where a branch diverges from its parent. Records starting before it are shared (inherited live). |
| **Lineage** | The chain of timelines from a timeline up to the prime timeline, with the cut-off moment for each ancestor. |
| **Override** | A record in a branch that replaces, within that branch and its descendants, an inherited record that spans the branch point. |
| **Calendar** | An interpretation ("lens") of a dimension's absolute time into human-readable dates. Calendars never own time; they convert. |
| **Calendar definition** | The schema-versioned JSON document describing a calendar: levels, templates, patterns, cycles, eras, regimes, overlays, formats. |
| **Level** | A named unit size in a calendar's hierarchy (second, minute, hour, day, month, year, …). Levels are strictly nested. |
| **Template** | A concrete layout of one unit at a level as an ordered list of child units at the level below. |
| **Top level / top unit** | The coarsest level; its units form an infinite sequence indexed by an integer (`n`), e.g. years. |
| **Pattern** | The rule that picks the template for each top-unit index: fixed, cyclic, rule-based, plus explicit exceptions. |
| **Intercalary unit** | A unit that exists in the hierarchy but is excluded from regular numbering (e.g. "Midyear's Day", epagomenal days). |
| **Cycle (parallel cycle)** | A named repeating sequence on a level that runs independently of the hierarchy, e.g. a 7-day week or a 60-year cycle. |
| **Era** | A display-level year-numbering segment (e.g. BC/AD, "Third Age", reign eras). |
| **Regime** | A calendar structure valid from a moment on. Several regimes model **calendar reforms**. |
| **Overlay** | A cycle with a rational period displayed alongside dates without affecting them (moons, seasons). |
| **Date fields** | The structured form of a moment in a calendar (`{year, month, day, hour, …}` plus derived cycle/era/overlay info). |
| **Precision** | The calendar level to which a time point is known (e.g. `year`). The stored moment is the start of that unit; display is at that level. |
| **Approximate (circa)** | Flag marking a time point as uncertain ("c. 1023"). |
| **Time point** | A stored definition of a moment: an **anchor** + precision + approximate flag. |
| **Anchor** | How a time point is defined: `absolute` (a moment), `calendar` (a date as typed in a calendar) or `relative` (another **time slot** + offset). |
| **Time slot** | A named time point on a record that others may reference: `event.start`, `event.end`, `timeline.branch_point`, `fact.valid_from`, … |
| **Resolution** | Computing the moment of a time point. Resolved moments are cached in sortable columns. |
| **Propagation** | Re-resolving every time slot that (transitively) depends on something that changed (a time slot or a calendar). |
| **Duration (value)** | A length of time: either exact base units or calendar amounts (`{month: 3}`) whose length depends on where they are applied. |
| **Present moment** | A dimension's narrative "now"; the default for as-of views and relative displays ("200 years ago"). |
| **As-of view / time cursor** | Showing entities, lists, graph and maps as they are at moment `t` in timeline `T`. |
| **Existence** | The periods during which an entity exists (birth→death, founding→destruction), stored as `core.exists` facts. |
| **Worldline** | An entity's personal (subjective) timeline: ordered **segments**, separated by **jumps** (time/dimension travel). |
| **Worldline segment** | A stretch of continuous existence in one (dimension, timeline) between two moments, with a subjective-time rate. |
| **Subjective time** | Elapsed personal time along a worldline (e.g. a time traveler's age). |
| **Correspondence** | A mapping between the times of two dimensions defined by ordered **sync points**, interpolated piecewise-linearly. |
| **Sync point** | A pair (moment in dimension A, moment in dimension B) declared simultaneous. |

## Events & recurrence

| Term | Meaning |
|------|---------|
| **Event** | Core entity occupying a span on one timeline. Has optional sub-events, causes/effects, participants and recurrence. |
| **Sub-event** | An event whose parent is another event (or a materialized occurrence). |
| **Causal link** | Directed `core.causes` link from a cause event to an effect event. |
| **Importance** | Event level-of-detail priority 1 (minor) … 5 (epochal) used for timeline culling. |
| **Recurrence rule / series** | A rule describing repeated occurrences of an event (calendar rule or fixed interval). The event carrying it is the **series**. |
| **Occurrence** | One instance of a series, computed on demand; never stored in bulk. |
| **Occurrence key** | Stable identifier of an occurrence: period index `k` (and sub-index `j` when a period has several), written `"k"` or `"k.j"`. |
| **Materialized occurrence** | An occurrence stored as its own event row because it was modified, cancelled, given sub-events or referenced. |

## Quality, sharing & tooling

| Term | Meaning |
|------|---------|
| **Consistency rule** | A check (structural or narrative) producing **findings**. Each rule has a per-vault **severity**: `off`, `warning` or `error`. |
| **Suppression** | A user decision to ignore one specific finding (e.g. an intentional paradox), with a note. |
| **Visibility** | `public`, `spoiler` or `private` on entities, links, facts, field values and rich-text blocks. |
| **Author mode / reader mode** | The editing UI vs the read-only presentation used for sharing. Authors can "preview as reader". |
| **Read-only server mode** | Running the app (`LORE_READ_ONLY=true`) so it serves vault(s) without mutations and with visibility filtering. |
| **Published snapshot** | A sanitized copy of a vault with private content physically removed, meant for read-only serving/export. |
| **Static export** (post-MVP) | A build of the SPA plus a JSON data snapshot that any static HTTP server can host. |
| **Chronology engine** | The pure time library implemented twice: Python `lore.chronology` and TypeScript `@lore/chronology`. |
| **Conformance suite** | Shared JSON test vectors in `spec/chronology/conformance/` that both engines must pass. |
| **Sortable key** | TEXT encoding of a non-negative big integer whose byte order equals numeric order (`"0004" + "1023"`). |
| **Data source** | Frontend abstraction over where data comes from (`HttpDataSource`, later `StaticDataSource`). |
