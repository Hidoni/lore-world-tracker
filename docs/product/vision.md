# Product vision

## One-liner

A locally hosted, single-user **living wiki for fictional worlds** in which **time is tracked
strictly and exhaustively**, from a dimension's inception to its heat death. Everything else
(characters, places, peoples, languages, organizations, concepts) hangs off that time backbone,
and everything links to everything.

## Who it is for

- **The author** is one worldbuilder (novelist, game master, game designer, hobbyist) running
  the app on their own machine (Docker or dev setup). They have full control and no accounts.
- **Readers** are friends, players and collaborators. They get a **read-only** view of
  a vault, with private notes and secrets removed and spoilers folded.

## What it does

1. Turns structured input plus free-form rich text into a cross-linked compendium.
2. Keeps one canonical time axis per dimension (an integer count of base units). Any number of
   calendars act as lenses over it, and each can be as weird as the world needs.
3. Places events on timelines with sub-events, cause-and-effect chains, participants and
   recurrence rules. Recurrence is never expanded into billions of stored rows.
4. Tracks how the world changes. Relationships, field values and existence have validity periods,
   so any page, list, graph or map can be viewed **as of** any moment.
5. Supports alternate timelines (what-ifs), time flowing differently between dimensions, and time
   travelers whose personal timelines differ from the world's.
6. Lets the author explore everything visually: a zoomable timeline from the cosmic scale down to
   the base unit, an Obsidian-like graph, hierarchy and causality views, family trees, and maps.
7. Flags contradictions with configurable strictness (off / warning / error per rule).

## Principles (in priority order when they conflict)

1. **Never lose or corrupt the author's data.** Migrations are planned from day one, backups are
   taken before risky operations, history and undo come built in, and vaults are portable folders.
2. **Time is the backbone and it is exact.** Absolute time is an arbitrary-precision integer.
   Floats, `Date` and `datetime` never represent in-world time. Calendars interpret time and never
   own it.
3. **Strict, with escape hatches.** The app knows a great deal about temporal consistency, but
   fiction breaks rules on purpose (time travel, paradoxes). Every narrative rule can be turned
   down or suppressed per finding.
4. **Everything is linkable and every link can be traversed.** Typed links, mentions, backlinks,
   graph and timeline all come from the same link model.
5. **Structure plus freedom.** Every kind has structured fields and a free WYSIWYG body. Users
   can add custom fields and custom kinds.
6. **Modular by default.** Every non-core feature is a toggleable module that can be expanded or
   removed without surgery on the core.
7. **Scale without fear.** Cosmic durations (10^100+ base units), deep hierarchies and tens of
   thousands of entities must work smoothly.
8. **Safe to share.** Visibility is part of the data model, and a shared view can never leak
   private content.

## Non-goals (for the MVP)

- Multi-user editing, accounts, permissions, real-time collaboration.
- Hosting as a SaaS; the app may be exposed publicly **only** in read-only mode.
- Native mobile/desktop apps. The UI is a desktop-first web app, and reader mode should be usable
  on mobile.
- AI features. These are a likely future module (e.g. an MCP server over the vault), and the
  architecture keeps that door open.
- UI translation (i18n). Content is full Unicode; UI strings are English.
- Third-party plugin loading at runtime. Modules are first-party and compiled in.

## MVP definition

The MVP is done when an author can, in one Docker deployment:

- create several **vaults**, each with several **dimensions** (time spec + calendars),
- define calendars with **leap rules and exceptions, intercalary days, week and parallel cycles,
  eras, reforms and astronomical overlays**, and see every date in every calendar,
- create **events** with precision/circa dates, relative (live-linked) anchors, sub-events,
  causal chains, participants and **all recurrence types** (with per-occurrence changes and
  sub-events),
- edit a calendar and get an **impact preview** that keeps typed dates by default,
- use the **Locations, Species, Characters, Groups, Languages (with lexicon) and Misc** modules,
  plus **images/attachments, interactive maps and custom fields & custom kinds**,
- give relationships, fields and existence **validity periods** and browse **as of** any moment,
- create **alternate timelines**, define **cross-dimension correspondences** and model
  **personal timelines** of time travelers,
- explore via the **timeline view**, **graph view** (global and local), hierarchy, causality and
  family-tree views, backlinks and search,
- see and configure **consistency findings**,
- mark things **private/spoiler** and run a **read-only server** (ideally from a published
  snapshot) for readers,
- back up and restore a vault, and upgrade the app without losing data.

Post-MVP candidates are listed in `docs/plan/roadmap.md` (milestone M13): static export,
Markdown/Obsidian export, portable JSON import/export, an MCP/AI module, explicit uncertainty
ranges, log-scale "cosmic" timeline axis, map territories over time, custom script fonts, and more.
