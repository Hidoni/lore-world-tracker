"""The languages module's spec."""

from typing import Any

from lore.core.entities.extensions import KindExtension
from lore.core.entities.models import Entity
from lore.core.errors import InvalidInputError
from lore.core.history.service import REVERT_HOOKS
from lore.core.history.tables import HistoryTable, columns_owner
from lore.core.modules import ModuleSpec, VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.languages.kinds import LANGUAGE, LANGUAGE_KIND, WRITING_SYSTEM_KIND
from lore.modules.languages.lexicon import (
    ALPHABET_FIELD,
    LEXICON_SEARCH,
    LEXICON_SLOTS,
    LEXICON_VISIBILITY,
    Lexicon,
    purge_entries,
    reindex_after_revert,
)
from lore.modules.languages.links import LINK_TYPES
from lore.modules.languages.models import LexiconEntry
from lore.modules.languages.router import router


def _write_language(
    _context: VaultContext, _entity: Entity, ext: dict[str, Any] | None, _creating: bool
) -> None:
    if ext is not None:
        raise InvalidInputError("Languages have no `ext`.")


def _read_language(
    _context: VaultContext, _entity: Entity, _policy: VisibilityPolicy
) -> dict[str, Any] | None:
    return None


def _update_language(context: VaultContext, entity: Entity, sent: frozenset[str]) -> None:
    """A changed `alphabet_order` re-sorts the lexicon (same transaction)."""
    if "fields" in sent:
        Lexicon(context).recollate(entity)


if reindex_after_revert not in REVERT_HOOKS:
    REVERT_HOOKS.append(reindex_after_revert)

MODULE = ModuleSpec(
    id="languages",
    name="Languages",
    description="Languages and writing systems, their families, speakers and lexicons.",
    kinds=(LANGUAGE_KIND, WRITING_SYSTEM_KIND),
    link_types=LINK_TYPES,
    models=(LexiconEntry,),
    history_tables=(HistoryTable.of(LexiconEntry, columns_owner("language_id")),),
    routers=(router,),
    slot_providers=(LEXICON_SLOTS,),
    search_contributors=(LEXICON_SEARCH,),
    visibility_filters=(LEXICON_VISIBILITY,),
    kind_extensions=(
        KindExtension(
            LANGUAGE, write=_write_language, read=_read_language, update=_update_language
        ),
    ),
    purge_hooks=(purge_entries,),
)

__all__ = ["ALPHABET_FIELD", "MODULE"]
