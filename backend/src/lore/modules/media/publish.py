"""The media module's publish contributor (``docs/modules/media.md``, Visibility, backup,
publish): a published snapshot gets the files of the items readers may see, with their
thumbnails made in advance (a reader-side server may not be able to write). Published snapshots
themselves arrive with #140, which calls this through ``ModuleSpec.publish_contributors``."""

import shutil
from pathlib import Path

from sqlalchemy import select

from lore.core.modules.spec import VaultContext
from lore.core.visibility import READER
from lore.modules.media import storage
from lore.modules.media.models import MediaItem
from lore.modules.media.service import Media


def publish_media(context: VaultContext, target: Path) -> list[str]:
    """Copy the reader-visible items' files (and, for raster images, every thumbnail size) into
    ``target`` (a vault folder being published) at the same paths; returns their ids."""
    source = context.vault.info.path
    service = Media(context, READER)
    rows = context.session.execute(
        select(MediaItem.id, MediaItem.sha256, MediaItem.mime)
        .where(*service.visible_conditions())
        .order_by(MediaItem.id)
    ).all()
    copied: list[str] = []
    for media_id, sha256, mime in rows:
        original = storage.file_path(source, sha256)
        if not original.is_file():
            continue
        destination = storage.file_path(target, sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        if mime in storage.RASTER:
            for width in storage.THUMB_WIDTHS:
                cached, data = storage.thumbnail(source, sha256, width)
                out = storage.thumb_path(target, sha256, width)
                out.parent.mkdir(parents=True, exist_ok=True)
                if cached is not None:
                    shutil.copyfile(cached, out)
                elif data is not None:
                    out.write_bytes(data)
        copied.append(media_id)
    return copied


__all__ = ["publish_media"]
