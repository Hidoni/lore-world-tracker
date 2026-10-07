"""The consistency API's operations (``api.md`` §2): findings, rules and severities,
suppressions, scans. Author-only (readers get ``404``, ``visibility-and-sharing.md`` §2).

- **Findings** listed are those of evaluated rules (enabled modules, not ``off``): ``status``
  ``open`` (default; not suppressed), ``suppressed`` or ``all``. Possible findings show as
  ``info``. Order (decided with #55): error, warning, info, then the most recently found first.
- **Severities** are stored in ``vault_meta.settings.consistency`` (not recorded in history).
  Hard rules can't change (``422``). Setting a rule ``off`` deletes its findings; leaving ``off``
  scans it.
- **Suppressions** of open findings of configurable rules are recorded in history; deleting one
  that doesn't exist is ``404``.
"""

import base64
import binascii
import json
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, case, func, or_, select

from lore.core.consistency import engine
from lore.core.consistency.models import Finding, FindingEntity, Suppression
from lore.core.consistency.schemas import (
    FindingOut,
    FindingPage,
    FindingSubject,
    RuleInfo,
    RuleList,
    ScanResult,
    SuppressionOut,
)
from lore.core.entities.models import Entity
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.history import recorder
from lore.core.registry.types import RuleDef

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext

_RANK = {"error": 0, "warning": 1, "info": 2}
STATUSES = ("open", "suppressed", "all")


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[ErrorItem(path=path, code="invalid_value",
                                                        message=message)])  # fmt: skip


class ConsistencyService:
    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session

    def _rules(self) -> tuple[dict[str, RuleDef], dict[str, str]]:
        stored = engine.stored_severities(self.session)
        rules = {r.id: r for r in engine.enabled_rules(self.context)}
        return rules, {i: engine.effective_severity(r, stored) for i, r in rules.items()}

    # --- findings -------------------------------------------------------------------------------

    def findings(
        self,
        *,
        status: str = "open",
        severities: Iterable[str] = (),
        certainty: str | None = None,
        rules: Iterable[str] = (),
        owner: str | None = None,
        entity: str | None = None,
        timeline: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> FindingPage:
        defs, effective = self._rules()
        shown = {i for i, s in effective.items() if s != "off"}
        if owner is not None:
            shown = {i for i in shown if defs[i].owner == owner}
        if rules:
            shown &= set(rules)
        error_rules = sorted(i for i in shown if effective[i] == "error")
        rank = case(
            (Finding.certainty == "possible", 2),
            (Finding.rule_id.in_(error_rules), 0),
            else_=1,
        )
        suppressed = select(Suppression.fingerprint).where(
            Suppression.fingerprint == Finding.fingerprint
        )
        statement = select(Finding, rank.label("rank")).where(Finding.rule_id.in_(sorted(shown)))
        if status == "open":
            statement = statement.where(~suppressed.exists())
        elif status == "suppressed":
            statement = statement.where(suppressed.exists())
        wanted = sorted({_RANK[s] for s in severities})
        if wanted:
            statement = statement.where(rank.in_(wanted))
        if certainty is not None:
            statement = statement.where(Finding.certainty == certainty)
        if entity is not None:
            statement = statement.where(
                Finding.id.in_(
                    select(FindingEntity.finding_id).where(FindingEntity.entity_id == entity)
                )
            )
        if timeline is not None:
            statement = statement.where(Finding.timeline_id == timeline)
        if cursor is not None:
            after_rank, after_created, after_id = _decode(cursor)
            statement = statement.where(
                or_(
                    rank > after_rank,
                    and_(rank == after_rank, Finding.created_at < after_created),
                    and_(
                        rank == after_rank,
                        Finding.created_at == after_created,
                        Finding.id < after_id,
                    ),
                )
            )
        statement = statement.order_by(rank, Finding.created_at.desc(), Finding.id.desc())
        rows = self.session.execute(statement.limit(limit + 1)).all()
        page = rows[:limit]
        items = self._out([(finding, int(r)) for finding, r in page], defs)
        next_cursor = None
        if len(rows) > limit:
            last, last_rank = page[-1]
            next_cursor = _encode(int(last_rank), last.created_at, last.id)
        return FindingPage(items=items, next_cursor=next_cursor)

    def _out(self, rows: list[tuple[Finding, int]], defs: dict[str, RuleDef]) -> list[FindingOut]:
        ids = [finding.id for finding, _rank in rows]
        subjects: dict[str, list[FindingSubject]] = {i: [] for i in ids}
        if ids:
            found = self.session.execute(
                select(FindingEntity.finding_id, FindingEntity.entity_id, Entity.name, Entity.kind)
                .outerjoin(Entity, Entity.id == FindingEntity.entity_id)
                .where(FindingEntity.finding_id.in_(ids))
                .order_by(FindingEntity.finding_id, FindingEntity.position)
            )
            for finding_id, entity_id, name, kind in found:
                subjects[finding_id].append(FindingSubject(id=entity_id, name=name, kind=kind))
        fingerprints = [finding.fingerprint for finding, _rank in rows]
        suppressions = {
            s.fingerprint: s
            for s in self.session.scalars(
                select(Suppression).where(Suppression.fingerprint.in_(fingerprints))
            )
        }
        items = []
        for finding, rank in rows:
            rule = defs[finding.rule_id]
            suppression = suppressions.get(finding.fingerprint)
            items.append(
                FindingOut(
                    fingerprint=finding.fingerprint,
                    rule_id=finding.rule_id,
                    owner=rule.owner,
                    title=rule.title,
                    severity=("error", "warning", "info")[rank],
                    certainty=finding.certainty,  # type: ignore[arg-type]
                    message=finding.message,
                    subjects=subjects[finding.id],
                    timeline_id=finding.timeline_id,
                    data=finding.data,
                    suppression=None
                    if suppression is None
                    else SuppressionOut(note=suppression.note, created_at=suppression.created_at),
                    created_at=finding.created_at,
                    updated_at=finding.updated_at,
                )
            )
        return items

    # --- rules ----------------------------------------------------------------------------------

    def rules(self) -> RuleList:
        defs, effective = self._rules()
        suppressed = select(Suppression.fingerprint)
        counts: dict[str, int] = dict(
            self.session.execute(
                select(Finding.rule_id, func.count())
                .where(Finding.fingerprint.not_in(suppressed))
                .group_by(Finding.rule_id)
            ).all()
        )
        return RuleList(
            items=[
                RuleInfo(
                    id=rule.id,
                    owner=rule.owner,
                    title=rule.title,
                    description=rule.description,
                    category=rule.category,
                    default_severity=rule.default_severity,
                    severity=effective[rule.id],  # type: ignore[arg-type]
                    configurable=rule.configurable,
                    findings=counts.get(rule.id, 0) if effective[rule.id] != "off" else 0,
                )
                for rule in sorted(defs.values(), key=lambda r: (r.owner != "core", r.owner, r.id))
            ]
        )

    def set_severity(self, rule_id: str, severity: str | None) -> RuleInfo:
        defs, effective = self._rules()
        rule = defs.get(rule_id)
        if rule is None:
            raise NotFoundError(f"No rule {rule_id!r} (or its module is disabled).")
        if not rule.configurable:
            raise _invalid("severity", "Hard rules are always errors.")
        before = effective[rule_id]
        engine.store_severity(self.session, rule_id, severity)  # type: ignore[arg-type]
        after = engine.effective_severity(rule, engine.stored_severities(self.session))
        if after == "off":
            engine.delete_rule_findings(self.session, rule_id)
        elif before == "off":
            engine.scan(self.context, [rule])
        return next(r for r in self.rules().items if r.id == rule_id)

    # --- suppressions ---------------------------------------------------------------------------

    def suppress(self, fingerprint: str, note: str) -> FindingOut:
        defs, effective = self._rules()
        finding = self.session.scalar(select(Finding).where(Finding.fingerprint == fingerprint))
        if finding is None or effective.get(finding.rule_id, "off") == "off":
            raise NotFoundError("No such finding.")
        rule = defs[finding.rule_id]
        if not rule.configurable:
            raise _invalid("fingerprint", "Findings of hard rules can't be suppressed.")
        existing = self.session.get(Suppression, fingerprint)
        if existing is not None:
            raise ConflictError("The finding is already suppressed.")
        recorder.describe(self.session, f"Suppressed a finding of {rule.title}")
        self.session.add(Suppression(fingerprint=fingerprint, rule_id=rule.id, note=note))
        self.session.flush()
        rank = 2 if finding.certainty == "possible" else _RANK[effective[rule.id]]
        return self._out([(finding, rank)], defs)[0]

    def unsuppress(self, fingerprint: str) -> None:
        existing = self.session.get(Suppression, fingerprint)
        if existing is None:
            raise NotFoundError("No such suppression.")
        recorder.describe(self.session, "Took back a suppression")
        self.session.delete(existing)
        self.session.flush()

    # --- scans ----------------------------------------------------------------------------------

    def scan(self) -> ScanResult:
        counts = engine.scan(self.context)
        return ScanResult(rules=len(counts), findings=sum(counts.values()))


def _encode(rank: int, created_at: datetime, finding_id: str) -> str:
    raw = json.dumps([rank, created_at.isoformat(), finding_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[int, datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        rank, created, finding_id = json.loads(raw)
        return int(rank), datetime.fromisoformat(created), str(finding_id)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise _invalid("cursor", "The cursor is invalid.") from exc


__all__ = ["STATUSES", "ConsistencyService"]
