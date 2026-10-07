"""Recurrence-rule proposals: reconciling materialized occurrences with a rule change
(``recurrence.md`` §8, ``time-model.md`` §7.5, R-REC-6).

``POST /events/{id}/recurrence/proposals {rule, start?, end?}`` checks the change like a PATCH
would (``422`` on ``rule…``, ``start``, ``end``) and gives every materialized occurrence that isn't
in the trash a status: ``unchanged`` (its key still starts at ``original_start_t``), ``moved``
(its key starts elsewhere) or ``orphaned`` (its key has no occurrence any more). Apply takes a
strategy per occurrence (decided with #54 where the spec is silent):

- ``keep_key`` (default when moved): it keeps its key and moves with the rule (a ``modified``
  occurrence keeps its own time).
- ``rekey``: it takes the key of ``occurrence_at(original_start_t)`` (moved) or of the first
  occurrence at or after it (orphaned); its occurrence anchors follow the new key and
  ``original_start_t`` becomes that occurrence's start. Two occurrences ending up with one key
  (also one in the trash) is ``409 rekey_conflict``.
- ``detach`` (default when orphaned): it becomes a standalone event; anchors to its occurrence are
  pinned at its current moments.
- ``trash`` (orphaned only): it goes to the trash, its occurrence anchors pinned at its current
  moments first (they can't resolve any more). One with sub-events answers ``409
  occurrence_has_sub_events``: detach it instead.

Apply is stale (``409 proposal_stale``) when the series row changed (its revision) or the
statuses computed again differ from the preview. It writes the series' new rule, start and end
and the reconciliation as one changeset. Direct edits that would orphan an occurrence are refused
(``lore.core.time.events``).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from lore.chronology.schema import (
    EndSpec,
    RelativeAnchor,
    TimePoint,
    TimePointEnd,
)
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, LoreError
from lore.core.history.recorder import describe
from lore.core.time import series
from lore.core.time.events import (
    EVENT,
    home_row,
    parse_rule_document,
    plan_times,
    write_times,
)
from lore.core.time.models import Event, Proposal
from lore.core.time.propagate import TimeWriter
from lore.core.time.proposals import ProposalStaleError, load_proposal, pinned, save_proposal
from lore.core.time.resolve import Resolver
from lore.core.time.specs import parse_end_spec

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

RECURRENCE = "recurrence"
KEEP_KEY = "keep_key"
REKEY = "rekey"
DETACH = "detach"
TRASH = "trash"


class RekeyConflictError(ConflictError):
    """Two materialized occurrences would end up with one key."""

    code = "rekey_conflict"
    title = "Rekey conflict"


@dataclass(frozen=True)
class Change:
    """The requested change: the rule (when sent; ``None`` stops the recurrence), start, end."""

    rule: series.Rule | None
    rule_document: dict[str, Any] | None
    start: TimePoint | None
    end: EndSpec | None


def parse_change(payload: Mapping[str, Any]) -> Change:
    document = payload.get("rule")
    start = payload.get("start")
    end = payload.get("end")
    return Change(
        rule=_paths(lambda: parse_rule_document(document)),
        rule_document=document,
        start=None if start is None else TimePoint.model_validate(start),
        end=None if end is None else parse_end_spec(end),
    )


_PREFIXES = (("ext.recurrence", "rule"), ("ext.start", "start"), ("ext.end", "end"))


def _paths[T](call: Callable[[], T]) -> T:
    """Run a check written for PATCH ``ext`` paths; report the proposal body's paths."""
    try:
        return call()
    except LoreError as exc:
        for error in exc.errors or []:
            for old, new in _PREFIXES:
                if error["path"] == old or error["path"].startswith(old + "."):
                    error["path"] = new + error["path"][len(old) :]
                    break
        raise


def _series(context: VaultContext, entity: Entity) -> Event:
    if entity.deleted_at is not None:
        raise ConflictError("The event is in the trash: restore it before editing it.")
    row = home_row(context.session, entity.id)
    if row is None:
        raise ConflictError("The event has no time data.")
    if row.series_entity_id is not None:
        message = "An occurrence of a recurring event can't recur."
        raise InvalidInputError(
            message, errors=[ErrorItem(path="rule", code="invalid_value", message=message)]
        )
    return row


def _statuses(
    context: VaultContext, entity: Entity, row: Event, change: Change
) -> list[series.Reconciliation]:
    assert entity.dimension_id is not None
    plan = _paths(
        lambda: plan_times(
            context, entity.dimension_id or "", row, start=change.start, end=change.end,
            rule=change.rule,
        )
    )  # fmt: skip
    return series.reconcile(
        plan.rule, plan.context, series.materialized(context.session, [entity.id])
    )


def _strategies(status: str, rekey: bool) -> tuple[list[str], str | None]:
    if status == series.MOVED:
        return [KEEP_KEY, *([REKEY] if rekey else []), DETACH], KEEP_KEY
    if status == series.ORPHANED:
        return [*([REKEY] if rekey else []), DETACH, TRASH], DETACH
    return [], None


def _items(context: VaultContext, entity: Entity, found: list[series.Reconciliation]) -> list[Any]:
    session = context.session
    holders = {
        r.occurrence_key: r.entity_id for r in series.materialized(session, [entity.id], live=False)
    }
    rows = session.execute(
        select(Entity.id, Entity.name).where(Entity.id.in_([r.row.entity_id for r in found]))
    )
    names = {entity_id: name for entity_id, name in rows}  # noqa: C416 (Row pairs)
    items = []
    for r in found:
        strategies, default = _strategies(r.status, r.rekey is not None)
        rekey_key = None if r.rekey is None else r.rekey.key
        holder = holders.get(rekey_key) if rekey_key is not None else None
        items.append(
            {
                "entity_id": r.row.entity_id,
                "name": names.get(r.row.entity_id, ""),
                "key": r.row.occurrence_key,
                "state": r.row.occurrence_state,
                "original_start_t": _text(r.row.original_start_t),
                "start_t": _text(r.row.start_t),
                "status": r.status,
                "new_start_t": _text(r.new_start),
                "rekey_key": rekey_key,
                "rekey_start_t": None if r.rekey is None else str(r.rekey.start),
                "rekey_held_by": None if holder == r.row.entity_id else holder,
                "strategies": strategies,
                "default_strategy": default,
            }
        )
    return items


def _text(t: int | None) -> str | None:
    return None if t is None else str(t)


def preview_rule_change(context: VaultContext, entity: Entity, payload: dict[str, Any]) -> Proposal:
    """``POST /events/{id}/recurrence/proposals``: the materialized occurrences' statuses under the
    change, stored for an hour."""
    row = _series(context, entity)
    change = parse_change(payload)
    items = _items(context, entity, _statuses(context, entity, row, change))
    summary = {
        status: sum(1 for i in items if i["status"] == status)
        for status in (series.UNCHANGED, series.MOVED, series.ORPHANED)
    }
    return save_proposal(
        context.session,
        kind=RECURRENCE,
        target_id=entity.id,
        payload=payload,
        impact={"items": items, "summary": summary},
        base_revision=row.revision,
    )


# --- apply ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AppliedRule:
    kept: int
    rekeyed: int
    detached: int
    trashed: int
    entity_ids: list[str]


_COMPARED = ("entity_id", "key", "status", "new_start_t", "rekey_key", "rekey_start_t")


def _strategy_error(entity_id: str, message: str, code: str = "invalid_value") -> InvalidInputError:
    return InvalidInputError(
        message, errors=[ErrorItem(path=f"strategies.{entity_id}", code=code, message=message)]
    )


def _chosen(
    items: Mapping[str, Mapping[str, Any]], strategies: Mapping[str, str]
) -> dict[str, str]:
    for entity_id, strategy in strategies.items():
        item = items.get(entity_id)
        if item is None:
            raise _strategy_error(entity_id, "The proposal has no such occurrence.",
                                  "unknown_record")  # fmt: skip
        if strategy not in item["strategies"]:
            allowed = ", ".join(item["strategies"]) or "none: it is unchanged"
            raise _strategy_error(entity_id, f"{strategy} isn't possible for this occurrence "
                                  f"({allowed}).")  # fmt: skip
    return {
        entity_id: strategies.get(entity_id, item["default_strategy"])
        for entity_id, item in items.items()
        if item["default_strategy"] is not None
    }


def _check_keys(
    context: VaultContext, entity: Entity, items: Mapping[str, Mapping[str, Any]],
    chosen: Mapping[str, str],
) -> None:  # fmt: skip
    """Every key ends up with at most one materialized occurrence (trashed ones included)."""
    holders: dict[str, list[str]] = {}
    for row in series.materialized(context.session, [entity.id], live=False):
        if row.entity_id in items:
            continue
        holders.setdefault(row.occurrence_key or "", []).append(row.entity_id)
    for entity_id, item in items.items():
        strategy = chosen.get(entity_id)
        if strategy in (DETACH, TRASH):
            continue
        key = item["rekey_key"] if strategy == REKEY else item["key"]
        holders.setdefault(key, []).append(entity_id)
    conflicts = [
        {"key": k, "entity_ids": sorted(v)} for k, v in sorted(holders.items()) if len(v) > 1
    ]
    if conflicts:
        raise RekeyConflictError(
            f"{len(conflicts)} occurrence key(s) would be held by several materialized "
            "occurrences: choose another strategy for one of them.",
            context={"conflicts": conflicts},
        )


def _occurrence_ref(spec: Any, series_id: str) -> tuple[TimePoint, RelativeAnchor] | None:
    """The time point of a spec when it is anchored to an occurrence of the series."""
    point = spec.time_point if isinstance(spec, TimePointEnd) else spec
    if isinstance(point, TimePoint) and isinstance(point.anchor, RelativeAnchor):
        ref = point.anchor.ref
        if ref.type == EVENT and ref.id == series_id and ref.occurrence is not None:
            return point, point.anchor
    return None


def _respec(
    writer: TimeWriter,
    row: Event,
    series_id: str,
    dimension_id: str,
    *,
    rekey: tuple[str, str] | None = None,
    resolver: Resolver | None = None,
) -> None:
    """Anchors of a materialized occurrence to occurrences of its series, after reconciliation:
    with ``rekey = (old key, new key)``, anchors to the old key follow the new one; otherwise
    (detach, trash) every such anchor is pinned at the slot's current moment."""
    specs = (
        ("start", row.start_spec, row.start_t),
        ("end", parse_end_spec(row.end_spec), row.end_t),
    )
    for slot, spec, t in specs:
        found = _occurrence_ref(spec, series_id)
        if found is None:
            continue
        point, anchor = found
        new: Any
        if rekey is not None:
            if anchor.ref.occurrence != rekey[0]:
                continue
            ref = anchor.ref.model_copy(update={"occurrence": rekey[1]})
            new_point = point.model_copy(update={"anchor": anchor.model_copy(update={"ref": ref})})
            new = (
                spec.model_copy(update={"time_point": new_point})
                if spec is not point
                else new_point
            )
        else:
            if t is None or resolver is None:
                continue
            new = pinned(spec, t, resolver.has_default_level)
        if slot == "start":
            row.start_spec = new
        else:
            row.end_spec = new
        writer.set_spec(EVENT, row.entity_id, slot, new, dimension_id=dimension_id)


def apply_rule_change(
    context: VaultContext, entity: Entity, proposal_id: str, strategies: Mapping[str, str]
) -> AppliedRule:
    """``POST /events/{id}/recurrence/proposals/{pid}/apply``."""
    from lore.core.entities.service import EntityService  # noqa: PLC0415 (import cycle)

    session = context.session
    proposal = load_proposal(session, RECURRENCE, entity.id, proposal_id)
    row = _series(context, entity)
    change = parse_change(proposal.payload)
    found = _statuses(context, entity, row, change)
    items = {i["entity_id"]: i for i in proposal.impact["items"]}
    fresh = _items(context, entity, found)
    if row.revision != proposal.base_revision or [[i[k] for k in _COMPARED] for i in fresh] != [
        [i[k] for k in _COMPARED] for i in proposal.impact["items"]
    ]:
        raise ProposalStaleError(
            "The series or its materialized occurrences changed since the preview: preview the "
            "change again.",
            context={"proposals": f"/events/{entity.id}/recurrence/proposals"},
        )
    chosen = _chosen(items, strategies)
    _check_keys(context, entity, items, chosen)
    assert entity.dimension_id is not None
    dimension_id = entity.dimension_id
    rows = {r.row.entity_id: r for r in found}
    resolver = Resolver(context, dimension_id, row.timeline_id)
    entities = EntityService(context)
    trash_writer = TimeWriter(context)
    trashed = [i for i, s in chosen.items() if s == TRASH]
    for entity_id in trashed:
        _respec(trash_writer, rows[entity_id].row, entity.id, dimension_id, resolver=resolver)
    trash_writer.propagate(path="strategies")
    for entity_id in sorted(trashed):
        entities.trash(entity_id)
    writer = TimeWriter(context)
    for entity_id in sorted(i for i, s in chosen.items() if s == DETACH):  # frees their keys
        occurrence_row = rows[entity_id].row
        _respec(writer, occurrence_row, entity.id, dimension_id, resolver=resolver)
        occurrence_row.series_entity_id = None
        occurrence_row.occurrence_key = None
        occurrence_row.occurrence_state = None
        occurrence_row.original_start_t = None
        occurrence_row.revision += 1
    rekeyed = sorted(i for i, s in chosen.items() if s == REKEY)
    for entity_id in rekeyed:  # keys are unique per series and timeline: free them all first
        rows[entity_id].row.occurrence_key = None
    session.flush()
    for entity_id in rekeyed:
        reconciliation = rows[entity_id]
        assert reconciliation.rekey is not None
        occurrence_row = reconciliation.row
        old_key = items[entity_id]["key"]
        occurrence_row.occurrence_key = reconciliation.rekey.key
        occurrence_row.original_start_t = reconciliation.rekey.start
        occurrence_row.revision += 1
        _respec(writer, occurrence_row, entity.id, dimension_id,
                rekey=(old_key, reconciliation.rekey.key))  # fmt: skip
    session.flush()
    entity.updated_at = utc_now()
    row.revision += 1
    write_times(
        context, dimension_id, row, start=change.start, end=change.end, rule=change.rule,
        rule_sent=True, writer=writer, reconciled=True,
    )  # fmt: skip
    session.delete(proposal)
    counts = {
        s: sum(1 for c in chosen.values() if c == s) for s in (KEEP_KEY, REKEY, DETACH, TRASH)
    }
    describe(session, f"Changed the recurrence of “{entity.name}” ({len(chosen)} occurrences "
             "reconciled)")  # fmt: skip
    session.flush()
    return AppliedRule(
        kept=counts[KEEP_KEY],
        rekeyed=counts[REKEY],
        detached=counts[DETACH],
        trashed=counts[TRASH],
        entity_ids=sorted({entity.id, *items}),
    )
