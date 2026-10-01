# Planning log

This file tracks the **planning effort itself** (the session(s) that produced the specs,
ADRs, CLAUDE.md and the GitHub backlog). Implementation progress is tracked in GitHub
issues/milestones, not here. See `docs/plan/roadmap.md` for the implementation roadmap.

## Status

- Phase: **planning in progress**
- Started: 2026-10-01
- Planner model: Claude Opus 5.5 (Claude Code)

## Decisions captured from the product owner (2026-10-01 Q&A)

Time semantics:

| # | Topic | Decision |
|---|-------|----------|
| D1 | Calendar edits vs existing events | **Preview, keep dates.** Events remember the calendar date as typed. Editing a calendar recomputes absolute moments so typed dates stay the same, after an impact preview where the user can pin any/all affected records to their current absolute moment instead. |
| D2 | Fuzzy dates | **Precision + circa.** Every time point has a precision (calendar level) and an optional `approximate` flag; it is stored as a concrete moment (start of the unit) and displayed at its precision. Schema leaves room for explicit uncertainty ranges later. |
| D3 | Relative times | **Live-linked anchors.** Event starts/ends, relationship validity bounds, era boundaries, etc. may be anchored to another record's time slot plus an offset (calendar units or base units). Moving the anchor moves dependents. Cycles are rejected. |
| D4 | World state over time | **Fully temporal.** Relationships and individual fields can carry validity periods (bounded by moments or anchors). A time cursor shows entities/lists/graph "as of" a moment. In the data model from day one. |
| D5 | Calendar features in first calendar milestone | **All:** leap rules & exceptions; intercalary days & week cycles (continuous/reset, excluded days, parallel cycles); eras & reforms; astronomical overlays. |
| D6 | Recurrence | **All:** simple calendar rules; advanced RRULE-style rules generalized to any calendar; fixed base-unit intervals; series limits (count/until) & exceptions (skip/move/modify one occurrence). Occurrences are never stored in bulk. |
| D7 | Advanced time concepts in MVP | **All three:** cross-dimension time correspondences; personal timelines (time travel / worldlines); alternate timelines (branches sharing everything before the branch point). |
| D8 | Temporal consistency | **Per-rule severity** (off / warning / error, per vault). Defaults: structural rules = error; narrative rules = warning. |

Product structure:

| # | Topic | Decision |
|---|-------|----------|
| D9 | Universes per installation | **Multiple vaults.** A vault = self-contained folder (SQLite DB + media). Unit of backup/export/sharing. Dimensions live inside a vault. |
| D10 | Entity scoping | **Home dimension or multiversal.** Entities belong to one dimension by default; can be marked multiversal (vault-wide). Links may cross dimensions. |
| D11 | Sharing | **Read-only server mode in MVP; static export later.** Frontend gets a pluggable data source from day one. |
| D12 | Secrets | **Visibility on entities, links/fields and rich-text blocks** (public / spoiler / private). Read-only views & exports omit private, fold spoilers. |

Tech & process:

| # | Topic | Decision |
|---|-------|----------|
| D13 | Frontend framework | **React** (TypeScript, Vite). |
| D14 | UI kit | **shadcn/ui + Tailwind.** |
| D15 | Git workflow for implementers | **Branch + PR per issue, agent self-merges (squash) when CI is green**; issue auto-closes. Planning docs were committed directly to `main`. |
| D16 | Extra MVP modules | **All:** images & attachments; interactive maps; language lexicon; custom fields & custom kinds. |

Other instructions from the product owner:

- Use only the GitHub repository `Hidoni/lore-world-tracker`. **Never create any other GitHub
  repositories or GitHub Projects (boards) for this.** Issues, labels and milestones inside the
  repo are fine.
- Node/npm: future agents can assume `node`/`npm` are on PATH (nvm). The planning session's
  shell lacked them; use `nvm use latest` if needed.
- Backend: Python managed with `uv`. Frontend: TypeScript with `node`/`npm`. Deployment:
  Docker (Dockerfile mandatory, docker compose suggested).
- Every significant feature/step must be committed.
- Non-core features must be designed as toggleable modules that may be expanded or removed.
- A database migration plan must exist from day one.

## Deliverables checklist

- [x] Q&A with product owner (decisions above)
- [x] `docs/product/` — vision, requirements (+ traceability), glossary
- [x] `docs/architecture/overview.md`
- [x] `docs/architecture/time-model.md`
- [x] `docs/architecture/chronology-engine.md` (calendars)
- [x] `docs/architecture/recurrence.md`
- [x] `docs/architecture/data-model.md`
- [x] `docs/architecture/modules.md`
- [x] `docs/architecture/persistence-and-migrations.md`
- [x] `docs/architecture/api.md`
- [x] `docs/architecture/frontend.md`
- [x] `docs/architecture/consistency.md`
- [x] `docs/architecture/visibility-and-sharing.md`
- [x] `docs/architecture/security.md`
- [x] `docs/architecture/testing.md`
- [x] `docs/architecture/deployment.md`
- [x] `docs/modules/*.md` (one per module)
- [x] `docs/adr/*` (key decisions)
- [x] `docs/plan/workflow.md` (agent workflow, definition of done)
- [x] `CLAUDE.md`, `README.md`, `docs/README.md`
- [x] `.github/` issue + PR templates
- [x] GitHub labels + milestones
- [x] GitHub issues (full backlog, with dependencies)
- [x] `docs/plan/roadmap.md` with issue index
- [ ] Final review pass + push

## Backlog creation progress

Issue sources are written in the planning session's scratchpad (`backlog/Mxx.md`) and created with a
script that records `key → issue number`. Every issue body ends with its backlog key
(e.g. `M1-04`), so the mapping can be rebuilt from GitHub if the scratchpad is lost.

- Labels and milestones (M0–M13) created.
- M0: #1–#7. M1: #8–#29. M2: #30–#43. M3: #44–#57. M4: #58–#71. M5: #72–#88. M6: #89–#99.
  M7: #100–#108. M8: #109–#113. M9: #114–#125. M10: #126–#132. M11: #133–#137. M12: #138–#146.
  M13: #147–#162. **All 162 issues created**, and native "blocked by" relationships are mirrored for each.
- `tools/backlog.py` helper written and tested. `docs/plan/roadmap.md` generated (issue index +
  requirement traceability; every requirement traces to at least one issue).

## Resume notes

If a new context window/session picks this up: read this file, then `git log --oneline`,
then check `gh issue list -R Hidoni/lore-world-tracker --state all --limit 300` to see what
backlog items already exist before creating more.
