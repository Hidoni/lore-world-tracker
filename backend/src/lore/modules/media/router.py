"""Routes of the media module, mounted at ``/api/v1/vaults/{vault_id}/m/media``
(``docs/modules/media.md``, API; ``security.md`` §3)."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Path, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    SettingsDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.entities.schemas import ID_PATTERN
from lore.core.errors import InvalidInputError
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.vaults import OpenVault
from lore.core.visibility import AUTHOR, VisibilityPolicy
from lore.modules.media import storage, svg
from lore.modules.media.schemas import (
    Alt,
    Caption,
    GalleryItemCreate,
    GalleryItemOut,
    GalleryItemUpdate,
    GalleryOut,
    MediaItemList,
    MediaItemOut,
    MediaItemUpdate,
    MediaUploadResult,
)
from lore.modules.media.service import Media

router = APIRouter(tags=["media"])

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]
Size = Literal["160", "480", "1280", "original"]
CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
CACHE = "private, max-age=31536000, immutable"


def _media(
    vault: OpenVault, session: Session, registry: ModuleRegistry,
    policy: VisibilityPolicy = AUTHOR,
) -> Media:  # fmt: skip
    return Media(VaultContext(vault, session, registry), policy)


@router.post("/items", name="upload", status_code=201)
def upload(
    *,
    file: Annotated[UploadFile, File(description="The file (an allowed type, within the limit).")],
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    settings: SettingsDep,
    alt: Annotated[Alt, Form()] = "",
    caption: Annotated[Caption, Form()] = "",
) -> MediaUploadResult:
    """Upload a file (``security.md`` §3): its type is read from its bytes and must be an image
    (png, jpeg, webp, gif, avif), a document (pdf, plain text, Markdown) or an SVG (shown
    sanitized; one the sanitizer can't read is refused); images are decoded, and refused above
    the pixel limit. Files larger than
    ``LORE_MAX_UPLOAD_MB`` are refused. The same bytes are stored once: uploading them again
    returns the existing item (``created: false``). Refusals are ``422``, path ``file``."""
    try:
        data = storage.read_limited(file.file, settings.max_upload_mb << 20)
    except storage.MediaRejectedError as error:
        message = str(error)
        raise InvalidInputError(
            message, errors=[{"path": "file", "code": "too_large", "message": message}]
        ) from error
    return _media(vault, session, registry).upload(data, file.filename, alt=alt, caption=caption)


@router.get("/items", name="list")
def list_items(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    unused: Annotated[bool, Query(description="Only items nothing uses.")] = False,
    entity: Annotated[
        str | None, Query(pattern=ID_PATTERN, description="Only items this entity uses.")
    ] = None,
    q: Annotated[
        str | None, Query(max_length=200, description="In names, alt and captions.")
    ] = None,
    mime: Annotated[
        str | None, Query(max_length=100, description="A type, or a prefix ending in `/`.")
    ] = None,
    trashed: Annotated[bool, Query(description="The items in the trash instead.")] = False,
    cursor: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> MediaItemList:
    """The media library, newest first. Readers see only items a visible context uses."""
    return _media(vault, session, registry, policy).list(
        unused=unused, entity=entity, q=q, mime=mime, trashed=trashed, cursor=cursor, limit=limit
    )


@router.get("/items/{media_id}", name="get")
def get_item(
    media_id: IdPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> MediaItemOut:  # fmt: skip
    """One item and where it is used (``404`` for readers unless a visible context uses it)."""
    service = _media(vault, session, registry, policy)
    return service.out(service.item(media_id))


@router.patch("/items/{media_id}", name="update")
def update_item(
    media_id: IdPath, body: MediaItemUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> MediaItemOut:  # fmt: skip
    """Change the alt text or caption (``409`` when ``revision`` is stale)."""
    return _media(vault, session, registry).update(media_id, body)


@router.put("/items/{media_id}/file", name="replace_file")
def replace_file(
    *,
    media_id: IdPath,
    file: Annotated[UploadFile, File(description="The new file (an allowed type).")],
    revision: Annotated[int, Form()],
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    settings: SettingsDep,
) -> MediaItemOut:
    """Replace the item's file, keeping its id (pages, galleries and maps that use it show the
    new one). An image must stay an image (``422``, path ``file``); bytes another item holds are
    a ``409`` naming it (``context.media_id``), as is a stale ``revision``."""
    try:
        data = storage.read_limited(file.file, settings.max_upload_mb << 20)
    except storage.MediaRejectedError as error:
        message = str(error)
        raise InvalidInputError(
            message, errors=[{"path": "file", "code": "too_large", "message": message}]
        ) from error
    return _media(vault, session, registry).replace(
        media_id, data, file.filename, revision=revision
    )


@router.delete("/items/{media_id}", name="trash")
def trash_item(
    media_id: IdPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> MediaItemOut:
    """Move to the trash (pages that use it show it as missing); the file is kept until the
    item is purged by the daily collection (``docs/modules/media.md``, GC)."""
    return _media(vault, session, registry).trash(media_id)


@router.post("/items/{media_id}/restore", name="restore")
def restore_item(
    media_id: IdPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> MediaItemOut:
    """Bring an item back from the trash."""
    return _media(vault, session, registry).restore(media_id)


@router.get(
    "/items/{media_id}/file",
    name="file",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The bytes."}},
)
def get_file(
    *,
    media_id: IdPath,
    request: Request,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    size: Annotated[Size, Query(description="A WebP thumbnail width, or the original.")] = (
        "original"
    ),
) -> Response:
    """The file (``security.md`` §3): ``Content-Type`` from the stored item, ``nosniff``, a
    restrictive CSP, ``ETag`` (the hash, plus the size) and immutable caching. Raster images and
    their thumbnails are inline; an SVG is sanitized and inline (``lore.modules.media.svg``);
    other files are sent as attachments. Thumbnails exist for raster images only."""
    served = _media(vault, session, registry, policy).file(media_id, size)
    row = served.item
    # An SVG's bytes depend on the sanitizer too.
    etag = (
        f'"{row.sha256}-{size}-svg{svg.VERSION}"'
        if row.mime == storage.SVG
        else (f'"{row.sha256}-{size}"')
    )
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": CSP,
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    disposition = "inline" if served.inline else "attachment"
    if served.path is not None:
        return FileResponse(
            served.path, media_type=served.mime, headers=headers, filename=row.filename,
            content_disposition_type=disposition,
        )  # fmt: skip
    headers["Content-Disposition"] = disposition
    return Response(content=served.data, media_type=served.mime, headers=headers)


@router.get(
    "/items/{media_id}/tiles/{level}/{x}/{y}",
    name="tile",
    response_class=Response,
    responses={200: {"content": {"image/webp": {}}, "description": "The tile (WebP)."}},
)
def get_tile(
    *,
    media_id: IdPath,
    level: Annotated[int, Path(ge=0, le=64, description="The image shrunk 2^level times.")],
    x: Annotated[int, Path(ge=0, description="The tile's column, from the left.")],
    y: Annotated[int, Path(ge=0, description="The tile's row, from the top.")],
    request: Request,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> Response:
    """A deep-zoom tile of a raster image (#162; ``docs/modules/media.md``): 256 px square
    (smaller at the right and bottom edges), WebP, cached like files (``ETag``: the hash and the
    tile). The first tile requested makes the image's whole pyramid. Tiles the image doesn't have
    are ``404``; files that aren't raster images ``422``."""
    served = _media(vault, session, registry, policy).tile(media_id, level, x, y)
    etag = f'"{served.item.sha256}-tile-{level}-{x}-{y}"'
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": CSP,
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if served.path is not None:
        return FileResponse(served.path, media_type=served.mime, headers=headers)
    return Response(content=served.data, media_type=served.mime, headers=headers)


# --- galleries ------------------------------------------------------------------------------


@router.get("/entities/{entity_id}/gallery", name="gallery")
def gallery(
    entity_id: IdPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> GalleryOut:  # fmt: skip
    """The entity's gallery, in order."""
    return _media(vault, session, registry, policy).gallery(entity_id)


@router.post("/entities/{entity_id}/gallery", name="add_to_gallery", status_code=201)
def add_to_gallery(
    entity_id: IdPath, body: GalleryItemCreate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> GalleryItemOut:  # fmt: skip
    """Add an item to the gallery (at the end unless ``sort_key`` says where)."""
    return _media(vault, session, registry).add_to_gallery(entity_id, body)


@router.patch("/gallery/{item_id}", name="update_gallery_item")
def update_gallery_item(
    item_id: IdPath, body: GalleryItemUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> GalleryItemOut:  # fmt: skip
    """Change a gallery item's caption, place (``sort_key``) or visibility."""
    return _media(vault, session, registry).update_gallery_item(item_id, body)


@router.delete("/gallery/{item_id}", name="remove_from_gallery", status_code=204)
def remove_from_gallery(
    item_id: IdPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> Response:
    """Take an item out of the gallery (the item itself stays in the library)."""
    _media(vault, session, registry).remove_from_gallery(item_id)
    return Response(status_code=204)
