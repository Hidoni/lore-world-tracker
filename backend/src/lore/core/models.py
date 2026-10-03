"""The ORM metadata of the core: every core model module is imported here.

``lore db check`` and autogenerate compare migrations against this metadata, so a new core
model module must be added to ``load_metadata``. Module models are registered by the module
framework (#33).
"""

from sqlalchemy import MetaData


def load_metadata() -> MetaData:
    from lore.core.db.base import Base  # noqa: PLC0415
    from lore.core.vaults import meta  # noqa: F401, PLC0415

    return Base.metadata
