# Architecture Decision Records

Short records of significant decisions: context, decision, consequences, alternatives.
**Before changing a decision, write a new ADR that supersedes the old one** (set the old one's
status to `Superseded by ADR-XXXX`). Use `0000-template.md`.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-monorepo-and-tooling.md) | Monorepo layout and tooling | Accepted |
| [0002](0002-sqlite-per-vault.md) | One SQLite database per vault | Accepted |
| [0003](0003-arbitrary-precision-time.md) | Arbitrary-precision integer time everywhere | Accepted |
| [0004](0004-dual-chronology-engines.md) | Two chronology engines bound by a conformance suite | Accepted |
| [0005](0005-module-system.md) | Static module registry, per-vault toggles, single migration history | Accepted |
| [0006](0006-generic-entity-model.md) | Generic entities with JSON fields and typed links | Accepted |
| [0007](0007-anchors-and-propagation.md) | Live-linked time points with a dependency graph | Accepted |
| [0008](0008-timelines-from-day-one.md) | Timeline-aware data from day one | Accepted |
| [0009](0009-recurrence-without-materialization.md) | Computed recurrence with materialized exceptions | Accepted |
| [0010](0010-changesets.md) | Row-level changesets for history and undo | Accepted |
| [0011](0011-visibility-and-published-snapshots.md) | Visibility model, published snapshots and leak tests | Accepted |
| [0012](0012-frontend-stack.md) | Frontend stack and DataSource abstraction | Accepted |
| [0013](0013-api-contract.md) | REST + OpenAPI-generated TypeScript client | Accepted |
| [0014](0014-agent-workflow.md) | Issue-driven agent workflow with self-merge on green CI | Accepted |
