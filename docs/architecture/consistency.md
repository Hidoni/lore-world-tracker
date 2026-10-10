# Consistency engine

> Time is "thoroughly and strictly tracked" (brief), yet fiction breaks rules on purpose. D8:
> every rule has a **per-vault severity** (`off` / `warning` / `error`). Structural rules default
> to error, narrative rules to warning, and specific findings can be suppressed as intentional.

## 1. Concepts

| Term | Meaning |
|------|---------|
| **Rule** | A named check owned by core or a module (`<owner>.<area>.<name>`). |
| **Hard rule** | Structural invariant that cannot be configured. Always `error`, always blocks writes. |
| **Configurable rule** | Severity set per vault. Default from the rule definition. |
| **Finding** | One rule violation about one or more subjects (records). |
| **Certainty** | `definite` or `possible` (when precision/circa makes the violation uncertain, §4). |
| **Fingerprint** | `sha256(rule_id + sorted subject ids + discriminator)`, stable across re-evaluations. |
| **Suppression** | User decision that a fingerprint is intentional, with a note. Suppressed findings are hidden by default. |

## 2. Rule definition (backend)

```python
@dataclass(frozen=True)
class RuleDef:
    id: str                                   # "core.event.effect_before_cause"
    owner: str                                # "core" or a module id (must match the id prefix)
    title: str
    description: str                          # shown in "explain"; describe how to fix
    category: Literal["structural", "narrative", "advanced_time", "module"]
    default_severity: Literal["off", "warning", "error"]
    configurable: bool                        # False = hard rule
    triggers: tuple[Trigger, ...]             # record types / link types / field keys that affect it
    check: Callable[[RuleContext, frozenset[SubjectRef]], Iterable[FindingDraft]]   # incremental
    scan: Callable[[RuleContext], Iterable[FindingDraft]]                            # full scan (SQL-backed)
    quick_fixes: tuple[QuickFixDef, ...] = ()  # optional automated remedies offered in the UI
```

Implementation: `lore.core.registry.RuleDef` (with `Trigger` and `QuickFixDef`). Modules register
rules in `ModuleSpec.consistency_rules`; core's are `lore.core.consistency.rules.CORE_RULES`. The
registry endpoint lists those of core and the enabled modules. The engine is
`lore.core.consistency` (#55): `engine` (evaluation, blocking, scans), `compare` (§4), `rules`,
`service`/`router` (the API).

- **Rule contract.** `check(ctx, subjects)` returns **every** finding of the rule that involves
  one of the subject entities (findings about those subjects it doesn't return are deleted);
  `scan(ctx)` returns all of them. Both yield `FindingDraft(rule_id, subjects, message,
  certainty, discriminator, timeline_id, data)`; subjects are entity ids in a meaningful order.
- **Triggers.** `Trigger("record", <kind>|"*")`: an entity of the kind whose row, or any
  recorded row it owns (events, calendars, … including propagation's bulk updates), changed.
  `Trigger("link_type", <key>|"*")`: the ends of changed links of the type.
  `Trigger("field", <key>)`: entities whose field changed. Trashed entities have no findings.
  A link is none of its ends' records: a changed link fires `link_type` triggers only (decided
  with #235: writing a link doesn't move its ends, and re-checking both ends' time rules made
  every link cost as much as two event edits). A rule that reads links declares their types.
- **Sets, not records** (#235). `check` and `scan` read in sets. A rule that compares time
  points selects its candidates on stored moments, asks `RuleContext.preload` for the slots of
  those whose moments conflict and only then reads `point`s (each resolved once per context);
  `Resolver.preload` loads them with the slots their specs resolve through. A `check` must reach
  its rows from its subjects through an index, whatever the vault's size: the cost of a write's
  check may not grow with the vault (`tests/consistency/test_consistency_perf.py`). Findings are
  stored with bulk statements.

`RuleContext` gives access to the session, `TimelineView`, the existence/as-of helpers, compiled
calendars and the vault settings. Rules are pure readers. Only quick fixes write, and they do so
through normal services.

## 3. Evaluation

1. **Incremental, in the write transaction.** After a service writes (and time propagation has
   run), the consistency service maps changed records to affected subjects via rule triggers
   (including records whose resolved times changed through propagation). It runs `check` for those
   subjects, upserts findings by fingerprint and resolves findings that are no longer produced.
2. **Blocking.** If the write produces a new **definite** finding for a rule whose effective
   severity is `error`, the transaction is rolled back with `422 consistency_error`, listing the
   findings. The client may resend with `suppress: [{fingerprint, note}]` ("save anyway, this is
   intentional"). The write then succeeds and the suppressions are recorded in the same changeset.
   Hard rules cannot be suppressed.
3. **Full scan:** `POST /consistency/scan` runs every enabled rule's `scan`. It runs automatically
   after migrations that touch time data, after module enable/disable, and after severity
   changes from `off`. Target: < 10 s for 100k entities. Rules must implement `scan` with
   set-based SQL, not per-entity Python loops.
4. **Disabled modules** are not evaluated. Their findings are hidden, not deleted.

Implementation (decided with #55 where the above is silent):

- **Every write is checked.** The vault's session factories carry the engine (`OpenVault` with
  its module registry), so API requests, the CLI and scripts all go through it: each time a
  session is about to write a changeset (at commit, or an undo's own `write_now`), before history
  records it. Repairs (`lore vault reindex`, which also rescans) call `record_only(session)`:
  findings are updated, nothing blocks.
- **Fixed findings are deleted** (not kept as resolved). Setting a rule `off` deletes its
  findings; leaving `off` scans it. Suppressions are kept, so a finding found again stays
  suppressed.
- **Save anyway.** `suppress` items name a finding by `fingerprint`, or by `rule_id` for every
  new blocking finding of that rule the write produces: a create's findings name the new entity,
  whose id is new on every attempt. Unknown fingerprints, or rules without a blocking finding,
  are `422 validation_error` on `suppress`. Suppressions requested for other findings of the
  write or for open findings are recorded too; hard-rule ones are ignored (they still block).
  Every write takes `suppress`: entity and link create/update, the proposal applies, and an
  optional body `{suppress}` on trash, restore, occurrence materialize/delete and undo. An undo
  that would add a blocking finding answers `409 revert_conflict` with `context.findings`.
- **Calendar proposals.** Records a proposal's apply gives a strategy explicitly
  (`time-model.md` §7.4) don't block on **hard** rules (`accept`); their findings are recorded.
  Configurable error rules (e.g. `core.recurrence.invalid_rule`) still need `suppress`.
- **Scans** run on `POST /consistency/scan`, after module enable/disable, when a rule leaves
  `off`, on the first author-mode open after a schema change (`vault_meta.
  consistency_scanned_revision`) and in `lore vault reindex`.
5. **Timelines:** narrative rules evaluate per timeline lineage (`TimelineView`). A finding
   records `timeline_id` when it is timeline-specific (e.g. only in a branch).

## 4. Precision-aware comparisons

Each time point `p` has stored moment `t(p)`, uncertainty extent `[lo, hi)` (`time-model.md`
§5.3) and an `approximate` flag. For a required relation `a ≤ b`:

- **Definite violation:** `lo(a) ≥ hi(b)` (even the earliest possible `a` is after the latest
  possible `b`) and neither point is approximate.
- **Possible violation:** not definite, but `t(a) > t(b)`, or the condition above holds with an
  approximate point.
- Otherwise there is no finding.

Possible violations are recorded with `certainty: possible` and shown at `info` level (hidden
unless "show uncertain" is on). They never block writes. Shared helpers in
`lore.core.consistency.compare` implement this once. Rules must use them.

Findings API (`api.md` §2): author-only. The list shows rules that are evaluated; `severity` is
the rule's effective one, `info` for possible findings; order: error, warning, info, then the
most recently found first (decided with #55).

## 5. UI

- **Findings panel** (`/v/$vault/consistency`): filter by severity, certainty, rule, owner,
  entity, timeline. Each finding shows a message, linked subjects, "explain" (rule description)
  and quick fixes.
- **Badges:** entity pages, tree nodes and timeline items show the count/severity of open
  findings.
- **Rule settings:** a table of rules grouped by owner, with severity selectors (hard rules shown
  locked) and descriptions.
- **Save-anyway dialog:** lists blocking findings, requires a note, and resends with
  suppressions.

## 6. Rule catalog (initial)

Core's rules as implemented (#55): the hard rules below except the M9 ones (time statuses come
from the stored `time_status`: `out_of_bounds`, `cycle`, `invalid_date` (also `calendar_error`)
and `unresolved_ref`; `end_before_start` from stored moments; one `core.parent.cycle` finding per
cycle), `core.recurrence.invalid_rule`, `core.time.anchor_to_trashed` (status `trashed_ref`),
`core.event.subevent_outside_parent` (series parents aside), `core.event.effect_before_cause`
(same dimension only) and `core.event.duplicate_name_same_time` (names compared ignoring case
and accents; possible when a start is circa). The other core rules arrive with their features.

Hard rules (core, `error`, not configurable):

| Id | Check |
|----|-------|
| `core.time.out_of_bounds` | resolved moment outside `[0, D]` |
| `core.time.end_before_start` | events, validity periods, worldline segments |
| `core.time.cycle` | dependency cycle (normally rejected at write; reported if data arrives via import/migration) |
| `core.time.invalid_date` | calendar anchor no longer forms a valid date |
| `core.time.unresolved_anchor` | reference purged and not frozen |
| `core.calendar.invalid` | calendar definition fails to compile |
| `core.parent.cycle` / `core.parent.not_allowed` | parent tree integrity |
| `core.correspondence.non_monotonic` (M9) | sync points not strictly increasing in both dimensions |
| `core.timeline.branch_point_invalid` (M9) | branch point outside bounds or referencing non-parent records |

Configurable, default `error`:

| Id | Check |
|----|-------|
| `core.recurrence.invalid_rule` | rule fails validation after a calendar change |

Narrative, default `warning`:

| Id | Owner | Check |
|----|-------|-------|
| `core.event.subevent_outside_parent` | core | child span not within parent (or occurrence) span |
| `core.event.effect_before_cause` | core | effect starts before cause (via correspondence across dimensions; subjective order when worldlines apply) |
| `core.event.participant_not_existing` | core | participant's existence (or worldline) does not cover the event |
| `core.fact.overlap` | core | overlapping facts for a single-valued temporal field |
| `core.fact.outside_existence` | core | fact validity outside the entity's existence |
| `core.link.outside_existence` | core | temporal link validity outside either endpoint's existence |
| `core.time.anchor_to_trashed` | core | anchored to a trashed record |
| `core.branch.shared_past_modified` | branches | branch-own record starting before the branch point |
| `characters.parent_born_after_child` | characters | parent's existence starts after the child's |
| `groups.member_outside_group_existence` | groups | membership validity outside the group's existence |
| `locations.event_at_nonexistent_location` | locations | event site does not exist at the event's time |
| `locations.child_outside_parent_existence` | locations | child location exists outside the parent's existence |
| `species.member_before_emergence` | species | an entity of a species exists before the species emerged |
| `languages.speaker_outside_existence` | languages | speaker link outside the language's existence |
| `maps.pin_target_missing` | maps | pin points to a trashed/hidden entity |
| `languages.entry_outside_existence` | languages | lexicon attestation period outside the language's existence |
| `worldlines.absent_participant` | worldlines | participation not covered by any segment |
| `worldlines.ambiguous_participation` | worldlines | several segments cover the participation and none is chosen |
| `worldlines.jump_event_mismatch` | worldlines | departure/arrival events don't match segment ends/starts |
| `correspondences.inconsistent_paths` | correspondences | two correspondence paths disagree |

Informational (default `off`, can be enabled):

| Id | Owner | Check |
|----|-------|-------|
| `characters.concurrent_spouses` | characters | more than one spouse link valid at the same time |
| `worldlines.self_encounter` | worldlines | an entity's segments overlap in the same timeline (meets itself) |
| `worldlines.causal_loop` | worldlines | an event chain causes an event in its own past (bootstrap paradox) |
| `core.event.duplicate_name_same_time` | core | two events with the same name overlapping in time |
| `groups.leader_not_member` | groups | leader without an overlapping membership |
| `maps.pin_outside_map_location` | maps | pinned location is not inside the map's location tree |

Additional hard rule owned by a module: `branches.override_start_changed` (an override's start
differs from its root's; catches bad imports).

**Module docs (`docs/modules/*.md`) are authoritative for module rules.** This catalog is the
initial overview and must be updated when module docs add rules. New rules are added by the issue
that implements the related feature. Every rule ships with incremental and scan tests, including
precision-aware cases.
