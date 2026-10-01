# ADR-0004: Two chronology engines bound by a conformance suite

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

Calendar conversions, arithmetic, recurrence expansion and correspondence mapping are needed:

- **on the server:** authoritative resolution on writes, transactional propagation (D3),
  calendar-edit impact previews (D1), window queries with occurrence expansion, validation,
  future non-UI clients (CLI, MCP);
- **in the browser:** interactive pickers, live calendar-editor previews, timeline ticks at
  60 fps, formatting everywhere, and a post-MVP static export with **no backend** (D11).

## Decision

Implement the engine twice, in Python (`lore.chronology`) and TypeScript (`@lore/chronology`),
both pure and dependency-free. Behavior is defined by `chronology-engine.md`/`recurrence.md` and
by shared **conformance vectors** in `spec/chronology/conformance/` that both must pass. JSON
Schemas are exported from the Python models and TS types are generated from them. Python alone
upgrades old definition versions. Viewport/tick math is TS-only.

## Consequences

- The UX stays fast and offline-capable, the server stays authoritative, and static export becomes
  possible.
- Double implementation cost for the hardest component, which is mitigated by vectors,
  property tests and a strict "same PR" change protocol. Issues for each engine area come in
  pairs (Python first, then the TS port against the same vectors).
- Drift risk is controlled by CI (both runners, schema drift checks).

## Alternatives considered

- Python only, with the browser calling the API for every conversion: laggy timeline/pickers over
  a network, and makes static export impossible.
- TS only, with the backend calendar-agnostic (client-authoritative): breaks server-side
  propagation and validation, and makes future non-UI clients second-class.
- One implementation run in both places (Rust→WASM+PyO3, Pyodide, embedded V8/QuickJS in
  Python): adds a third toolchain or heavy runtimes, and complicates debugging and Docker.
  Rejected.
