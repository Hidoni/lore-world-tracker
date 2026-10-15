"""The ``image`` rich-text node (``docs/modules/media.md``, Integration points): a block image of
a media item, ``{mediaId, alt, caption, width}``.

Readers keep the node: an image in a block they see is exactly what makes its item visible to
them (``media_refs``), so its file answers. Its text (alt and caption) is searchable."""

import re
from typing import Any

from lore.core.richtext.handlers import Node, RichTextNodeHandler

_ID = re.compile(r"^[0-9a-zA-Z][0-9a-zA-Z_-]{0,99}$")
MAX_TEXT = 2000
MAX_WIDTH = 4000


def _validate(attrs: dict[str, Any]) -> dict[str, Any]:
    unknown = set(attrs) - {"mediaId", "alt", "caption", "width"}
    if unknown:
        raise ValueError(f"unknown attributes: {', '.join(sorted(unknown))}")
    media_id = attrs.get("mediaId")
    if not isinstance(media_id, str) or not _ID.match(media_id):
        raise ValueError("mediaId must be an id")
    out: dict[str, Any] = {"mediaId": media_id}
    for name in ("alt", "caption"):
        value = attrs.get(name)
        if value is None:
            out[name] = ""
        elif not isinstance(value, str) or len(value) > MAX_TEXT:
            raise ValueError(f"{name} must be text of at most {MAX_TEXT} characters")
        else:
            out[name] = value
    width = attrs.get("width")
    if width is not None and (
        isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= MAX_WIDTH
    ):
        raise ValueError(f"width must be a number of pixels from 1 to {MAX_WIDTH}")
    out["width"] = width
    return out


def _text(node: Node) -> str:
    attrs = node.get("attrs") or {}
    return " ".join(str(attrs.get(k) or "") for k in ("alt", "caption")).strip()


IMAGE_NODE = RichTextNodeHandler(
    type="image",
    group="block",
    validate_attrs=_validate,
    extract_text=_text,
    ref_kind="media",
    extract_refs=lambda node: [str((node.get("attrs") or {}).get("mediaId", ""))],
)
