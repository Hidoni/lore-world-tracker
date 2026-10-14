"""Core's time-bearing record types and kind extensions, registered with the module registry
(``time-model.md`` §6, ``modules.md`` §2.1)."""

from lore.core.entities.extensions import KindExtension
from lore.core.facts.models import EntityFact
from lore.core.links.models import Link
from lore.core.time import calendars, dimensions, events, series
from lore.core.time.fields import ENTITY_FIELD_SLOTS
from lore.core.time.models import Calendar, CorrespondencePoint, Dimension, Event, Timeline
from lore.core.time.slots import SlotDef, SlotProvider

SYNC_POINT = "sync_point"

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
        events.EVENT,
        Event,
        (
            SlotDef("start", referenceable=True),
            SlotDef("end", spec="end", referenceable=True),
            # The recurrence rule's time points (recurrence.md §2), stored in the rule.
            SlotDef(series.UNTIL_SLOT, custom=True),
            SlotDef("exclusion:*"),  # exclusion:<i>.from, exclusion:<i>.to
        ),
        # The home rows: refs name the event entity (seen from a branch, they mean its
        # override there when it has one: ``Resolver.slot``, time-model.md §9.1).
        id_column="entity_id",
        entity_column="entity_id",
        timeline_column="timeline_id",
        load=series.HOME_RULE_SLOTS.load,
        write=series.HOME_RULE_SLOTS.write,
        beyond=series.HOME_RULE_SLOTS.beyond,
        write_spec=series.HOME_RULE_SLOTS.write_specs,
        keys=series.HOME_RULE_SLOTS.keys,
        row_condition="events.overrides_id IS NULL",
        row_test=lambda row: row.get("overrides_id") is None,
    ),
    # Branch override rows of events (time-model.md §4.4): slot owners of their own, by row id.
    # Their start copies their root's spec (an override starts where its root does).
    SlotProvider(
        series.EVENT_OVERRIDE,
        Event,
        (
            SlotDef("start"),
            SlotDef("end", spec="end"),
            SlotDef(series.UNTIL_SLOT, custom=True),
            SlotDef("exclusion:*"),
        ),
        id_column="id",
        entity_column="entity_id",
        timeline_column="timeline_id",
        load=series.OVERRIDE_RULE_SLOTS.load,
        write=series.OVERRIDE_RULE_SLOTS.write,
        beyond=series.OVERRIDE_RULE_SLOTS.beyond,
        write_spec=series.OVERRIDE_RULE_SLOTS.write_specs,
        keys=series.OVERRIDE_RULE_SLOTS.keys,
        row_condition="events.overrides_id IS NOT NULL",
        row_test=lambda row: row.get("overrides_id") is not None,
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
    # Facts' validity (time-model.md §10.1): anchors may refer to a fact's bounds.
    SlotProvider(
        "fact",
        EntityFact,
        (
            SlotDef("valid_from", referenceable=True),
            SlotDef("valid_to", referenceable=True),
        ),
        entity_column="entity_id",
        timeline_column="timeline_id",
    ),
    ENTITY_FIELD_SLOTS,
    # Temporal links' validity (time-model.md §10.3): "married from the Wedding until her Death".
    SlotProvider(
        "link",
        Link,
        (
            SlotDef("valid_from", referenceable=True),
            SlotDef("valid_to", referenceable=True),
        ),
        timeline_column="timeline_id",
    ),
    # Sync points of correspondences (time-model.md §12): ``a`` resolves in dimension A, ``b``
    # in dimension B; either may be anchored to an event of its dimension. They describe how
    # time flows, not history, so their anchors are seen from the prime timelines.
    SlotProvider(
        SYNC_POINT,
        CorrespondencePoint,
        (
            SlotDef("a", dimension_column="a_dimension_id"),
            SlotDef("b", dimension_column="b_dimension_id"),
        ),
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
        events.EVENT,
        write=events.write_event,
        read=events.read_event,
        update=events.update_event,
        trash=events.trash_event,
        purge=events.purge_event,
        stored_problems=events.event_problems,
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
