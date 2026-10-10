"""The consistency engine (``consistency.md`` §2-§3, D8).

Rules are ``RuleDef``s from core (``lore.core.consistency.rules``) and the enabled modules. Each
has a per-vault severity (``vault_meta.settings.consistency``; hard rules are always ``error``).
Rules set to ``off``, and those of disabled modules, are not evaluated.

- **Incremental.** Vault sessions carry the engine (``checker``, installed by ``OpenVault``):
  API requests, the CLI and scripts alike. Each time a session is about to write a changeset (at
  commit, or an undo's ``write_now``), the changed rows are mapped to subject entities through
  the rules' triggers (``record`` = an entity of a kind, or any kind with ``*``, whose row or
  records changed, propagation included; ``link_type`` = the ends of changed links of a type,
  which is all a changed link fires; ``field`` = entities whose field changed). ``check``
  returns every finding of the rule that involves one of the subjects; findings are upserted by
  fingerprint, and the rule's findings about those subjects that weren't produced again are
  deleted (decided with #55: a fixed finding is deleted). Findings about purged entities are
  deleted.
- **Blocking.** A new **definite** finding of a rule whose severity is ``error`` aborts the write
  with ``422 consistency_error`` unless it is suppressed: already (``consistency_suppressions``)
  or by the request's ``suppress: [{fingerprint, note}]`` (recorded in the same changeset). Hard
  rules can't be suppressed, but a calendar proposal's explicitly accepted records don't block
  them (``accept``, decided with #55). Requested suppressions of other findings of the write (or
  of open findings) are recorded too; unknown fingerprints are ``422`` on ``suppress``.
- **Full scan** (``scan``): every evaluated rule's ``scan`` replaces its findings.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import bindparam, delete, insert, select, update
from sqlalchemy.orm import Session

from lore.core.consistency.compare import DEFINITE, Certainty, Point
from lore.core.consistency.models import Finding, FindingEntity, Suppression
from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity
from lore.core.errors import ErrorItem, InvalidInputError
from lore.core.history import recorder
from lore.core.registry.types import RuleDef
from lore.core.time.dependencies import SlotNode
from lore.core.time.resolve import Resolver
from lore.core.vaults.meta import get_meta, set_meta

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

type Severity = Literal["off", "warning", "error"]
SEVERITIES: tuple[Severity, ...] = ("off", "warning", "error")
_REQUEST = "lore_consistency_request"
_BATCH = 5000
ANY = "*"


class ConsistencyError(InvalidInputError):
    """An error-severity rule blocks the write (``consistency.md`` §3)."""

    code = "consistency_error"
    title = "Consistency rule violated"


@dataclass(frozen=True)
class FindingDraft:
    """A finding a rule produces: its subjects (entity ids, in a meaningful order), a message,
    its certainty, a discriminator for several findings about the same subjects, the timeline
    when it is timeline-specific and free ``data``."""

    rule_id: str
    subjects: tuple[str, ...]
    message: str
    certainty: Certainty = DEFINITE
    discriminator: str = ""
    timeline_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """``sha256(rule_id + sorted subject ids + discriminator)`` (§1)."""
        text = "\0".join([self.rule_id, *sorted(set(self.subjects)), self.discriminator])
        return hashlib.sha256(text.encode()).hexdigest()


class RuleContext:
    """What rules read with (§2): the session, resolvers per dimension (stored moments with the
    extents of their specs) and the registry. Rules never write."""

    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        self.registry = context.registry
        self._resolvers: dict[str, Resolver | None] = {}
        self._points: dict[tuple[str, str, str, str], Point | None] = {}
        self._tables: set[str] | None = None

    def has_table(self, name: str) -> bool:
        """Whether the vault has a table (a module's may be missing until it is migrated)."""
        if self._tables is None:
            from sqlalchemy import inspect  # noqa: PLC0415

            self._tables = set(inspect(self.session.connection()).get_table_names())
        return name in self._tables

    def resolver(self, dimension_id: str) -> Resolver | None:
        if dimension_id not in self._resolvers:
            try:
                self._resolvers[dimension_id] = Resolver(self.context, dimension_id)
            except Exception:
                self._resolvers[dimension_id] = None
        return self._resolvers[dimension_id]

    def preload(
        self, dimension_id: str, record_type: str, slots: Iterable[tuple[str, str]]
    ) -> None:
        """Load the stored slots ``(record id, slot)`` a rule is about to ask ``point`` for, in
        sets: a rule over thousands of records must not load them one by one (#235)."""
        resolver = self.resolver(dimension_id)
        if resolver is not None:
            resolver.preload(SlotNode(record_type, record_id, slot) for record_id, slot in slots)

    def point(self, dimension_id: str, record_type: str, record_id: str, slot: str) -> Point | None:
        """A stored slot as a point (moment, extent, circa); ``None`` without a moment. Each
        slot is resolved once per context (rules are readers: nothing changes under them)."""
        key = (dimension_id, record_type, record_id, slot)
        if key not in self._points:
            resolver = self.resolver(dimension_id)
            self._points[key] = (
                None if resolver is None else Point.of(resolver.slot(record_type, record_id, slot))
            )
        return self._points[key]


# --- severities -----------------------------------------------------------------------------------


def stored_severities(session: Session) -> dict[str, str]:
    settings = get_meta(session, "settings")
    found = settings.get("consistency") if isinstance(settings, dict) else None
    return {k: v for k, v in (found or {}).items() if v in SEVERITIES}


def effective_severity(rule: RuleDef, stored: Mapping[str, str]) -> Severity:
    if not rule.configurable:
        return "error"
    value = stored.get(rule.id, rule.default_severity)
    return value if value in SEVERITIES else rule.default_severity


def store_severity(session: Session, rule_id: str, severity: Severity | None) -> None:
    """Store a rule's severity (``None``: back to its default). Settings aren't recorded in
    history."""
    settings = get_meta(session, "settings")
    settings = dict(settings) if isinstance(settings, dict) else {}
    severities = dict(settings.get("consistency") or {})
    if severity is None:
        severities.pop(rule_id, None)
    else:
        severities[rule_id] = severity
    settings["consistency"] = severities
    set_meta(session, "settings", settings)


def enabled_rules(context: VaultContext) -> list[RuleDef]:
    """The rules of core and the enabled modules."""
    from lore.core.modules.service import enabled_modules  # noqa: PLC0415 (import cycle)

    return context.registry.rules_for(enabled_modules(context.session, context.registry))


def evaluated_rules(context: VaultContext) -> list[RuleDef]:
    """The enabled rules that aren't ``off``."""
    stored = stored_severities(context.session)
    return [r for r in enabled_rules(context) if effective_severity(r, stored) != "off"]


# --- storage --------------------------------------------------------------------------------------


# Bulk writes go to the tables: the findings are derived data (not recorded in history).
_FINDINGS: Any = Finding.__table__
_SUBJECTS: Any = FindingEntity.__table__

type _Stored = tuple[str, str, str, str | None, Any]  # id, certainty, message, timeline, data


def _chunks(values: Iterable[str]) -> Iterable[list[str]]:
    wanted = sorted(set(values))
    for start in range(0, len(wanted), _BATCH):
        yield wanted[start : start + _BATCH]


def _stored(statement: Any, session: Session) -> dict[str, _Stored]:
    return {row[0]: tuple(row[1:]) for row in session.execute(statement)}


def _existing(session: Session, rule_id: str, subjects: Iterable[str] | None) -> dict[str, _Stored]:
    """The rule's findings (about any of ``subjects``; all without), by fingerprint."""
    statement = select(
        Finding.fingerprint, Finding.id, Finding.certainty, Finding.message, Finding.timeline_id,
        Finding.data,
    ).where(Finding.rule_id == rule_id)  # fmt: skip
    if subjects is None:
        return _stored(statement, session)
    found: dict[str, _Stored] = {}
    for batch in _chunks(subjects):
        ids = select(FindingEntity.finding_id).where(FindingEntity.entity_id.in_(batch))
        found.update(_stored(statement.where(Finding.id.in_(ids)), session))
    return found


def store_findings(
    session: Session, rule_id: str, drafts: Iterable[FindingDraft], scope: Iterable[str] | None
) -> list[FindingDraft]:
    """Upsert the rule's findings by fingerprint and delete those about ``scope`` (every one of
    the rule's without) that weren't produced. Returns the drafts that are new. Everything is
    read and written in sets: a scan or a calendar edit stores tens of thousands (#235)."""
    produced: dict[str, FindingDraft] = {}
    for draft in drafts:
        produced.setdefault(draft.fingerprint, draft)
    session.flush()
    existing = _existing(session, rule_id, scope)
    gone = [found[0] for fingerprint, found in existing.items() if fingerprint not in produced]
    for batch in _chunks(gone):
        session.execute(delete(Finding).where(Finding.id.in_(batch)))
    known = dict(existing)
    for batch in _chunks(set(produced) - set(existing)):  # found before, about other subjects
        known.update(
            _stored(
                select(
                    Finding.fingerprint, Finding.id, Finding.certainty, Finding.message,
                    Finding.timeline_id, Finding.data,
                ).where(Finding.fingerprint.in_(batch)),
                session,
            )
        )  # fmt: skip
    now = utc_now()
    new: list[FindingDraft] = []
    inserted: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    subjects: dict[str, list[str]] = {}  # finding id -> its subjects, in order
    for fingerprint, draft in produced.items():
        values = (draft.certainty, draft.message, draft.timeline_id, dict(draft.data))
        found = known.get(fingerprint)
        if found is None:
            finding_id = new_id()
            row = dict(zip(("certainty", "message", "timeline_id", "data"), values, strict=True))
            inserted.append(
                {"id": finding_id, "fingerprint": fingerprint, "rule_id": rule_id,
                 "created_at": now, "updated_at": now, **row}
            )  # fmt: skip
            new.append(draft)
        else:
            finding_id = found[0]
            if found[1:] != values:
                row = dict(zip(("b_certainty", "b_message", "b_timeline", "b_data"), values,
                               strict=True))  # fmt: skip
                changed.append({"b_id": finding_id, "b_updated_at": now, **row})
        subjects[finding_id] = list(dict.fromkeys(draft.subjects))
    for start in range(0, len(inserted), _BATCH):
        session.execute(insert(_FINDINGS), inserted[start : start + _BATCH])
    if changed:
        session.execute(
            update(_FINDINGS)
            .where(_FINDINGS.c.id == bindparam("b_id"))
            .values(
                certainty=bindparam("b_certainty"),
                message=bindparam("b_message"),
                timeline_id=bindparam("b_timeline"),
                data=bindparam("b_data"),
                updated_at=bindparam("b_updated_at"),
            ),
            changed,
        )
    _store_subjects(session, subjects, {row["id"] for row in inserted})
    if gone or inserted or changed:
        for loaded in list(session.identity_map.values()):
            if isinstance(loaded, Finding | FindingEntity):
                session.expire(loaded)
    return new


def _store_subjects(session: Session, subjects: Mapping[str, list[str]], new: set[str]) -> None:
    """Store the subjects of findings (by finding id), rewriting those that changed."""
    current: dict[str, list[str]] = {}
    for batch in _chunks(set(subjects) - new):
        rows = session.execute(
            select(FindingEntity.finding_id, FindingEntity.entity_id)
            .where(FindingEntity.finding_id.in_(batch))
            .order_by(FindingEntity.finding_id, FindingEntity.position)
        )
        for finding_id, entity_id in rows:
            current.setdefault(finding_id, []).append(entity_id)
    rewritten = [i for i, wanted in subjects.items() if i not in new and current.get(i) != wanted]
    for batch in _chunks(rewritten):
        session.execute(delete(FindingEntity).where(FindingEntity.finding_id.in_(batch)))
    rows_to_add = [
        {"finding_id": finding_id, "entity_id": entity_id, "position": position}
        for finding_id in (*sorted(new), *rewritten)
        for position, entity_id in enumerate(subjects[finding_id])
    ]
    for start in range(0, len(rows_to_add), _BATCH):
        session.execute(insert(_SUBJECTS), rows_to_add[start : start + _BATCH])


def delete_findings_of(session: Session, entity_ids: Iterable[str]) -> None:
    """Every finding about entities that are gone (purged)."""
    wanted = sorted(set(entity_ids))
    for start in range(0, len(wanted), _BATCH):
        ids = select(FindingEntity.finding_id).where(
            FindingEntity.entity_id.in_(wanted[start : start + _BATCH])
        )
        session.execute(delete(Finding).where(Finding.id.in_(ids)))


def delete_rule_findings(session: Session, rule_id: str) -> None:
    session.execute(delete(Finding).where(Finding.rule_id == rule_id))


# --- triggers -------------------------------------------------------------------------------------


@dataclass
class Hits:
    """What a set of changes touched: entities by kind, link ends by link type, entities by
    changed field key, and purged entities."""

    kinds: dict[str, str] = field(default_factory=dict)  # entity id -> kind
    link_types: dict[str, set[str]] = field(default_factory=dict)
    fields: dict[str, set[str]] = field(default_factory=dict)
    purged: set[str] = field(default_factory=set)

    def subjects(self, rule: RuleDef) -> set[str]:
        found: set[str] = set()
        for trigger in rule.triggers:
            if trigger.kind == "record":
                found.update(i for i, kind in self.kinds.items() if trigger.key in (ANY, kind))
            elif trigger.kind == "link_type":
                for link_type, ends in self.link_types.items():
                    if trigger.key in (ANY, link_type):
                        found.update(ends)
            else:
                found.update(self.fields.get(trigger.key, ()))
        return found


def hits_of(session: Session, changes: Sequence[recorder.RecordedChange]) -> Hits:
    hits = Hits()
    touched: set[str] = set()
    for change in changes:
        rows = [row for row in (change.before, change.after) if row is not None]
        if change.table != "links":  # a link changes neither of its ends' records
            touched.update(change.owners)
        if change.table == "entities":
            row = rows[-1]
            hits.kinds[change.row_id] = str(row["kind"])
            if change.after is None:
                hits.purged.add(change.row_id)
            elif change.before is not None:
                for key in _changed_fields(change.before, change.after):
                    hits.fields.setdefault(key, set()).add(change.row_id)
        elif change.table == "links":
            for row in rows:
                ends = {str(row[k]) for k in ("source_id", "target_id") if row.get(k)}
                hits.link_types.setdefault(str(row["link_type"]), set()).update(ends)
    missing = sorted(touched - set(hits.kinds))
    for start in range(0, len(missing), _BATCH):
        kinds: dict[str, str] = dict(
            session.execute(
                select(Entity.id, Entity.kind).where(Entity.id.in_(missing[start : start + _BATCH]))
            ).all()
        )
        hits.kinds.update(kinds)
    return hits


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> set[str]:
    import json  # noqa: PLC0415

    def parsed(row: Mapping[str, Any]) -> dict[str, Any]:
        value = row.get("fields")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return {}
        return value if isinstance(value, dict) else {}

    old, new = parsed(before), parsed(after)
    return {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}


# --- requests -------------------------------------------------------------------------------------


@dataclass
class Request:
    """What a session's writes say about consistency: suppressions (by fingerprint or rule),
    records whose hard-rule findings don't block (``accept``), and whether to block at all."""

    suppress: dict[str, str] = field(default_factory=dict)  # fingerprint -> note
    suppress_rules: dict[str, str] = field(default_factory=dict)  # rule id -> note
    accepted: set[str] = field(default_factory=set)
    blocking: bool = True


def _request(session: Session) -> Request:
    request: Request | None = session.info.get(_REQUEST)
    if request is None:
        request = session.info[_REQUEST] = Request()
    return request


def checker(vault: Any, registry: Any) -> recorder.BeforeWrite:
    """The vault sessions' consistency check (``OpenVault``): every changeset any session writes
    is checked (API requests, the CLI, scripts), before history records it."""
    from lore.core.modules.spec import VaultContext  # noqa: PLC0415 (import cycle)

    def check(session: Session, changes: list[recorder.RecordedChange]) -> None:
        if changes:
            evaluate(VaultContext(vault, session, registry), changes)

    return check


def request_suppress(session: Session, items: Iterable[tuple[str | None, str | None, str]]) -> None:
    """A write's ``suppress`` member: findings it declares intentional, as ``(fingerprint,
    rule id, note)`` with one of the first two."""
    request = _request(session)
    for fingerprint, rule_id, note in items:
        if fingerprint is not None:
            request.suppress[fingerprint] = note
        elif rule_id is not None:
            request.suppress_rules[rule_id] = note


def accept(session: Session, entity_ids: Iterable[str]) -> None:
    """Hard-rule findings about these entities don't block this write (records a calendar
    proposal's apply accepted explicitly, ``time-model.md`` §7.4)."""
    _request(session).accepted.update(entity_ids)


def record_only(session: Session) -> None:
    """This session's writes update findings but never block (repairs: ``lore vault reindex``,
    scans after migrations)."""
    _request(session).blocking = False


def evaluate(context: VaultContext, changes: Sequence[recorder.RecordedChange]) -> None:
    """Incremental checks of a write (§3.1) and blocking (§3.2)."""
    session = context.session
    request = _request(session)
    hits = hits_of(session, changes)
    if hits.purged:
        delete_findings_of(session, hits.purged)
    rules = evaluated_rules(context)
    stored = stored_severities(session)
    rule_context = RuleContext(context)
    blocking: list[tuple[RuleDef, FindingDraft]] = []
    produced: dict[str, tuple[RuleDef, FindingDraft]] = {}
    for rule in rules:
        subjects = hits.subjects(rule) - hits.purged
        if not subjects:
            continue
        drafts = list(rule.check(rule_context, frozenset(subjects)))
        produced.update({d.fingerprint: (rule, d) for d in drafts})
        new = store_findings(session, rule.id, drafts, subjects)
        if effective_severity(rule, stored) == "error":
            blocking += [(rule, d) for d in new if d.certainty == DEFINITE]
    if request.blocking:
        _resolve_blocking(context, request, blocking, produced)


def _resolve_blocking(
    context: VaultContext,
    request: Request,
    blocking: list[tuple[RuleDef, FindingDraft]],
    produced: Mapping[str, tuple[RuleDef, FindingDraft]],
) -> None:
    session = context.session
    unknown: list[ErrorItem] = []
    for rule_id, note in sorted(request.suppress_rules.items()):
        matched = [d for r, d in blocking if r.id == rule_id and r.configurable]
        if not matched:
            unknown.append(
                ErrorItem(
                    path="suppress",
                    code="not_found",
                    message=f"The write has no blocking finding of {rule_id}.",
                )
            )
        for draft in matched:
            request.suppress.setdefault(draft.fingerprint, note)
    if unknown:
        raise InvalidInputError("Some suppressed findings don't exist.", errors=unknown)
    fingerprints = sorted({d.fingerprint for _r, d in blocking} | set(request.suppress))
    suppressed = set(
        session.scalars(
            select(Suppression.fingerprint).where(Suppression.fingerprint.in_(fingerprints))
        )
    )
    _record_suppressions(context, request, produced, suppressed)
    suppressed |= {fp for fp in request.suppress if fp in produced and produced[fp][0].configurable}
    left = [
        (rule, draft)
        for rule, draft in blocking
        if draft.fingerprint not in suppressed
        and (rule.configurable or not set(draft.subjects) & request.accepted)
    ]
    if left:
        raise ConsistencyError(
            f"{len(left)} finding{'s' if len(left) != 1 else ''} of error-severity rules: "
            + left[0][1].message
            + (
                " Resend with `suppress` to save anyway."
                if any(r.configurable for r, _ in left)
                else ""
            ),
            errors=[
                ErrorItem(path="suppress", code=rule.id, message=draft.message)
                for rule, draft in left
            ],
            context={"findings": [_problem(rule, draft) for rule, draft in left]},
        )


def _problem(rule: RuleDef, draft: FindingDraft) -> dict[str, Any]:
    return {
        "fingerprint": draft.fingerprint,
        "rule_id": rule.id,
        "message": draft.message,
        "certainty": draft.certainty,
        "subjects": list(draft.subjects),
        "suppressible": rule.configurable,
    }


def _record_suppressions(
    context: VaultContext,
    request: Request,
    produced: Mapping[str, tuple[RuleDef, FindingDraft]],
    suppressed: set[str],
) -> None:
    """Store the request's suppressions: findings of this write or open findings, of
    configurable rules."""
    session = context.session
    wanted = {fp: note for fp, note in request.suppress.items() if fp not in suppressed}
    if not wanted:
        return
    rules = {r.id: r for r in enabled_rules(context)}
    open_findings = dict(
        session.execute(
            select(Finding.fingerprint, Finding.rule_id).where(
                Finding.fingerprint.in_(sorted(wanted))
            )
        ).all()
    )
    errors: list[ErrorItem] = []
    for index, (fingerprint, note) in enumerate(sorted(wanted.items())):
        rule_id = (
            produced[fingerprint][0].id
            if fingerprint in produced
            else open_findings.get(fingerprint)
        )
        rule = rules.get(rule_id or "")
        if rule is None:
            errors.append(
                ErrorItem(
                    path=f"suppress.{index}.fingerprint",
                    code="not_found",
                    message="No such finding.",
                )
            )
            continue
        if not rule.configurable:
            continue  # hard rules can't be suppressed (they still block)
        session.add(Suppression(fingerprint=fingerprint, rule_id=rule.id, note=note))
    if errors:
        raise InvalidInputError("Some suppressed findings don't exist.", errors=errors)
    session.flush()


# --- scans ----------------------------------------------------------------------------------------


def scan(context: VaultContext, rules: Iterable[RuleDef] | None = None) -> dict[str, int]:
    """Full scan (§3.3): each rule's findings are replaced by what its ``scan`` finds. Returns
    the number of findings per rule."""
    rule_context = RuleContext(context)
    counts: dict[str, int] = {}
    for rule in evaluated_rules(context) if rules is None else rules:
        drafts = list(rule.scan(rule_context))
        store_findings(context.session, rule.id, drafts, None)
        counts[rule.id] = len({d.fingerprint for d in drafts})
    return counts


__all__ = [
    "SEVERITIES",
    "ConsistencyError",
    "FindingDraft",
    "Hits",
    "Request",
    "RuleContext",
    "accept",
    "checker",
    "effective_severity",
    "enabled_rules",
    "evaluate",
    "evaluated_rules",
    "record_only",
    "request_suppress",
    "scan",
    "store_findings",
    "store_severity",
    "stored_severities",
]
