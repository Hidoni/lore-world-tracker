"""Core's time-bearing record types and kind extensions, registered with the module registry
(``time-model.md`` §6, ``modules.md`` §2.1)."""

from lore.core.entities.extensions import KindExtension
from lore.core.time import dimensions
from lore.core.time.models import Dimension, Timeline
from lore.core.time.slots import SlotDef, SlotProvider

CORE_SLOT_PROVIDERS: tuple[SlotProvider, ...] = (
    SlotProvider(
        "dimension",
        Dimension,
        (SlotDef("present"),),
        id_column="entity_id",
        entity_column="entity_id",
        dimension_column="entity_id",
    ),
    SlotProvider(
        "timeline",
        Timeline,
        (SlotDef("branch_point", referenceable=True, resolved_column="branch_t"),),
        id_column="entity_id",
        entity_column="entity_id",
        dimension_column="dimension_id",
    ),
)

CORE_KIND_EXTENSIONS: tuple[KindExtension, ...] = (
    KindExtension(
        dimensions.DIMENSION,
        write=dimensions.write_dimension,
        read=dimensions.read_dimension,
        update=dimensions.update_dimension,
        trash=dimensions.trash_dimension,
        purge=dimensions.purge_dimension,
        stored_problems=dimensions.dimension_problems,
    ),
    KindExtension(
        dimensions.TIMELINE,
        write=dimensions.write_timeline,
        read=dimensions.read_timeline,
        update=dimensions.update_timeline,
        trash=dimensions.trash_timeline,
        purge=dimensions.purge_timeline,
        stored_problems=dimensions.timeline_problems,
    ),
)
