"""The languages module's consistency rules (``docs/modules/languages.md``).

- ``languages.speaker_outside_existence``: a ``speaks`` link is valid while the language doesn't
  exist.
- ``languages.entry_outside_existence``: a lexicon entry is attested while its language doesn't
  exist.
"""

from collections.abc import Iterator

from sqlalchemy import select

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.consistency.existence import chunks, span, with_existence
from lore.core.consistency.narrative import Within, links_within, narrative_rule
from lore.core.db import unindexed
from lore.core.entities.models import Entity
from lore.core.registry.types import RuleDef, Trigger
from lore.modules.languages.kinds import LANGUAGE
from lore.modules.languages.lexicon import RECORD
from lore.modules.languages.links import SPEAKS
from lore.modules.languages.models import LexiconEntry


def _entries(ctx: RuleContext, subjects: frozenset[str] | None) -> Iterator[FindingDraft]:
    if not ctx.has_table(LexiconEntry.__tablename__):
        return
    statement = (
        select(
            LexiconEntry.id,
            LexiconEntry.language_id,
            LexiconEntry.timeline_id,
            LexiconEntry.valid_from_t,
            LexiconEntry.valid_to_t,
            LexiconEntry.headword,
            Entity.name,
        )
        .join(Entity, Entity.id == LexiconEntry.language_id)
        .where(
            LexiconEntry.timeline_id.is_not(None),
            unindexed(LexiconEntry.deleted_at).is_(None),
            unindexed(Entity.deleted_at).is_(None),
        )
    )
    scope = with_existence(ctx) if subjects is None else subjects  # languages with existence
    checker = Within(ctx)
    for batch in chunks(scope):
        for row in ctx.session.execute(statement.where(LexiconEntry.language_id.in_(batch))):
            entry_id, language_id, timeline_id, from_t, to_t, *_names = row
            checker.add(language_id, timeline_id, span(RECORD, entry_id, from_t, to_t), row)
    for row, certainty in checker.findings():
        entry_id, language_id, timeline_id, _from, _to, headword, name = row
        yield FindingDraft(
            "languages.entry_outside_existence",
            (language_id,),
            f"“{headword}” is attested in “{name}” while the language doesn't exist.",
            certainty=certainty,
            discriminator=entry_id,
            timeline_id=timeline_id,
        )


CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    narrative_rule(
        "languages.speaker_outside_existence",
        "languages",
        "Speaker outside the language's existence",
        "A speaker link is valid while the language doesn't exist.",
        links_within(
            "languages.speaker_outside_existence",
            (SPEAKS,),
            ("target",),
            lambda speaker, language, _side: (
                f"“{speaker}” speaks “{language}” while it doesn't exist."
            ),
        ),
        triggers=(Trigger("record", LANGUAGE), Trigger("link_type", SPEAKS)),
    ),
    narrative_rule(
        "languages.entry_outside_existence",
        "languages",
        "Entry outside the language's existence",
        "A lexicon entry's attestation period lies outside its language's existence.",
        _entries,
        triggers=(Trigger("record", LANGUAGE),),
    ),
)

__all__ = ["CONSISTENCY_RULES"]
