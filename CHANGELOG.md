# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Releases happen at the milestones listed in
`docs/plan/roadmap.md` (the first is v0.1.0, at the end of M2).

## [Unreleased]

## [0.1.0] - 2026-10-05

The first release that writes vaults: the core platform (M2) on top of the foundations (M0) and
the chronology engine (M1). It has no UI for worlds yet (M4); everything is reachable through the
`/api/v1` API and the `lore` CLI.

### Added

- **M0 Foundations** (#1–#7, #167):
  - Backend scaffold: FastAPI app factory, `LORE_*` settings, `lore` CLI (`serve`, `openapi`),
    `/api/v1/health` and `/api/v1/meta`, structured logging with request ids.
  - HTTP hardening: Host allowlist, mutation guard (`X-Lore-Client`, `Origin`), security headers
    and CSP, request size limits, problem+json errors.
  - Frontend workspaces: `@lore/web` SPA shell (React, TanStack Router/Query, Tailwind, shadcn)
    and the `@lore/chronology` package skeleton.
  - API contract pipeline: OpenAPI → generated TypeScript types, typed client, drift check.
  - Makefile entry point, dev orchestration (`make dev`), GitHub Actions CI (backend, frontend,
    contract, chronology, e2e, docker) and Dependabot.
  - Multi-stage Docker image and `docker-compose.yml` (author instance on `127.0.0.1:8080`).
- **M1 Chronology engine** (#8–#29):
  - The time engine in Python (`lore.chronology`) and TypeScript (`@lore/chronology`), sharing one
    spec, exported JSON Schemas and conformance vectors that both engines pass.
  - Calendars: definition validation and compilation, moment ⇄ fields conversions, unit bounds,
    ordinals and picker options, parallel cycles (weeks), intercalary units, eras, regimes
    (calendar reforms) and local anchors, astronomical overlays (moons, seasons).
  - Calendar arithmetic (add with constrain/reject, diff by largest unit) and formatting
    (patterns, defaults, intercalary formats, spans, large numbers).
  - Calendar preset library with base-unit scaling.
  - Recurrence rules: intervals, calendar rules, filters and selectors, cycle frequencies,
    counts, exclusions, occurrence numbers and window expansion without bulk storage.
  - Correspondence mapping between dimensions.
  - Timeline viewport math, calendar-aware ticks and tiles.
  - Cross-engine differential fuzzing (`make test-differential`) and benchmarks (`make bench`).
- **M2 Core platform** (#30–#43):
  - Vaults: a data directory of vault folders (`vault.json` + one SQLite database each), with a
    registry, per-vault locks and engines, and the vault API and `lore vault` CLI.
  - Migrations: per-vault Alembic upgrades on open with an automatic pre-migration backup,
    `lore vault migrate` and `lore db check`/`revision` tooling.
  - Core schema v1 (entities, aliases, tags, links, link types, mentions) with exact sortable
    integers and UUIDv7 ids.
  - The backend module framework: module specs, registries of kinds, fields and link types,
    per-vault module enablement.
  - Entities: create, read, update, trash, restore and purge with parent rules and optimistic
    concurrency; listing, the navigation tree, children, the trash and field value suggestions.
  - Links: core and custom link types, link CRUD, per-entity links and backlinks.
  - History: every write is a changeset; the recent changes feed, per-entity history and undo.
  - Rich text: document validation, text and mention extraction, mentions and reader filtering.
  - Search: FTS5 full-text search (incl. trigram matching) and the quick switcher, kept current in
    the write transaction, with reindexing.
  - Visibility: author and reader policies (public, spoiler, private), `?as_reader=true` previews
    and the canary leak-test harness.
  - Backups: manual zip backups, scheduled backups with retention, and restore into a new vault.
  - Maintenance: `lore vault check` (integrity, foreign keys, derived data), `reindex` and
    `optimize`, plus a daily `PRAGMA optimize`.
  - The sample world generator (`make sample-vault SIZE=tiny|small|medium|large`) and the first
    golden fixture vault, which every later migration is tested against.

[Unreleased]: https://github.com/Hidoni/lore-world-tracker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Hidoni/lore-world-tracker/releases/tag/v0.1.0
