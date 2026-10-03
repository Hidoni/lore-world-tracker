"""Feature modules, one package per module (see ``docs/architecture/modules.md``)."""

from sqlalchemy import MetaData

from lore.core.models import load_metadata as load_core_metadata
from lore.core.modules import ModuleSpec

# Every module's spec, in dependency order. Explicit: no entry points, no discovery (§2.2).
ALL_MODULES: list[ModuleSpec] = []


def load_metadata() -> MetaData:
    """Core and module ORM metadata: what ``lore db check`` / ``lore db revision`` compare the
    migrations against. Module models register themselves when ``ALL_MODULES`` is imported."""
    return load_core_metadata()
