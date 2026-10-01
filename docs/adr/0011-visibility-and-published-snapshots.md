# ADR-0011: Visibility model, published snapshots and leak tests

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

D12 requires public/spoiler/private visibility on entities, links/fields and rich-text blocks.
D11 requires a shareable read-only mode. A single leak (a private name in a search snippet, a
graph edge, a backlink count) breaks trust.

## Decision

- Visibility columns on every user-facing authored row type, field-level overrides, and block-level
  wrappers in rich text. Effective visibility = most restrictive along references.
- A per-request `VisibilityPolicy` applied in SQL by every read helper. Rich text is filtered by a
  dedicated function. Search has separate public/restricted FTS columns.
- Reader deployments serve **published snapshots**: sanitized vault copies where private data is
  physically deleted.
- A **canary leak-test suite** calls every GET route in reader mode (and against a published
  snapshot) and fails on any canary string. Routes without a test recipe fail the suite.

## Consequences

- Every new read endpoint costs a leak-test recipe. This is intentional.
- Publishing is an explicit author action that produces an artifact with a lifecycle (re-publish
  to update).

## Alternatives considered

- Filtering only at the API serialization layer: easy to miss derived data. Rejected as the sole
  mechanism.
- Separate "public vault" maintained by hand: duplicate work, and it drifts.
