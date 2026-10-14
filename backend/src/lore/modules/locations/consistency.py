"""The locations module's consistency rules (``docs/modules/locations.md``).

- ``locations.event_at_nonexistent_location``: an event's site doesn't exist at the event's
  start.
- ``locations.child_outside_parent_existence``: a location exists while the location it lies in
  (its parent) doesn't.
"""

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import aliased

from lore.core.consistency.engine import RuleContext
from lore.core.consistency.existence import chunks
from lore.core.consistency.narrative import events_within, narrative_rule, periods_within
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.registry.types import RuleDef, Trigger
from lore.modules.locations.kinds import LOCATION
from lore.modules.locations.links import EVENT_SITE


def _nested(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[tuple[str, str]]:
    """``(location, parent location)`` pairs (involving a subject)."""
    parent = aliased(Entity)
    statement = (
        select(Entity.id, Entity.parent_id)
        .join(parent, parent.id == Entity.parent_id)
        .where(unindexed(Entity.kind) == LOCATION, unindexed(parent.kind) == LOCATION)
    )
    statements = (
        [statement]
        if subjects is None
        else [statement.where(column.in_(batch))
              for batch in chunks(subjects) for column in (Entity.id, Entity.parent_id)]
    )  # fmt: skip
    for selected in statements:
        for child_id, parent_id in ctx.session.execute(selected):
            if parent_id is not None:
                yield child_id, parent_id


CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    narrative_rule(
        "locations.event_at_nonexistent_location",
        "locations",
        "Event at a location that doesn't exist",
        "An event's site doesn't exist at the event's start.",
        events_within(
            "locations.event_at_nonexistent_location",
            EVENT_SITE,
            lambda event, site: f"“{event}” takes place at “{site}” while it doesn't exist.",
            instant=True,
        ),
        triggers=(Trigger("record", "*"), Trigger("link_type", EVENT_SITE)),
    ),
    narrative_rule(
        "locations.child_outside_parent_existence",
        "locations",
        "Location outside its parent's existence",
        "A location exists while the location it lies in doesn't.",
        periods_within(
            "locations.child_outside_parent_existence",
            _nested,
            lambda child, parent: f"“{child}” exists while “{parent}”, which it lies in, doesn't.",
        ),
        triggers=(Trigger("record", LOCATION),),
    ),
)

__all__ = ["CONSISTENCY_RULES"]
