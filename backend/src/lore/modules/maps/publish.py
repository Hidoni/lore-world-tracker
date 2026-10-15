"""The maps module's publish contributor (``docs/modules/maps.md``, Visibility, publish):
published snapshots (#140) keep only the maps readers see, which are exactly the ones whose
image is reader-visible (a map references its image at its own visibility, for its location),
so the media contributor copies their files."""

from sqlalchemy import select

from lore.core.modules.spec import VaultContext
from lore.core.visibility import READER
from lore.modules.maps.models import Map
from lore.modules.maps.service import MAP_VISIBILITY


def published_maps(context: VaultContext) -> list[str]:
    """The ids of the maps a published snapshot keeps."""
    return list(
        context.session.scalars(
            select(Map.id)
            .where(Map.deleted_at.is_(None), *READER.module_rows(MAP_VISIBILITY))
            .order_by(Map.id)
        )
    )
