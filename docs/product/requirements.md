# Requirements

This document contains:

1. the **original brief** (verbatim, the root of all requirements),
2. the **product-owner decisions** made during planning (D1–D16),
3. the **numbered requirements** derived from both, each tagged with the milestone that delivers
   it (see `docs/plan/roadmap.md`).

Issues reference requirement IDs (e.g. `R-CAL-5`). When a requirement changes, update it here in
the same PR and note the change in the PR description.

---

## 1. Original brief (verbatim)

> This is a greenfield project that will be a comprehensive fictional world lore tracker web app,
> with a TS frontend (Use `node` and `npm`) and a Python backend (use `uv`), with the suggested
> deployment method being docker compose (at the very least a dockerfile must be provided), with
> every significant feature/step being committed […]. Design every non-core feature with the idea
> that they might be expanded upon or removed in the future, as if they are all in togglable
> modules. Make sure to factor for things that might be an issue in the future, for example, if
> your plan is to use a DB, that there's already a migration plan from day one. […] Your design
> should be for a locally hosted single-user web app that will also either have a read-only
> "display" mode or an export option that produces a read-only view of the web app in a way that
> can be shared with others (could be as basic as pointing them to a read-only deployed instance
> of it on the web or as complex as "run an http server serving the exposed project").
>
> This system is an all in one fictional lore world tracker that will turn user input in a GUI
> into a thoroughly tracked, comprehensive compendium of all of their lore. This will be split up
> into various components, most of which will be optional.
> The most critical concept that this whole thing centers around is the concept of thoroughly and
> strictly tracked time. The system will track a dimension's time from its inception to its heat
> death.
>
> The following are the core components:
> 1. Dimension. The user *must* define at least one dimension, specifying its name, it is the
>    highest level entity in the lore hierarchy.
> 2. Time. Each dimension must have its own time flow defined. This is in the form of a time spec
>    with a a single unit of the lowest granularity of tracked time i.e. a base unit of "seconds"
>    or "milliseconds" and how many of those occur between the beginning of the dimension and its
>    end (Expect this to be a very large number!).
> 3. Calendars. A calendar is an interpretation of the dimension's time. It determines the time
>    spec (i.e. it defines things such as "minutes" or "hours" and how many of those are in a day,
>    week and year). At least one must be defined for the dimension as events (see below) are
>    defined at a point in time. It is important to note that time is tracked independently of any
>    specific calendar, they are just ways to interpret it. Calendars must support complex systems
>    that don't necessarily exist in the human world, for example a calendar with alternating year
>    cycles (odd years have months X, Y Z and even years have months U, V, W)
> 4. Events. Events are placed on the timeline defined at a specific moment in the dimension's
>    time and spanning a duration, defined via a specific calendar's time tracking method but
>    viewable in all of them. Events may have any number of other events linked to them in a cause
>    and effect chain, and may contain sub-events that occur in them (i.e. "War" might have a
>    "Death of X" event under it). Events may also have other optional entities linked to them,
>    like characters and so on, which will be detailed further below. Events may be defined as
>    repeating (for example a holiday or a birthday), with sub-events potentially happening in one
>    instance of a repeating event (However, since a dimension's duration is very long, you must
>    also not automatically generate every instance of a repeating event to be stored internally,
>    as this could immediately be billions of GBs of data for a complex list of events!).
>
> The following are the optional components that should implemented in the MVP (with a system
> that is designed to allow for more in the future):
> 1. Locations. A location could be as large as a galaxy or as small as a room in a house, and
>    locations can thus be contained inside of other locations. Locations can be part of events.
> 2. Species. Can be part of events.
> 3. Characters. A character can have relationships with other characters. Characters can be part
>    of events.
> 4. Languages. A spoken and/or written language.
> 5. Groups. A social/organizational group (i.e. a military or shadowy organization). Groups can
>    have sub-groups in them (i.e. a group for a city could have sub groups for its various
>    governmental departments). Can be part of events.
> 6. Miscellaneous. Anything that doesn't fit cleanly into one of the established components (for
>    example a scientific concept like "time travel" could fall here). These can have children of
>    any type. Can be part of events.
>
> The UI should provide navigation through dimensions and their timelines and hierachically
> through events, allowing the user to create things whenever they want, with structured inputs
> for the various components alongside a free WYSIWYG editor. Things should be easily linkable to
> each other visually and textually and those links should be visually explorable in a logical
> way (take inspiration from Obsidian and its graph view for example, but also a timeline view
> that shows all of a dimension's events!).
> At the end of the day this should serve as a user's living wiki of their fictional world,
> allowing them to see through everything they have made and how it all comes together while
> still allowing them to edit it and build upon it freely.

(Elided passages concern the planning process itself and are reflected in
`docs/plan/planning-log.md`.)

## 2. Product-owner decisions

The authoritative list with full wording lives in `docs/plan/planning-log.md`. In short:

| ID | Decision |
|----|----------|
| D1 | Calendar edits: impact preview; default **keep typed dates** (recompute moments); user may pin records to their current moments. |
| D2 | Fuzzy dates: **precision + circa flag**; explicit uncertainty ranges deferred (schema leaves room). |
| D3 | **Live-linked relative anchors** (events, link/fact validity, era boundaries, …); cycles rejected. |
| D4 | **Fully temporal world state**: validity periods on links and fields; as-of time cursor. |
| D5 | First calendar milestone supports **all** calendar features (leap rules + exceptions, intercalary + weeks + parallel cycles, eras + reforms, overlays). |
| D6 | **All** recurrence types: simple and advanced calendar rules, fixed intervals, limits and exceptions. |
| D7 | MVP includes **cross-dimension correspondences, personal timelines (worldlines) and alternate timelines (branches)**. |
| D8 | Consistency: **per-rule severity** (off/warning/error per vault); structural=error, narrative=warning by default. |
| D9 | **Multiple vaults** per installation (folder = SQLite + media). |
| D10 | Entities have a **home dimension or are multiversal**; links may cross dimensions. |
| D11 | **Read-only server mode in MVP**; static export post-MVP; pluggable frontend data source from day one. |
| D12 | **Visibility (public/spoiler/private)** on entities, links/fields and rich-text blocks. |
| D13 | **React** frontend. |
| D14 | **shadcn/ui + Tailwind**. |
| D15 | Implementers: **branch + PR per issue, squash self-merge on green CI**. |
| D16 | MVP also includes **images & attachments, interactive maps, language lexicon, custom fields & custom kinds**. |

## 3. Numbered requirements

Milestones: M0 Foundations · M1 Chronology engine · M2 Core platform · M3 Time core ·
M4 Frontend foundation · M5 Time UI & timeline view · M6 Content modules · M7 Temporal world
state · M8 Exploration · M9 Advanced time · M10 Media & maps · M11 Custom fields & kinds ·
M12 Sharing, backup & hardening · M13 Post-MVP.

### Vaults (R-VLT)

| ID | Requirement | MS |
|----|-------------|----|
| R-VLT-1 | Multiple vaults per installation; create, list, rename, open, delete (to trash) via UI and CLI. | M2, M4 |
| R-VLT-2 | A vault is a folder (`vault.json`, `lore.db`, `media/`, `backups/`) that can be copied/moved as a whole. | M2 |
| R-VLT-3 | Consistent vault backup (zip incl. media) and restore (migrating older backups); automatic pre-migration backups; scheduled backups with retention. | M2, M12 |
| R-VLT-4 | Vault settings: name, enabled modules, consistency severities, display preferences. | M2, M4 |

### Dimensions (R-DIM)

| ID | Requirement | MS |
|----|-------------|----|
| R-DIM-1 | A vault must contain at least one dimension before any time-bound content can be created. A dimension is an entity (page, links, etc.). | M3, M5 |
| R-DIM-2 | Time spec: base unit (singular/plural/abbreviation) and duration `D` as an arbitrary-precision integer (≤ 1000 decimal digits). | M3 |
| R-DIM-3 | `D` may be changed only if every resolved moment in the dimension stays ≤ new `D`. | M3 |
| R-DIM-4 | Optional present moment (time point) per dimension. | M3, M7 |
| R-DIM-5 | At least one calendar per dimension before events can be created; a default display calendar per dimension. | M3, M5 |

### Time core (R-TIME)

| ID | Requirement | MS |
|----|-------------|----|
| R-TIME-1 | All in-world times are integers in base units. Never floats/`Date`/`datetime`. Transmitted as decimal strings. | all |
| R-TIME-2 | Time points have anchors: `absolute`, `calendar` (date as typed) or `relative` (time slot + offset in base or calendar units). | M3 |
| R-TIME-3 | Every time point carries a precision (calendar level or `base`) and an `approximate` flag. | M3 |
| R-TIME-4 | Live propagation: changing a time slot or calendar re-resolves all dependents in the same transaction; dependency cycles are rejected. | M3 |
| R-TIME-5 | Calendar edits produce an impact preview (old/new moment per affected record); default keeps typed dates; user can pin any/all records to their current moments. | M3, M5 |
| R-TIME-6 | Durations are exact base units or calendar amounts (applied with "constrain" semantics). | M1, M3 |
| R-TIME-7 | All resolved moments must lie within `[0, D]` (structural rule). | M3 |

### Calendars (R-CAL)

| ID | Requirement | MS |
|----|-------------|----|
| R-CAL-1 | Calendars are entities of a dimension defined by a schema-versioned definition validated by the engine. | M1, M3 |
| R-CAL-2 | Strictly nested levels down to the base unit; templates with named/numbered children; uniform and variable levels. | M1 |
| R-CAL-3 | Top-unit patterns: fixed, cyclic (e.g. odd years months X,Y,Z / even years U,V,W), rule-based (modular predicates, leap rules), explicit per-index exceptions. | M1 |
| R-CAL-4 | Intercalary units excluded from regular numbering and optionally from cycles. | M1 |
| R-CAL-5 | Parallel cycles on any level (weeks, market weeks, sexagenary…), continuous or reset per parent level, skipping excluded units; several at once. | M1 |
| R-CAL-6 | Eras: forward/backward numbering, with or without year zero, boundaries at time points (anchorable to events), names/abbreviations. | M1, M3 |
| R-CAL-7 | Regimes (reforms): structure switches at a moment; numbering continuity configurable. | M1 |
| R-CAL-8 | Overlays: cycles with rational periods (moons, seasons) and named phases. | M1 |
| R-CAL-9 | Alignment: declare which date corresponds to which time point (anchorable). | M1, M3 |
| R-CAL-10 | Formatting per precision via patterns; huge numbers readable (grouping, scientific notation). | M1 |
| R-CAL-11 | Conversions both ways, unit bounds, ordinals, arithmetic and differences give identical results in Python and TypeScript (conformance suite). | M1 |
| R-CAL-12 | Preset library scaled to the dimension's base unit: Gregorian, Julian, Julian→Gregorian reform, 360-day, Shire-like intercalary, alternating-year example, Mayan Long Count with Tzolkʼin/Haabʼ cycles, lunisolar example, absolute pseudo-calendar. | M1, M5 |
| R-CAL-13 | Calendar editor UI with live preview and validation feedback. | M5 |
| R-CAL-14 | Every moment is viewable in all calendars of its dimension; a global display-calendar switcher. | M5 |

### Events (R-EVT)

| ID | Requirement | MS |
|----|-------------|----|
| R-EVT-1 | An event is an entity on exactly one timeline, with a start time point and an end given as a time point, duration, end-of-time or unknown. | M3 |
| R-EVT-2 | Sub-events (parent = event or materialized occurrence); hierarchical navigation. | M3, M5 |
| R-EVT-3 | Many-to-many directed cause → effect links with optional description. | M3, M5 |
| R-EVT-4 | Participants of any kind with a role; module-specific link types (e.g. event site). | M3, M6 |
| R-EVT-5 | Category and importance (1–5). | M3 |
| R-EVT-6 | Event page shows dates in all calendars, duration, parent chain, sub-events, causes/effects, participants. | M5 |

### Recurrence (R-REC)

| ID | Requirement | MS |
|----|-------------|----|
| R-REC-1 | Occurrences are never stored in bulk; they are computed for any window without iterating from the series start. | M1, M3 |
| R-REC-2 | Calendar rules: frequency at any level or cycle; interval; BY-constraints (values, nth, last, multiple per period, period filters such as odd years). | M1 |
| R-REC-3 | Fixed base-unit interval rules. | M1 |
| R-REC-4 | Limits: never, count, until; series bounds computed efficiently. | M1, M3 |
| R-REC-5 | Skip, move or modify single occurrences; occurrence-specific sub-events/links/notes via materialized occurrences. | M3, M5 |
| R-REC-6 | Rule changes list materialized occurrences that no longer match and let the user re-key or detach them. | M3, M5 |
| R-REC-7 | Timeline shows dense series as bands and individual occurrences when zoomed in. | M5 |

### Timelines / branches (R-TL)

| ID | Requirement | MS |
|----|-------------|----|
| R-TL-1 | Every dimension has a prime timeline; branches fork from any timeline at an (anchorable) branch point. | M3 (infra), M9 |
| R-TL-2 | Branches inherit live all records starting before the lineage cut-off; records spanning the branch point may be overridden; later records are not inherited. | M9 |
| R-TL-3 | Entities created in a branch are visible only in that branch and its descendants. | M9 |
| R-TL-4 | UI: timeline switcher, branch creation, "edit in this timeline" overrides, divergence indicators, comparison lanes, per-timeline notes. | M9 |

### Cross-dimension (R-XD)

| ID | Requirement | MS |
|----|-------------|----|
| R-XD-1 | Correspondences between two dimensions via ordered sync points (anchorable), piecewise-linear with rational rates, configurable extrapolation. | M1, M9 |
| R-XD-2 | "Concurrently in …" display on event pages; dual-dimension timeline lanes. | M9 |
| R-XD-3 | Compose correspondences along paths; flag disagreeing paths. | M9 |

### Worldlines / personal timelines (R-WL)

| ID | Requirement | MS |
|----|-------------|----|
| R-WL-1 | Any entity may have a worldline: ordered segments in (dimension, timeline) with a subjective rate; jumps optionally linked to events. UI focuses on characters. | M9 |
| R-WL-2 | A participation can be pinned to a specific segment (entity present twice at once). | M9 |
| R-WL-3 | Personal timeline view: experienced events in subjective order, subjective age. | M9 |
| R-WL-4 | Consistency rules are worldline-aware (paradox-aware). | M9 |

### Entities (R-ENT)

| ID | Requirement | MS |
|----|-------------|----|
| R-ENT-1 | Every entity has kind, name, aliases, summary, rich-text body, fields, tags, visibility, parent, home dimension (or multiversal). | M2 |
| R-ENT-2 | Generic CRUD API and generic UI (forms generated from field definitions) plus module-specific panels. | M2, M4 |
| R-ENT-3 | Soft delete to trash with restore. | M2, M4 |
| R-ENT-4 | Full history via changesets: per-entity history, recent changes, undo. | M2, M4 |
| R-ENT-5 | Optimistic concurrency via a revision number. | M2 |

### Links (R-LNK)

| ID | Requirement | MS |
|----|-------------|----|
| R-LNK-1 | Typed links with forward/inverse labels, role, data, optional validity (timeline-bound) and visibility. | M2, M7 |
| R-LNK-2 | User-defined link types. | M2, M11 |
| R-LNK-3 | Textual linking via `[[` and `@` autocomplete in rich text; mentions tracked; backlinks; unlinked mentions. | M4, M8 |
| R-LNK-4 | Visual linking: create links from graph/timeline/maps via drag or context actions. | M8 |

### Temporal world state (R-TMP)

| ID | Requirement | MS |
|----|-------------|----|
| R-TMP-1 | Existence periods for any entity (multiple intervals), anchorable to events. | M7 |
| R-TMP-2 | Temporal fields (facts) with validity periods. | M7 |
| R-TMP-3 | Global time cursor: entity pages, lists, graph and maps reflect the state at the cursor in the selected timeline. | M7, M8, M10 |
| R-TMP-4 | Derived displays: age, elapsed time, relative to present moment. | M7 |

### Modules (R-MOD)

| ID | Requirement | MS |
|----|-------------|----|
| R-MOD-1 | Module system on both tiers; per-vault enable/disable without data loss; dependency handling. | M2, M4 |
| R-MOD-2 | Each module has a doc in `docs/modules/` describing its contributions. | M6+ |

### Content modules

| ID | Requirement | MS |
|----|-------------|----|
| R-LOC-1 | Locations nest (galaxy → room), have types, can be event sites, residences and be controlled by groups (temporal). Location tree view. | M6 |
| R-SPC-1 | Species with fields (classification, typical lifespan as duration…), subspecies, origin, descent; can participate in events. | M6 |
| R-CHR-1 | Characters with fields, species, relationships (family/social/custom; directed or symmetric; temporal), memberships, residence; family tree and relationship views. | M6, M7 |
| R-GRP-1 | Groups with types, sub-groups, memberships (role/rank, temporal), leadership, inter-group relations, territory; org chart view. | M6 |
| R-LNG-1 | Languages (spoken/written/signed), writing systems, descent (family tree), speakers. | M6 |
| R-LNG-2 | Lexicon: entries (headword, romanization, pronunciation/IPA, part of speech, definitions, etymology, notes, visibility), search, CSV import/export. | M6 |
| R-MSC-1 | Misc entries with a category; can be the parent of entities of any kind; can participate in events. | M6 |

### Media & maps

| ID | Requirement | MS |
|----|-------------|----|
| R-MED-1 | Upload images/files into a vault; content-addressed storage; thumbnails; embed in rich text; cover/portrait images; gallery; safe serving. | M10 |
| R-MAP-1 | Image-based maps attached to locations; pins for locations/events/any entity; nested drill-down; time-aware pins. | M10 |

### Custom fields & kinds (R-CST)

| ID | Requirement | MS |
|----|-------------|----|
| R-CST-1 | Custom fields on any kind (type, options, temporal flag, default visibility, section). | M11 |
| R-CST-2 | Custom kinds (label, icon, color, fields, allowed parents) rendered by the generic UI. | M11 |

### UI (R-UI)

| ID | Requirement | MS |
|----|-------------|----|
| R-UI-1 | Navigation: vault → dimension → timeline → hierarchical events; entity tree by kind/parent; breadcrumbs; recent/pinned. | M4, M5 |
| R-UI-2 | WYSIWYG editor alongside structured fields on every entity page. | M4 |
| R-UI-3 | Timeline view: zoom from whole dimension to base unit, calendar ticks, lanes, sub-events, recurrence, eras, overlays, cursor, filters, minimap; branch and cross-dimension lanes. | M5, M9 |
| R-UI-4 | Graph view: global and local, filters, as-of. | M8 |
| R-UI-5 | Hierarchy, causality, family-tree and org-chart views. | M5, M6, M8 |
| R-UI-6 | Command palette and global search. | M4 |
| R-UI-7 | Dark/light themes; keyboard accessible; desktop-first; reader mode usable on mobile. | M4, M12 |

### Search (R-SRCH)

| ID | Requirement | MS |
|----|-------------|----|
| R-SRCH-1 | Full-text search over names, aliases, summaries, bodies, fields and module content (e.g. lexicon); prefix and substring; filters; visibility-aware. | M2, M4, M6 |

### Consistency (R-CON)

| ID | Requirement | MS |
|----|-------------|----|
| R-CON-1 | Rule registry with per-vault severities; findings panel; per-page indicators; suppressions with notes. | M3, M5 |
| R-CON-2 | Precision-aware evaluation (definite vs possible violations). | M3, M7 |
| R-CON-3 | Rule catalog: structural (M3), narrative (M7), module rules (M6), advanced-time rules (M9). | M3–M9 |

### Visibility & sharing (R-VIS, R-SHR)

| ID | Requirement | MS |
|----|-------------|----|
| R-VIS-1 | Visibility on entities, aliases, links, facts, field values, rich-text blocks, map pins, lexicon entries; media visibility derived from references. | M2 (data), M12 (enforcement) |
| R-VIS-2 | Authors can preview any page as a reader. | M12 |
| R-SHR-1 | Read-only server mode: mutations blocked, visibility filtering on every read path, automated leak tests. | M12 |
| R-SHR-2 | Published snapshot: sanitized vault copy with private content physically removed. | M12 |
| R-SHR-3 | Static export via a static data source (post-MVP). | M13 |

### Data safety & migrations (R-DAT)

| ID | Requirement | MS |
|----|-------------|----|
| R-DAT-1 | Alembic migrations from day one, single linear history, auto-upgrade on open with pre-migration backup. | M2 |
| R-DAT-2 | Versioned JSON payloads (calendar definitions, rich text, recurrence rules, exports) with upgrade functions. | M1, M2 |
| R-DAT-3 | Migration tests from fixture vaults created by earlier versions. | M2+ |

### Deployment (R-DEP)

| ID | Requirement | MS |
|----|-------------|----|
| R-DEP-1 | Multi-stage Dockerfile; `docker-compose.yml` with an author service bound to localhost and a read-only profile. | M0, M12 |
| R-DEP-2 | All configuration via environment variables (`LORE_*`). | M0 |

### Non-functional (R-NFR)

| ID | Requirement | MS |
|----|-------------|----|
| R-NFR-1 | Scale: 100k entities, 500k links, 100k events per vault. Timeline window query p95 < 150 ms (cold zoom-out over all 100k events < 500 ms, repeats cached: decided 2026-10-07); entity page < 300 ms locally; graph of 10k nodes interactive. | all |
| R-NFR-2 | Security: localhost binding by default; Host/Origin validation; CSRF-safe mutations; safe uploads; no raw HTML injection. | M0, M10, M12 |
| R-NFR-3 | Accessibility: keyboard navigation, ARIA (Radix primitives), sufficient contrast. | M4+ |
| R-NFR-4 | Latest Chrome, Firefox, Safari, Edge. | M4 |
| R-NFR-5 | Strict typing (mypy strict, TypeScript strict), linting, tests and CI gates on every PR. | M0 |
