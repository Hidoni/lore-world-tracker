# Module: `branches` — Alternate timelines

> "What if…" branches of a dimension's history that share everything before the branch point
> (D7). The data model (timelines, lineage visibility, override rows, `TimelineView`) is **core**
> (`time-model.md` §4). This module provides the API, UI and rules to create and work with
> branches. Covers R-TL-1…4.

## Summary

| | |
|---|---|
| Module id | `branches` |
| Depends on | – |
| Default enabled | yes |
| Milestone | M9 |

## Kinds

`timeline` is a core kind (the prime timeline exists for every dimension). This module enables
creating **branch** timelines.

## Tables

Core tables only (`timelines`, override rows in time-bound tables, `entity_timeline_notes`).

## API

- `POST /m/branches/timelines {dimension_id, parent_timeline_id, branch_point: TimePoint, name, summary}`:
  validates that the branch point resolves within bounds and references only records visible in
  the parent.
- `POST /m/branches/overrides {record_type, root_id, timeline_id, changes}`: creates (or updates)
  the override row for a spanning record. It validates `time-model.md` §4.4 and `recurrence.md`
  §6 (only post-cut-off aspects may change).
- `DELETE /m/branches/overrides/{record_type}/{id}`: reverts to the inherited version.
- `GET /m/branches/timelines/{id}/diff?against=parent`: records created in the branch, records
  overridden (with before/after), and inherited spanning records not overridden. Used for compare
  mode and the timeline page.
- `GET|PUT /m/branches/notes/{entity_id}/{timeline_id}`: per-timeline notes.
- Deleting a branch: the generic entity delete on the timeline entity (trash) with cascade
  confirmation listing branch-own records and descendant branches.

### Implemented (#114)

- `POST /m/branches/timelines` creates the branch through `lore.core.time.branches.create_branch`
  (core: the timeline kind's `ext` writes the row only for it). The branch point is resolved,
  stored and linked to its anchor like any time slot (`timeline.branch_point`, referenceable), so
  an anchored branch point moves with its event. An anchor to a record the parent timeline doesn't
  see (a sibling branch's event, fact or link; another lineage's branch point) is refused with
  `branch_point_invalid`; dimensions and calendars are timeless.
- `core.timeline.branch_point_invalid` (hard) reports stored branch points outside `[0, D]` or
  anchored to records the parent doesn't see.
- Branch-only entities and how lists, the tree, search and the graph show them:
  `time-model.md` §4.6. The graph also shows temporal links of the request's lineage only (of
  prime timelines without `timeline`); entity link lists without a time cursor list every
  timeline's links ("at any time"; each link carries its timeline).
- The facts list with `timeline` lists the facts visible in it (its own and those it inherits).
- Deleting: the generic entity delete with `cascade=true` (see API above).
- The sample world has "What if Aurel survived" (at the start of his assassination) with a
  branch-only group, an event and a fact.

### Implemented (#115)

- Overrides of events, facts and links (`time-model.md` §4.4), with the checks of
  `recurrence.md` §6 for series (`lore.core.time.overrides`). The override's start always follows
  its root's. Anchors in a branch see the branch's version of an event; the occurrences list takes
  `timeline`.
- The diff against the parent and per-timeline notes (`lore.core.time.branch_reads`).
- Rules `core.branch.shared_past_modified` (warning: a branch's own event, fact or link starting
  before the branch point) and `branches.override_start_changed` (hard).

### Implemented (#116)

- The timeline switcher in the top bar, the create-branch dialog (from the switcher, the
  timeline's context menu "Branch here…" at the moment clicked, and an event's "What if…" menu:
  branch at its start or end, anchored to it), badges and "Edit in this timeline" for events,
  facts (lifespans and temporal fields) and links, and "Only in <branch>" on branch-only entities
  (`frontend.md`, Branches).
- With the module disabled the switcher offers the prime timeline only and the UI offers no
  branch creation or editing. The API still answers for branches (a `tl` in a URL keeps
  working); hiding their records server-side is not done.

### Implemented (#117)

- **Compare mode** in the timeline view ("Compare" → the dimension's other timelines): each
  checked timeline gets lane groups of its own under the viewed one, on the same axis and
  read-only; a dashed marker shows where each compared branch diverges, and events a branch
  created or changed (its diff against its parent) are outlined (`frontend.md` §9.5).
- **Timeline page** (the `branches.timeline` panel on `timeline` entities): lineage, branch
  point, the diff's counts and its records (created, changed, carried over the branch point,
  eight of each with the rest counted), child branches, "View this timeline". The premise is the
  entity's summary.
- **Per-timeline notes** (the `branches.notes` panel, shown while a branch is viewed): the rich
  text editor, autosaved against the note's revision (an emptied note is deleted); readers see
  the note filtered. Module entity panels gained `useShown` for this.
- e2e E7.

## UI

- **Timeline switcher** in the top bar (tree of timelines per dimension, with the branch point
  shown). Switching sets `tl` in the URL. Every view (pages, lists, graph, maps, timeline)
  follows it.
- **Create branch:** from the timeline context menu ("Branch here"), an event page ("What if… —
  branch at the start/end of this event") or the switcher. A dialog asks for name, premise
  (summary), parent and branch point.
- **In a branch:**
  - inherited records show an "inherited from <timeline>" badge,
  - records entirely before the cut-off are read-only (shared past) with an explanation,
  - spanning records offer **Edit in this timeline**, which creates an override,
  - new records are created in the branch (branch-only entities get a badge).
- **Compare mode** in the timeline view: lane groups per selected timeline, a divergence marker,
  and differences highlighted (diff endpoint).
- **Timeline entity page:** premise, lineage, branch point, statistics, diff summary, child
  branches.
- **Per-timeline notes** section on entity pages when viewing a branch.

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `core.timeline.branch_point_invalid` | hard (core) | branch point outside bounds or referencing non-parent records |
| `core.branch.shared_past_modified` | warning | branch-own record starting before the branch point |
| `branches.override_start_changed` | hard | override whose start differs from its root (should be impossible via API; catches imports) |

## Disabling / removal notes

When disabled, the switcher only offers prime timelines, and existing branches and their records
are hidden (data preserved). Branch-only entities are hidden too.

## Future ideas

Re-parenting branches, merging a branch back ("canonize"), per-branch calendar variants, branch
comparison reports.
