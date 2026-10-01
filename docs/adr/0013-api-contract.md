# ADR-0013: REST + OpenAPI-generated TypeScript client

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

Backend and frontend evolve together in one repo, and many agents will change both. The contract
must be explicit and checked automatically.

## Decision

- JSON REST API under `/api/v1`, defined by FastAPI + Pydantic models. **The generated OpenAPI is
  the contract.**
- `openapi-typescript` generates `frontend/src/api/schema.gen.ts`, and `openapi-fetch` consumes
  it. CI regenerates and fails on diff.
- `snake_case` JSON end to end. Big integers are decimal strings. Errors are RFC 9457 problem+json
  with stable `code`s. Optimistic concurrency uses `revision`. Write responses include
  `affected` metadata for cache invalidation.

## Consequences

- Type errors surface at compile time when the API changes, and agents can't drift silently.
- Conventions (operation ids, response models) must be followed for good generated types.

## Alternatives considered

GraphQL (more machinery, weaker fit for file uploads/streams and simple caching); tRPC (TS-only);
hand-written TS types (drift).
