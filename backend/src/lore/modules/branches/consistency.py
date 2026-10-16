"""The branches module's consistency rules (``docs/modules/branches.md``).

- ``branches.override_start_changed`` (hard): an override row (``time-model.md`` §4.4) whose
  start differs from its root's. The API never writes one (overrides copy their root's start);
  this catches imports and older data.
"""

from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.consistency.existence import chunks
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.facts.models import EntityFact
from lore.core.links.models import Link
from lore.core.registry.types import RuleDef, Trigger
from lore.core.time.models import Event

RULE = "branches.override_start_changed"


def _changed(t: Any, root_t: Any) -> Any:
    return or_(t != root_t, (t.is_(None)) != (root_t.is_(None)))


def _findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    tables: list[tuple[str, Any, Any, str]] = [
        ("event", Event, "start_t", "entity_id"),
        ("fact", EntityFact, "valid_from_t", "entity_id"),
        ("link", Link, "valid_from_t", "source_id"),
    ]
    for record_type, model, start, owner in tables:
        root = aliased(model)
        row_owner = getattr(model, owner)
        statement = (
            select(model.id, row_owner, model.timeline_id, Entity.name)
            .join(root, root.id == model.overrides_id)
            .join(Entity, Entity.id == row_owner)
            .where(
                model.overrides_id.is_not(None),
                # Nearly every entity meets it: as an index it would walk them all (#144).
                unindexed(Entity.deleted_at).is_(None),
                _changed(getattr(model, start), getattr(root, start)),
            )
        )
        if hasattr(model, "deleted_at"):
            statement = statement.where(unindexed(model.deleted_at).is_(None))
        batches: Iterable[list[str] | None] = [None] if subjects is None else chunks(subjects)
        for batch in batches:
            query = statement if batch is None else statement.where(row_owner.in_(batch))
            for row_id, entity_id, timeline_id, name in ctx.session.execute(query):
                yield FindingDraft(
                    RULE,
                    (str(entity_id),),
                    f"A branch override of “{name}” doesn't start where the record does.",
                    discriminator=f"{record_type}/{row_id}",
                    timeline_id=timeline_id,
                )


CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    RuleDef(
        id=RULE,
        owner="branches",
        title="Override starts elsewhere",
        description="A branch override must start where the record it overrides does (the "
        "shared past can't change). Revert the override and override the record again.",
        category="structural",
        default_severity="error",
        configurable=False,
        triggers=(Trigger("record", "*"),),
        check=_findings,
        scan=lambda ctx: _findings(ctx, None),
    ),
)
