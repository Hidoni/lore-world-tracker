"""The maps module's spec (``docs/modules/maps.md``)."""

from lore.core.history.tables import HistoryTable, columns_owner
from lore.core.modules import ModuleSpec, StaticRead
from lore.modules.maps.consistency import CONSISTENCY_RULES
from lore.modules.maps.models import Map, MapPin, MapRegion
from lore.modules.maps.publish import publish_maps
from lore.modules.maps.router import router
from lore.modules.maps.service import (
    MAP_VISIBILITY,
    PIN_SLOTS,
    PIN_VISIBILITY,
    REGION_SLOTS,
    REGION_VISIBILITY,
    purge_maps,
)

MODULE = ModuleSpec(
    id="maps",
    name="Maps",
    description="Maps of locations with pins and regions that follow the time cursor, nested "
    "maps to drill into.",
    depends_on=("locations", "media"),
    models=(Map, MapPin, MapRegion),
    history_tables=(
        HistoryTable.of(Map, columns_owner("location_id")),
        HistoryTable.of(MapPin, columns_owner("target_entity_id")),
        HistoryTable.of(MapRegion, columns_owner("target_entity_id")),
    ),
    routers=(router,),
    slot_providers=(PIN_SLOTS, REGION_SLOTS),
    visibility_filters=(MAP_VISIBILITY, PIN_VISIBILITY, REGION_VISIBILITY),
    consistency_rules=CONSISTENCY_RULES,
    purge_hooks=(purge_maps,),
    publish_contributors=(publish_maps,),
    static_reads=(
        StaticRead("maps"),
        StaticRead("maps", kind="location", variants=((("location", "{id}"),),)),
        StaticRead("maps/{id}", ids_from="maps", timeline=True, as_of=True, event_moments=True),
        StaticRead("entities/{id}/pins", kind="*"),
    ),
)
