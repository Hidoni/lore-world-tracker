# ADR-0018: Base-unit refinement rewrites the dimension in place and closes its history

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

A dimension counts time in an integer base unit (ADR 0003). An author who started in seconds and
later needs milliseconds must make the unit finer without moving any date (#152,
`time-model.md` §3). Every moment and base-unit quantity of the dimension is stored in that unit:
`*_t` columns, absolute anchors, base durations, interval rules, calendar leaf counts, rates
between dimensions. History (ADR 0010) stores whole rows as they were, in the unit of their time.

## Decision

- **Rewrite in place, in one transaction:** every quantity the dimension stores in base units is
  multiplied by the integer factor, then every slot is resolved again (`rebuild_time`).
  Calendar dates, calendar durations and precisions are unit-free and stay. The steps are
  `lore.chronology.refine` (pure, on documents) and `lore.core.time.refine` (the vault).
- **A maintenance command, not an app feature:** `lore vault refine-base-unit` with `--dry-run`,
  next to `compact-history`. It is rare, vault-wide and irreversible, so it takes an automatic
  backup first.
- **History is closed at the refinement:** its changeset (origin `refinement`) can't be undone,
  and neither can any changeset before it. Their stored rows hold moments in the old unit;
  writing them back would silently misplace them by the factor. The backup taken before the
  refinement is the way back.

## Consequences

- Undo stays correct without rewriting history rows, which would mean decoding and rescaling
  every stored row of every table that ever held a moment.
- Authors lose undo across a refinement. The command says so, and History marks the entry.
- New stored base-unit quantities (a new module's JSON with absolute moments) must be added to
  the refinement, or be time points or base durations, which the document walker finds.
