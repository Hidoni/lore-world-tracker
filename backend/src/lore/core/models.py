"""The ORM metadata of the core: every core model module is imported here.

``lore db check`` and autogenerate compare migrations against this metadata, so a new core
model module must be added to ``load_metadata``. Module models are registered by the module
framework (#33).
"""

from sqlalchemy import MetaData


def load_metadata() -> MetaData:
    from lore.core.consistency import models as _consistency  # noqa: F401, PLC0415
    from lore.core.db.base import Base  # noqa: PLC0415
    from lore.core.entities import models as _entities  # noqa: F401, PLC0415
    from lore.core.history import models as _history  # noqa: F401, PLC0415
    from lore.core.links import models as _links  # noqa: F401, PLC0415
    from lore.core.richtext import models as _richtext  # noqa: F401, PLC0415
    from lore.core.search import models as _search  # noqa: F401, PLC0415
    from lore.core.time import models as _time  # noqa: F401, PLC0415
    from lore.core.vaults import meta as _meta  # noqa: F401, PLC0415

    return Base.metadata
