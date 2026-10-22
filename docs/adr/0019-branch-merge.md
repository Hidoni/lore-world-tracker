# ADR-0019: Merging a branch combines it into its parent, with a choice per conflicting record

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Branches (D7, ADR-0008) share everything before their branch point. #158 asks for two
operations the MVP left out (`time-model.md` §14): moving a branch under another timeline, and
merging a branch's divergence back into its parent ("canonize a branch"). Re-parenting has one
natural meaning. Merging does not: the parent has its own records after the branch point, which
the branch never saw ("Aurel dies" in the parent, "Aurel lives" in the branch). We considered
three answers:

1. **Swap:** the branch's history becomes the parent's, and the parent's old future moves into the
   branch, which becomes the "old canon". This is lossless and needs no choices, but the result
   differs from what "merge" suggests. Some records (fact and link overrides) would also have to
   trade roles, and anchors to their rows would read the other version.
2. **Combine:** the branch's records join the parent next to the parent's own future, and the
   author resolves contradictions by hand.
3. **Combine with a choice per record:** like 2, but the preview lists every live record of the
   parent after the branch point, and apply keeps or discards each one.

The product owner chose 3.

## Decision

- Both operations are **proposals** like calendar and recurrence edits: a preview stored for an
  hour (`proposals.kind = 'branch'`), then an apply that is one changeset and one undo. The
  preview is the apply run in a SAVEPOINT and rolled back. Apply plans again and is stale
  (`409`) when the plan differs from the preview's.
- **Merge** moves the branch's own rows to the parent and merges its overrides into what the
  parent saw. If that was the parent's own override, the branch's override replaces it. If it was
  the parent's own record, the record takes the override's changes. If it was an ancestor's
  record, the override becomes the parent's. The branch's child branches, branch-only entities
  and (where possible) notes follow, and the empty branch goes to the trash. The parent's live
  records at or after the branch point are **conflicts** with the strategies `keep` (default)
  and `discard`. Discarding reverts an override, or trashes an event, fact or link.
- **Re-parent** drops the overrides of records the branch no longer inherits spanning its cut-off.
- After either operation, branch points anchored to records their parent no longer sees are
  pinned to their moment, and time points anchored to a removed override or to the merged
  branch's branch point are frozen, as a purge freezes them.

## Consequences

- Nothing is lost silently: discarded records are in the trash, the merged branch too, and one
  undo restores the vault as it was.
- The parent's other branches after the branch point inherit the merged records that start before
  their own branch point. The preview names these branches (`siblings`).
- Records the merge doesn't know how to trash (worldline segments, module records that aren't
  overrides) can only be kept. A module that wants a discard for them needs a trash hook here.
