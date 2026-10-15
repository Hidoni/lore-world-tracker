"""The ``media`` field type (``docs/modules/media.md``): a media item id (a list of ids for a
``multiple`` field). Ids are checked for their shape here; ids of items that don't exist make no
reference (``lore.modules.media.refs``) and render as missing images."""

import re
from typing import Any

from lore.core.registry.types import FieldDef, FieldTypeDef

_ID = re.compile(r"^[0-9a-zA-Z][0-9a-zA-Z_-]{0,99}$")
MAX_ITEMS = 500


def _one(value: Any) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ValueError("must be a media item id")
    return value


def _validate(value: Any, field: FieldDef) -> Any:
    if not field.multiple:
        return _one(value)
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"must be a list of at most {MAX_ITEMS} media item ids")
    return [_one(item) for item in value]


MEDIA_FIELD_TYPE = FieldTypeDef(
    key="media",
    label="Image",
    description="An image or file from the vault's media library.",
    validate=_validate,
)
