"""Feature modules, one package per module (see ``docs/architecture/modules.md``)."""

from sqlalchemy import MetaData

from lore.core.models import load_metadata as load_core_metadata
from lore.core.modules import ModuleSpec
from lore.modules.branches import MODULE as BRANCHES
from lore.modules.characters import MODULE as CHARACTERS
from lore.modules.correspondences import MODULE as CORRESPONDENCES
from lore.modules.custom_fields import MODULE as CUSTOM_FIELDS
from lore.modules.graph import MODULE as GRAPH
from lore.modules.groups import MODULE as GROUPS
from lore.modules.languages import MODULE as LANGUAGES
from lore.modules.locations import MODULE as LOCATIONS
from lore.modules.maps import MODULE as MAPS
from lore.modules.media import MODULE as MEDIA
from lore.modules.misc import MODULE as MISC
from lore.modules.species import MODULE as SPECIES
from lore.modules.worldlines import MODULE as WORLDLINES

# Every module's spec, in dependency order. Explicit: no entry points, no discovery (§2.2).
ALL_MODULES: list[ModuleSpec] = [
    MEDIA, MISC, LOCATIONS, SPECIES, CHARACTERS, GROUPS, LANGUAGES, GRAPH, BRANCHES,
    CORRESPONDENCES, WORLDLINES, MAPS, CUSTOM_FIELDS,
]  # fmt: skip


def load_metadata() -> MetaData:
    """Core and module ORM metadata: what ``lore db check`` / ``lore db revision`` compare the
    migrations against. Module models register themselves when ``ALL_MODULES`` is imported."""
    return load_core_metadata()
