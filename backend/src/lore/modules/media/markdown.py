"""The media module's Markdown contributor (``docs/modules/media.md``, Integration points;
``lore.core.markdown.export``): the files of the items the export's audience may see are copied
into ``_media/`` under their uploaded names, and images, ``media`` fields and covers embed them
(``![[_media/<file>]]``). An image whose item isn't exported shows its alt text."""

import mimetypes
from pathlib import PurePosixPath

from sqlalchemy import select

from lore.core.markdown.export import MEDIA_FOLDER, MarkdownExport
from lore.core.markdown.render import escape, file_name
from lore.core.richtext.handlers import Node
from lore.modules.media import storage
from lore.modules.media.models import MediaItem
from lore.modules.media.service import Media


def _name(filename: str, mime: str) -> str:
    path = PurePosixPath(filename.replace("\\", "/")).name
    stem, dot, suffix = path.rpartition(".")
    if not dot or not stem:
        stem, suffix = path, (mimetypes.guess_extension(mime) or "").lstrip(".")
    suffix = "".join(c for c in suffix if c.isalnum())[:10].lower()
    return f"{file_name(stem)}.{suffix}" if suffix else file_name(stem)


def export_media(export: MarkdownExport) -> None:
    session = export.context.session
    visible = Media(export.context, export.policy).visible_conditions()
    rows = session.execute(
        select(MediaItem.id, MediaItem.sha256, MediaItem.filename, MediaItem.mime)
        .where(MediaItem.deleted_at.is_(None), *visible)
        .order_by(MediaItem.created_at, MediaItem.id)
    ).all()
    source = export.context.vault.info.path
    paths: dict[str, str] = {}
    for media_id, sha256, filename, mime in rows:
        original = storage.file_path(source, sha256)
        if not original.is_file():
            continue
        path = export.claim(MEDIA_FOLDER, _name(filename, mime))
        export.sink.copy(path, original)
        paths[media_id] = path

    def image(node: Node) -> str:
        attrs = node.get("attrs") or {}
        path = paths.get(str(attrs.get("mediaId")))
        alt = str(attrs.get("alt") or "").replace("|", " ").replace("]", " ").strip()
        if path is None:
            return escape(alt)
        width = attrs.get("width")
        option = f"|{width}" if width else (f"|{alt}" if alt else "")
        embed = f"![[{path}{option}]]"
        caption = str(attrs.get("caption") or "").strip()
        return f"{embed}\n*{escape(caption)}*" if caption else embed

    def field_value(value: object) -> str | None:
        path = paths.get(str(value))
        return None if path is None else f"[[{path}]]"

    def cover(media_id: str) -> str | None:
        path = paths.get(media_id)
        return None if path is None else f"![[{path}]]"

    export.nodes["image"] = image
    export.field_values["media"] = field_value
    export.cover = cover


__all__ = ["export_media"]
