"""The locations module's link types."""

from lore.core.registry import GraphStyle, LinkTypeDef
from lore.modules.locations.kinds import LOCATION

EVENT_SITE = "locations.event_site"
RESIDES_IN = "locations.resides_in"
ORIGIN = "locations.origin"
CONNECTED_TO = "locations.connected_to"


def _kind_of(*kinds: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"kind": {"enum": list(kinds)}},
        "additionalProperties": False,
    }


LINK_TYPES = (
    LinkTypeDef(
        EVENT_SITE,
        "took place at",
        inverse_label="site of",
        description="Where an event happened.",
        source_kinds=("event",),
        target_kinds=(LOCATION,),
        temporal="never",
    ),
    LinkTypeDef(
        RESIDES_IN,
        "resides in",
        inverse_label="residents",
        description="Someone or something living, based or held at a location.",
        target_kinds=(LOCATION,),
        temporal="optional",
        data_schema=_kind_of("home", "base", "prison", "exile", "other"),
    ),
    LinkTypeDef(
        ORIGIN,
        "originates from",
        inverse_label="origin of",
        description="Where someone or something comes from.",
        target_kinds=(LOCATION,),
        temporal="never",
    ),
    LinkTypeDef(
        CONNECTED_TO,
        "connected to",
        description="A road, river, sea route, portal… Portals may cross dimensions.",
        source_kinds=(LOCATION,),
        target_kinds=(LOCATION,),
        symmetric=True,
        temporal="optional",
        data_schema=_kind_of("road", "river", "sea_route", "portal", "tunnel", "other"),
        graph=GraphStyle(dashed=True),
    ),
)
