"""The media service (``docs/modules/media.md``): uploads, the library, files, galleries.

Reader visibility (``visibility-and-sharing.md`` §2): an item is visible iff a context a reader
sees references it: a ``media_refs`` row that isn't private, of an entity the reader sees
(``REF_VISIBILITY``). Everything else answers 404, the file endpoint included. Gallery items
follow their own visibility and their entity's (``GALLERY_VISIBILITY``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, InvalidInputError, NotFoundError
from lore.core.history import recorder
from lore.core.modules.spec import VaultContext
from lore.core.visibility import AUTHOR, VisibilityFilter, VisibilityPolicy
from lore.modules.media import storage, svg
from lore.modules.media.models import MediaGalleryItem, MediaItem, MediaRef
from lore.modules.media.refs import Refs
from lore.modules.media.schemas import (
    GalleryItemCreate,
    GalleryItemOut,
    GalleryItemUpdate,
    GalleryOut,
    MediaItemList,
    MediaItemOut,
    MediaItemUpdate,
    MediaRefOut,
    MediaUploadResult,
)

REF_VISIBILITY = VisibilityFilter(MediaRef, entity_columns=("entity_id",))
GALLERY_VISIBILITY = VisibilityFilter(MediaGalleryItem, entity_columns=("entity_id",))
MAX_FILENAME = 255
PAGE = 100


@dataclass(frozen=True)
class ServedFile:
    """What the file endpoint sends: a file on disk (``path``) or bytes made now (``data``), its
    type, and whether pages may show it (``inline``) or it downloads (an attachment)."""

    item: MediaItem
    path: Path | None
    data: bytes | None
    mime: str
    inline: bool


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[{"path": path, "code": "invalid_value",
                                               "message": message}])  # fmt: skip


def tile_levels(row: MediaItem) -> int | None:
    """``MediaItemOut.tile_levels``: the coarsest tile level of an image shown as tiles."""
    width, height = row.width, row.height
    if row.mime not in storage.RASTER or width is None or height is None:
        return None
    return storage.tile_levels(width, height) if storage.tiled(width, height) else None


def _display_name(filename: str | None) -> str:
    """The uploaded name, for display: its last path component, without control characters."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:MAX_FILENAME] or "file"


class Media:
    def __init__(self, context: VaultContext, policy: VisibilityPolicy = AUTHOR) -> None:
        self.context = context
        self.session: Session = context.session
        self.policy = policy

    @property
    def vault_path(self) -> Path:
        return self.context.vault.info.path

    # --- visibility ----------------------------------------------------------------------------

    def visible_conditions(self) -> list[Any]:
        """Conditions on ``MediaItem`` rows this request may see."""
        if self.policy is AUTHOR:
            return []
        seen = select(MediaRef.media_id).where(
            MediaRef.media_id == MediaItem.id, *self.policy.module_rows(REF_VISIBILITY, MediaRef)
        )
        return [MediaItem.deleted_at.is_(None), exists(seen)]

    def item(self, media_id: str, *, trashed: bool = True) -> MediaItem:
        row = self.session.scalars(
            select(MediaItem).where(MediaItem.id == media_id, *self.visible_conditions())
        ).one_or_none()
        if row is None or (not trashed and row.deleted_at is not None):
            raise NotFoundError(f"No media item {media_id}.")
        return row

    def _refs(self, media_ids: Sequence[str]) -> dict[str, list[MediaRefOut]]:
        found: dict[str, list[MediaRefOut]] = {}
        if not media_ids:
            return found
        rows = self.session.execute(
            select(MediaRef.media_id, MediaRef.entity_id, MediaRef.context)
            .where(
                MediaRef.media_id.in_(media_ids), *self.policy.module_rows(REF_VISIBILITY, MediaRef)
            )
            .order_by(MediaRef.media_id, MediaRef.entity_id, MediaRef.context)
        )
        for media_id, entity_id, context in rows:
            found.setdefault(media_id, []).append(MediaRefOut(entity_id=entity_id, context=context))
        return found

    def out(self, row: MediaItem, refs: list[MediaRefOut] | None = None) -> MediaItemOut:
        return MediaItemOut(
            id=row.id, sha256=row.sha256, filename=row.filename, mime=row.mime, size=row.size,
            width=row.width, height=row.height, tile_levels=tile_levels(row), alt=row.alt,
            caption=row.caption,
            revision=row.revision, created_at=row.created_at, deleted_at=row.deleted_at,
            refs=refs if refs is not None else self._refs([row.id]).get(row.id, []),
        )  # fmt: skip

    # --- library -------------------------------------------------------------------------------

    def upload(
        self, data: bytes, filename: str | None, *, alt: str = "", caption: str = ""
    ) -> MediaUploadResult:
        """Store an upload (``security.md`` §3). The same bytes are one item: uploading them
        again returns it (brought back from the trash if it was there)."""
        try:
            sniffed = storage.sniff(data, filename or "")
        except storage.MediaRejectedError as error:
            raise _invalid("file", str(error)) from error
        sha256 = storage.digest(data)
        existing = self.session.scalars(
            select(MediaItem).where(MediaItem.sha256 == sha256)
        ).one_or_none()
        storage.store(self.vault_path, sha256, data)
        if existing is not None:
            if existing.deleted_at is not None:
                existing.deleted_at = None
                recorder.describe(self.session, f"Restored {existing.filename}")
            self.session.flush()
            return MediaUploadResult(item=self.out(existing), created=False)
        row = MediaItem(
            sha256=sha256, filename=_display_name(filename), mime=sniffed.mime, size=len(data),
            width=sniffed.width, height=sniffed.height, alt=alt, caption=caption,
        )  # fmt: skip
        self.session.add(row)
        self.session.flush()
        recorder.describe(self.session, f"Uploaded {row.filename}")
        return MediaUploadResult(item=self.out(row, []), created=True)

    def list(
        self,
        *,
        unused: bool = False,
        entity: str | None = None,
        q: str | None = None,
        mime: str | None = None,
        trashed: bool = False,
        cursor: str | None = None,
        limit: int = PAGE,
    ) -> MediaItemList:
        """The library, newest first."""
        statement = select(MediaItem).where(*self.visible_conditions())
        statement = statement.where(
            MediaItem.deleted_at.is_not(None) if trashed else MediaItem.deleted_at.is_(None)
        )
        if unused:
            statement = statement.where(
                ~exists(select(MediaRef.media_id).where(MediaRef.media_id == MediaItem.id))
            )
        if entity is not None:
            statement = statement.where(
                exists(
                    select(MediaRef.media_id).where(
                        MediaRef.media_id == MediaItem.id,
                        MediaRef.entity_id == entity,
                        *self.policy.module_rows(REF_VISIBILITY, MediaRef),
                    )
                )
            )
        if q:
            pattern = f"%{q.lower()}%"
            statement = statement.where(
                func.lower(MediaItem.filename).like(pattern)
                | func.lower(MediaItem.alt).like(pattern)
                | func.lower(MediaItem.caption).like(pattern)
            )
        if mime:
            statement = statement.where(
                MediaItem.mime.startswith(mime) if mime.endswith("/") else MediaItem.mime == mime
            )
        if cursor:
            statement = statement.where(MediaItem.id < cursor)
        rows = list(self.session.scalars(statement.order_by(MediaItem.id.desc()).limit(limit + 1)))
        page = rows[:limit]
        refs = self._refs([row.id for row in page])
        return MediaItemList(
            items=[self.out(row, refs.get(row.id, [])) for row in page],
            next_cursor=page[-1].id if len(rows) > limit else None,
        )

    def update(self, media_id: str, data: MediaItemUpdate) -> MediaItemOut:
        row = self.item(media_id)
        if data.revision != row.revision:
            raise ConflictError(
                f"The media item changed (revision {row.revision}, the edit is based on "
                f"{data.revision}).",
                context={"current_revision": row.revision},
            )
        sent = data.model_fields_set - {"revision"}
        if "alt" in sent:
            row.alt = data.alt or ""
        if "caption" in sent:
            row.caption = data.caption or ""
        self.session.flush()
        return self.out(row)

    def replace(
        self, media_id: str, data: bytes, filename: str | None, *, revision: int
    ) -> MediaItemOut:
        """Put other bytes under the item (the library's "replace file"): everything that uses
        it shows the new file. An image stays an image; bytes another item already holds are
        refused (``409``, that item in ``context``). The old file stays on disk, so undo works."""
        row = self.item(media_id, trashed=False)
        if revision != row.revision:
            raise ConflictError(
                f"The media item changed (revision {row.revision}, the edit is based on "
                f"{revision}).",
                context={"current_revision": row.revision},
            )
        try:
            sniffed = storage.sniff(data, filename or "")
        except storage.MediaRejectedError as error:
            raise _invalid("file", str(error)) from error
        if (row.mime in storage.RASTER and sniffed.mime not in storage.RASTER) or (
            row.mime in storage.IMAGES and sniffed.mime not in storage.IMAGES
        ):
            raise _invalid("file", "An image can only be replaced by an image.")
        sha256 = storage.digest(data)
        if sha256 == row.sha256:
            return self.out(row)
        other = self.session.scalars(
            select(MediaItem.id).where(MediaItem.sha256 == sha256)
        ).one_or_none()
        if other is not None:
            raise ConflictError("The library already has this file.", context={"media_id": other})
        storage.store(self.vault_path, sha256, data)
        row.sha256, row.mime, row.size = sha256, sniffed.mime, len(data)
        row.width, row.height = sniffed.width, sniffed.height
        row.filename = _display_name(filename)
        recorder.describe(self.session, f"Replaced the file of {row.filename}")
        self.session.flush()
        return self.out(row)

    def trash(self, media_id: str, now: datetime | None = None) -> MediaItemOut:
        """Move to the trash (idempotent); the file stays until the item is purged."""
        row = self.item(media_id)
        if row.deleted_at is None:
            row.deleted_at = now or datetime.now(UTC)
            recorder.describe(self.session, f"Moved {row.filename} to the trash")
            self.session.flush()
        return self.out(row)

    def restore(self, media_id: str) -> MediaItemOut:
        row = self.item(media_id)
        if row.deleted_at is not None:
            row.deleted_at = None
            recorder.describe(self.session, f"Restored {row.filename}")
            self.session.flush()
        return self.out(row)

    def file(self, media_id: str, size: str) -> ServedFile:
        """The item and what to send: a file on disk, or bytes made now (a thumbnail, or a
        sanitized SVG, of a vault that can't be written). Sizes other than ``original`` exist for
        raster images only. An SVG is sent sanitized (``lore.modules.media.svg``) and inline; one
        the sanitizer can't read (stored before it existed) is sent as it is, as an attachment."""
        row = self.item(media_id)
        path = storage.file_path(self.vault_path, row.sha256)
        if size == "original":
            if not path.is_file():
                raise NotFoundError(f"The file of media item {media_id} is missing.")
            if row.mime == storage.SVG:
                try:
                    cached, data = storage.safe_svg(self.vault_path, row.sha256)
                except svg.SvgRejectedError:
                    return ServedFile(row, path, None, row.mime, inline=False)
                return ServedFile(row, cached, data, row.mime, inline=True)
            return ServedFile(row, path, None, row.mime, inline=row.mime in storage.RASTER)
        if row.mime not in storage.RASTER:
            raise _invalid("size", "Only images have thumbnails.")
        width = int(size)
        if width not in storage.THUMB_WIDTHS:
            raise _invalid("size", "Unknown size.")
        if not path.is_file():
            raise NotFoundError(f"The file of media item {media_id} is missing.")
        cached, data = storage.thumbnail(self.vault_path, row.sha256, width)
        return ServedFile(row, cached, data, "image/webp", inline=True)

    def tile(self, media_id: str, level: int, x: int, y: int) -> ServedFile:
        """A tile of a raster image (#162): level ``level`` (the image shrunk ``2^level``
        times, ``0`` to its ``tile_levels``), column ``x``, row ``y``. Any raster image has
        tiles; clients use them for the images whose ``tile_levels`` isn't null."""
        row = self.item(media_id)
        if row.mime not in storage.RASTER or row.width is None or row.height is None:
            raise _invalid("media_id", "Only raster images have tiles.")
        if level > storage.tile_levels(row.width, row.height):
            raise NotFoundError(f"Media item {media_id} has no tile level {level}.")
        across, down = storage.tile_count(row.width, row.height, level)
        if x >= across or y >= down:
            raise NotFoundError(f"Media item {media_id} has no tile {x}, {y} at level {level}.")
        if not storage.file_path(self.vault_path, row.sha256).is_file():
            raise NotFoundError(f"The file of media item {media_id} is missing.")
        cached, data = storage.tile(
            self.vault_path, row.sha256, size=(row.width, row.height), level=level, x=x, y=y
        )
        return ServedFile(row, cached, data, "image/webp", inline=True)

    # --- galleries -----------------------------------------------------------------------------

    def _entity(self, entity_id: str) -> Entity:
        """A visible entity of an available kind (not one of a disabled module's or an archived
        custom kind)."""
        entity = self.session.scalars(
            select(Entity).where(Entity.id == entity_id, *self.policy.entities(Entity))
        ).one_or_none()
        if entity is None:
            raise NotFoundError(f"No entity {entity_id}.")
        return EntityService(self.context, self.policy).load(entity_id)

    def _gallery_out(self, row: MediaGalleryItem, media: MediaItem) -> GalleryItemOut:
        return GalleryItemOut(
            id=row.id, entity_id=row.entity_id, media_id=row.media_id, caption=row.caption,
            sort_key=row.sort_key, visibility=row.visibility, revision=row.revision,
            media=self.out(media),
        )  # fmt: skip

    def gallery(self, entity_id: str) -> GalleryOut:
        self._entity(entity_id)
        rows = self.session.execute(
            select(MediaGalleryItem, MediaItem)
            .join(MediaItem, MediaItem.id == MediaGalleryItem.media_id)
            .where(
                MediaGalleryItem.entity_id == entity_id,
                MediaGalleryItem.deleted_at.is_(None),
                MediaItem.deleted_at.is_(None),
                *self.policy.module_rows(GALLERY_VISIBILITY, MediaGalleryItem),
            )
            .order_by(MediaGalleryItem.sort_key, MediaGalleryItem.id)
        ).all()
        return GalleryOut(
            entity_id=entity_id, items=[self._gallery_out(row, media) for row, media in rows]
        )

    def _gallery_item(self, item_id: str) -> MediaGalleryItem:
        row = self.session.get(MediaGalleryItem, item_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError(f"No gallery item {item_id}.")
        return row

    def add_to_gallery(self, entity_id: str, data: GalleryItemCreate) -> GalleryItemOut:
        entity = self._entity(entity_id)
        media = self.session.get(MediaItem, data.media_id)
        if media is None or media.deleted_at is not None:
            raise _invalid("media_id", "No such media item.")
        sort_key = data.sort_key
        if sort_key is None:
            last = self.session.scalar(
                select(func.max(MediaGalleryItem.sort_key)).where(
                    MediaGalleryItem.entity_id == entity.id, MediaGalleryItem.deleted_at.is_(None)
                )
            )
            sort_key = f"{last}V" if last else "a"
        row = MediaGalleryItem(
            entity_id=entity.id, media_id=media.id, caption=data.caption, sort_key=sort_key,
            visibility=data.visibility,
        )  # fmt: skip
        self.session.add(row)
        self.session.flush()
        recorder.describe(self.session, f"Added {media.filename} to the gallery of {entity.name}")
        return self._gallery_out(row, media)

    def update_gallery_item(self, item_id: str, data: GalleryItemUpdate) -> GalleryItemOut:
        row = self._gallery_item(item_id)
        if data.revision != row.revision:
            raise ConflictError(
                f"The gallery item changed (revision {row.revision}, the edit is based on "
                f"{data.revision}).",
                context={"current_revision": row.revision},
            )
        sent = data.model_fields_set - {"revision"}
        if "caption" in sent:
            row.caption = data.caption or ""
        if "sort_key" in sent and data.sort_key is not None:
            row.sort_key = data.sort_key
        if "visibility" in sent and data.visibility is not None:
            row.visibility = data.visibility
        self.session.flush()
        media = self.session.get(MediaItem, row.media_id)
        assert media is not None
        return self._gallery_out(row, media)

    def remove_from_gallery(self, item_id: str) -> None:
        row = self._gallery_item(item_id)
        row.deleted_at = datetime.now(UTC)
        self.session.flush()

    def rebuild_all_refs(self) -> None:
        """Every entity's derived refs (after enabling the module, or a repair)."""
        ids = self.session.scalars(select(Entity.id))
        Refs(self.context).rebuild(ids)


__all__ = ["GALLERY_VISIBILITY", "REF_VISIBILITY", "Media"]
