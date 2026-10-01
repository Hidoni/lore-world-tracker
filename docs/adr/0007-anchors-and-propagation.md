# ADR-0007: Live-linked time points with a dependency graph

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

D1: calendar edits keep typed dates by default (with an impact preview). D3: times can be
relative to other events and stay linked. Era boundaries, branch points, validity periods,
worldline segments and sync points can all be anchored too.

## Decision

- Every stored time is a **time point** (`anchor` + `precision` + `approximate`) where the anchor
  is `absolute`, `calendar` (as typed) or `relative` (slot reference + offset). The resolved moment
  is cached in a sortable column with a status.
- A generic **slot registry** declares which records own time slots. A `time_dependencies` table
  stores edges (slot→slot, slot→calendar, calendar→slot).
- Writes rewrite edges, reject cycles, compute the reverse-dependency closure, re-resolve in
  topological order, enforce hard structural rules and record everything in one changeset, all in
  one transaction.
- Calendar edits and recurrence-rule edits go through **proposals** (preview + per-record
  strategies + apply).

## Consequences

- Users can model "3 days after X" once, and the world stays consistent as they revise it.
- Writes can fan out (a calendar edit touching thousands of records). Mitigated by previews and
  performance budgets.
- Purging referenced records needs anchor freezing.
- Implementers must use the slot registry for any new time-bearing record (including modules).

## Alternatives considered

- Absolute-only storage, with relative input as a convenience: loses intent, so calendar edits and
  revisions silently desynchronize lore. Rejected by D1/D3.
- Recompute on read (no cached moments): makes every query depend on graph resolution, and
  indexes are impossible.
