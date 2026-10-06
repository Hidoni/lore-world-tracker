"""Core's time-bearing record types and kind extensions, registered with the module registry
(``time-model.md`` §6, ``modules.md`` §2.1)."""

from lore.core.entities.extensions import KindExtension
from lore.core.time import calendars, dimensions
from lore.core.time.models import Calendar, Dimension, Timeline
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
    SlotProvider(
        calendars.CALENDAR,
        Calendar,
        (SlotDef("*"),),  # alignment:<regime>, regime:<regime>, era:<era>, overlay:<overlay>
        id_column="entity_id",
        load=calendars.load_calendar_slots,
        write=calendars.write_calendar_slots,
        beyond=calendars.calendar_moments_beyond,
        write_spec=calendars.write_calendar_specs,
        keys=calendars.calendar_slot_keys,
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
    KindExtension(
        calendars.CALENDAR,
        write=calendars.write_calendar,
        read=calendars.read_calendar,
        trash=calendars.trash_calendar,
        purge=calendars.purge_calendar,
        stored_problems=calendars.calendar_problems,
    ),
)
