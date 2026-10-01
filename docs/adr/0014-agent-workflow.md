# ADR-0014: Issue-driven agent workflow with self-merge on green CI

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

The project will be implemented over time by many AI agent sessions, possibly in parallel. The
product owner chose (D15) branch + PR per issue with the agent self-merging when CI is green.
Every significant step must be committed (brief). Only the repository
`Hidoni/lore-world-tracker` may be used. No other repositories or GitHub Projects boards.

## Decision

- **GitHub issues are the task backlog**, grouped by **milestones** (M0–M13) and labeled by
  type/area/module/priority/size. Dependencies are recorded as GitHub "blocked by" relationships
  where available and always listed in the issue body.
- **Design lives in `docs/`.** Issues reference spec sections instead of duplicating them.
- One issue → one branch (`<issue>-<slug>`) → one PR (`Closes #<issue>`) → CI green → squash
  merge by the agent → issue auto-closes.
- Claiming: an agent adds the `status:in-progress` label and a comment before starting, so parallel
  agents skip claimed issues.
- Specs change in the same PR as the code that needs the change. Significant decisions get a new
  ADR.

The full procedure is in `docs/plan/workflow.md`.

## Consequences

- Progress is visible in GitHub, and each feature lands as one reviewable squash commit.
- CI is the safety net, so it must be comprehensive (`testing.md` §5).
- Parallel agents can conflict on Alembic heads and generated files. The workflow defines how to
  rebase and resolve.

## Alternatives considered

Plan files on disk only (no live status, harder parallelism); direct commits to main (no CI gate
before merge); waiting for human merges (slows progress; the product owner chose self-merge).
