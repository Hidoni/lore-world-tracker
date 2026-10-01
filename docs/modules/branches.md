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
