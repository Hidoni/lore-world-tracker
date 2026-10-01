# ADR-0009: Computed recurrence with materialized exceptions

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The brief forbids storing every instance of repeating events (it could be "billions of GBs").
Single instances must still be able to carry sub-events, and D6 requires skipping, moving and
modifying individual occurrences.

## Decision

- A series stores its rule. Occurrences are computed by the engines for any window, by jumping
  directly to the window with ordinal arithmetic (never iterating from the series start). Dense
  windows return counts/bands instead of items.
- Occurrence identity = **key** (`k` or `k.j`, period-based) with `occurrence_number` for display.
- Customized occurrences are **materialized** as separate event entities
  (`series_entity_id`, `occurrence_key`, state `referenced|modified|cancelled`). Unchanged
  materialized occurrences anchor to the series' occurrence via relative anchors, so they move
  with the rule.
- Rule changes go through reconciliation proposals (keep key / rekey / detach).

## Consequences

- Storage is proportional to what the author actually customizes.
- Counting (`count` limits, occurrence numbers) needs the super-period algorithm for complex
  rules. Very complex rules may be rejected for counting.
- Window merging must handle moved occurrences entering or leaving windows.

## Alternatives considered

- Materializing occurrences up to a horizon (common in calendar apps): breaks at cosmic scales
  and creates stale rows.
- Keying overrides by original start time (iCalendar `RECURRENCE-ID`): fragile under calendar
  edits that move every occurrence. Period keys are stabler (reconciliation covers the rest).
