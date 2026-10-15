"""Request and response models of the media module (``docs/modules/media.md``, API)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from lore.core.db.base import Visibility
from lore.core.entities.schemas import EntityId, SortKey

Caption = Annotated[str, StringConstraints(max_length=2000)]
Alt = Annotated[str, StringConstraints(max_length=1000)]


class MediaRefOut(BaseModel):
    entity_id: str
    context: str = Field(description="`body`, `field:<key>`, `cover`, `gallery`, `map` or `note`.")


class MediaItemOut(BaseModel):
    id: str
    sha256: str
    filename: str = Field(description="The uploaded name (display only).")
    mime: str
    size: int
    width: int | None
    height: int | None
    alt: str
    caption: str
    revision: int
    created_at: datetime
    deleted_at: datetime | None
    refs: list[MediaRefOut] = Field(
        default_factory=list, description="Where it is used (as the request sees it)."
    )


class MediaUploadResult(BaseModel):
    item: MediaItemOut
    created: bool = Field(description="False when the same bytes were already stored.")


class MediaItemList(BaseModel):
    items: list[MediaItemOut]
    next_cursor: str | None


class MediaItemUpdate(BaseModel):
    revision: int
    alt: Alt | None = None
    caption: Caption | None = None


class GalleryItemOut(BaseModel):
    id: str
    entity_id: str
    media_id: str
    caption: str
    sort_key: str
    visibility: Visibility
    revision: int
    media: MediaItemOut


class GalleryOut(BaseModel):
    entity_id: str
    items: list[GalleryItemOut]


class GalleryItemCreate(BaseModel):
    media_id: EntityId
    caption: Caption = ""
    sort_key: SortKey | None = Field(default=None, description="Default: after the last item.")
    visibility: Visibility = "public"


class GalleryItemUpdate(BaseModel):
    revision: int
    caption: Caption | None = None
    sort_key: SortKey | None = None
    visibility: Visibility | None = None
