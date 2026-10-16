"""The custom_fields module's spec (``docs/modules/custom_fields.md``)."""

from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec
from lore.modules.custom_fields.models import CustomFieldDef
from lore.modules.custom_fields.router import router
from lore.modules.custom_fields.service import provide_fields

MODULE = ModuleSpec(
    id="custom_fields",
    name="Custom fields",
    description="Your own structured fields on any kind.",
    models=(CustomFieldDef,),
    history_tables=(HistoryTable.of(CustomFieldDef),),
    routers=(router,),
    field_providers=(provide_fields,),
)
