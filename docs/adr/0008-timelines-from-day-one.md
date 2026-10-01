# ADR-0008: Timeline-aware data from day one

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

D7 puts alternate timelines (branches that share everything before a branch point) in the MVP.
Retrofitting branch-awareness into every time query later would mean rewriting most of the
backend.

## Decision

- Every dimension has a **prime timeline** from creation. Every time-bound row carries
  `timeline_id` and optional `overrides_id`.
- All reads of time-bound tables go through a single `TimelineView` helper implementing lineage
  visibility (`start < cutoff`) and override resolution (closest timeline wins), even while only
  prime timelines exist (M3).
- The branching UI/API is the `branches` module (M9). The data rules are core.

## Consequences

- M9 adds features without touching query code.
- Small constant overhead on every time query (a lineage CTE of length 1 in the common case).
- Records "spanning the branch point" are the only overridable inherited records. Implementers
  must validate this.

## Alternatives considered

- Branch = full copy of a dimension: simple, but the shared past would diverge silently.
  Rejected by the "shares everything before the branch point" decision.
- Adding timelines later: much more expensive, with high regression risk.
