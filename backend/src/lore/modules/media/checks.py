"""The media module's part of ``lore vault check`` / ``reindex`` (``ModuleSpec.derived_checks``):
``media_refs`` against bodies, fields, covers and galleries, and every item's file on disk."""

from collections.abc import Iterator

from sqlalchemy import or_, select

from lore.core.entities.models import Entity
from lore.core.maintenance.checks import DerivedDataCheck, Problem
from lore.core.modules.spec import VaultContext
from lore.modules.media import storage
from lore.modules.media.models import MediaItem, MediaRef
from lore.modules.media.refs import DERIVED, Refs

CHECK = "media"


def verify(context: VaultContext) -> Iterator[Problem]:
    session = context.session
    refs = Refs(context)
    existing = set(session.scalars(select(MediaItem.id)))
    stored: dict[str, dict[tuple[str, str], str]] = {}
    rows = session.execute(
        select(MediaRef.entity_id, MediaRef.media_id, MediaRef.context, MediaRef.visibility).where(
            or_(MediaRef.context.in_(DERIVED), MediaRef.context.startswith("field:"))
        )
    )
    for entity_id, media_id, where, level in rows:
        stored.setdefault(entity_id, {})[(media_id, where)] = level
    for entity in session.scalars(select(Entity).order_by(Entity.id)):
        wanted = {key: level for key, level in refs.wanted(entity).items() if key[0] in existing}
        if wanted != stored.get(entity.id, {}):
            yield Problem(
                CHECK, "stale_refs", f"entity {entity.id}: its media references are stale"
            )
    path = context.vault.info.path
    for media_id, sha256, filename in session.execute(
        select(MediaItem.id, MediaItem.sha256, MediaItem.filename).order_by(MediaItem.id)
    ):
        if not storage.file_path(path, sha256).is_file():
            yield Problem(
                CHECK, "missing_file", f"media item {media_id} ({filename}): its file is missing"
            )


def rebuild(context: VaultContext) -> int:
    ids = list(context.session.scalars(select(Entity.id)))
    Refs(context).rebuild(ids)
    return len(ids)


MEDIA_CHECK = DerivedDataCheck(
    id=CHECK,
    description="media references, and every item's file",
    verify=verify,
    rebuild=rebuild,
    unit="entities",
)
