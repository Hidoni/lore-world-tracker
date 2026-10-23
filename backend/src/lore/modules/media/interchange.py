"""The media module's tables in interchange documents (``docs/modules/media.md``, Interchange;
``interchange.md`` §5): an item travels with its file, and an item whose content the target
vault already has is that vault's item."""

from pathlib import Path

from lore.core.interchange.spec import InterchangeTable, Row
from lore.modules.media import storage


def item_file(vault_path: Path, row: Row) -> Path | None:
    return storage.file_path(vault_path, str(row["sha256"]))


def store_item_file(vault_path: Path, row: Row, source: Path) -> None:
    """Store an imported item's file: its content must have the item's hash and type (an SVG
    the sanitizer can't read is kept as it is, like one stored before the sanitizer)."""
    data = source.read_bytes()
    sha256 = str(row["sha256"])
    if storage.digest(data) != sha256:
        raise ValueError("the file doesn't have its media item's checksum")
    try:
        sniffed = storage.sniff(data, str(row["filename"]))
    except storage.MediaRejectedError as error:
        if row["mime"] != storage.SVG:
            raise ValueError(f"the file isn't one media items may hold: {error}") from error
    else:
        if sniffed.mime != row["mime"]:
            raise ValueError(f"the file is {sniffed.mime}, its media item says {row['mime']}")
    storage.store(vault_path, sha256, data)


MEDIA_ITEMS = InterchangeTable(
    "media_items", reuse_by_key=True, file=item_file, store=store_item_file
)
