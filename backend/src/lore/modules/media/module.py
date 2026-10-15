"""The media module's spec (``docs/modules/media.md``)."""

from sqlalchemy import select

from lore.core.entities.models import Entity
from lore.core.history.tables import HistoryTable, columns_owner
from lore.core.modules import ModuleSpec, VaultContext
from lore.modules.media.fields import MEDIA_FIELD_TYPE
from lore.modules.media.gc import collect_task
from lore.modules.media.models import MediaGalleryItem, MediaItem, MediaRef
from lore.modules.media.refs import Refs, rebuild_refs
from lore.modules.media.richtext import IMAGE_NODE
from lore.modules.media.router import router
from lore.modules.media.service import GALLERY_VISIBILITY, REF_VISIBILITY


def purge_gallery(context: VaultContext, entity: Entity) -> None:
    """Before an entity is purged: its gallery goes with it (recorded, like the entity)."""
    rows = context.session.scalars(
        select(MediaGalleryItem).where(MediaGalleryItem.entity_id == entity.id)
    )
    for row in rows:
        context.session.delete(row)
    context.session.flush()


def rebuild_on_enable(context: VaultContext) -> None:
    """Enabling the module (again) derives every entity's references from what is stored."""
    Refs(context).rebuild(context.session.scalars(select(Entity.id)))


MODULE = ModuleSpec(
    id="media",
    name="Media",
    description="Images and files in the vault: covers, galleries and images in pages.",
    field_types=(MEDIA_FIELD_TYPE,),
    models=(MediaItem, MediaRef, MediaGalleryItem),
    history_tables=(
        HistoryTable.of(MediaItem),
        HistoryTable.of(MediaGalleryItem, columns_owner("entity_id")),
    ),
    routers=(router,),
    visibility_filters=(REF_VISIBILITY, GALLERY_VISIBILITY),
    richtext_nodes=(IMAGE_NODE,),
    purge_hooks=(purge_gallery,),
    derived_hooks=(rebuild_refs,),
    maintenance_tasks=(collect_task,),
    on_enable=rebuild_on_enable,
)
