# ADR-0010: Row-level changesets for history and undo

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

A living wiki needs page history and undo, including undo of large cascaded operations
(calendar proposals that move hundreds of records). History lost before a feature exists can never
be recovered, so capture must start on day one.

## Decision

- Each write transaction produces one `changeset` with row-level `changes` (before/after JSON) for
  all registered authored tables, captured by SQLAlchemy flush hooks. Bulk statements must record
  their changes explicitly.
- `change_entities` indexes changes per entity for per-entity history.
- Undo = revert a changeset when no later change touched the same rows, as a new changeset.

## Consequences

- Per-entity history, recent-changes feed, undo, and an audit trail for debugging propagation.
- Storage grows with edits. Compaction is a post-MVP maintenance task.
- Developers must not bypass the ORM silently (enforced in review and tests that compare row
  counts with change counts in service tests).

## Alternatives considered

- Per-entity snapshot revisions only: no undo for cascades, and links/facts history get awkward.
- Event sourcing for everything: too heavy for the team and the problem.
