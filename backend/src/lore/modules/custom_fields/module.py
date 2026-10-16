"""The custom_fields module's spec (``docs/modules/custom_fields.md``)."""

from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec
from lore.modules.custom_fields.kinds import provide_kinds
from lore.modules.custom_fields.models import CustomFieldDef, CustomKind
from lore.modules.custom_fields.router import router
from lore.modules.custom_fields.service import provide_fields

MODULE = ModuleSpec(
    id="custom_fields",
    name="Custom fields",
    description="Your own structured fields on any kind, and your own kinds.",
    models=(CustomFieldDef, CustomKind),
    history_tables=(HistoryTable.of(CustomFieldDef), HistoryTable.of(CustomKind)),
    routers=(router,),
    kind_providers=(provide_kinds,),
    field_providers=(provide_fields,),
)
