"""The ``location`` kind and its fields."""

from lore.core.registry import FieldDef, FieldOption, KindCapabilities, KindDef

LOCATION = "location"

LOCATION_TYPES = (
    ("universe", "Universe"),
    ("galaxy", "Galaxy"),
    ("star_system", "Star system"),
    ("star", "Star"),
    ("planet", "Planet"),
    ("moon", "Moon"),
    ("plane", "Plane"),
    ("continent", "Continent"),
    ("ocean", "Ocean"),
    ("region", "Region"),
    ("country", "Country"),
    ("province", "Province"),
    ("city", "City"),
    ("town", "Town"),
    ("village", "Village"),
    ("district", "District"),
    ("building", "Building"),
    ("room", "Room"),
    ("landmark", "Landmark"),
    ("natural_feature", "Natural feature"),
    ("other", "Other"),
)

LOCATION_KIND = KindDef(
    LOCATION,
    "Location",
    "Locations",
    icon="map-pin",
    color="#10b981",
    description="A place, from a galaxy to a room; locations nest inside each other.",
    allowed_parents=(LOCATION, "misc"),
    fields=(
        FieldDef(
            "location_type",
            "Type",
            "enum",
            options=tuple(FieldOption(key, label) for key, label in LOCATION_TYPES),
            sort=0,
        ),
        FieldDef("type_detail", "Type detail", "text", help="A refinement.", sort=1),
        FieldDef("population", "Population", "integer", temporal=True, sort=2),
        FieldDef("climate", "Climate", "text", temporal=True, sort=3),
        FieldDef("area", "Area", "measurement", sort=4),
        FieldDef("coordinates", "Coordinates", "text", help="Free-form.", sort=5),
    ),
    capabilities=KindCapabilities(has_body=True, can_be_multiversal=True, has_existence=True),
)
