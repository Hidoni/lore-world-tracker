# ADR-0003: Arbitrary-precision integer time everywhere

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

A dimension's duration in base units is "a very large number" (brief). Heat-death scales in
seconds exceed 10^100, far beyond 64-bit integers (~9.2 × 10^18) and beyond exact double
precision. Calendars must be exact. Off-by-one-second errors compound into wrong dates.

## Decision

- A **moment** is a non-negative integer of base units (`time-model.md` §2). The limit is 1000
  decimal digits.
- Python `int`. TypeScript `bigint`. JSON and API use **decimal strings**. SQLite stores moments
  as **sortable TEXT keys** (`4-digit length prefix + digits`) via a `SortableBigInt`
  TypeDecorator, so comparisons and indexes work in SQL.
- Rationals (`{num, den}`) for non-integral rates and periods. Floor rounding.
- `float`, JS `number`, `Date` and `datetime` are banned for in-world time (lint rules + review).
  Pixel coordinates are the only place where time becomes a float, after viewport projection.

## Consequences

- No accidental precision loss, and calendars of any scale work.
- Slightly more verbose code (BigInt literals, string parsing at API edges).
- SQL can't do arithmetic on moments. Aggregations (e.g. density buckets) are computed in Python
  over fetched keys. If this becomes a bottleneck, an approximate `REAL` column normalized by
  `D` may be added for bucketing only (documented upgrade path).

## Alternatives considered

- 64-bit integers: cap of about 292 billion years at second resolution. Too small for the brief.
- Floats/decimals: inexact, or lack fast native ordering in SQLite.
- Per-dimension zero-padded fixed-width strings: break when `D` grows. The length prefix avoids
  this.
- BLOB big-endian encodings: equivalent ordering but unreadable when debugging.
