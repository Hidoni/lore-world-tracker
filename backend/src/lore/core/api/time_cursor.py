"""The time cursor's query parameters (``time-model.md`` §10.6, ``api.md`` §2): ``timeline`` and
``at`` (a moment or ``present``), shared by every read that can be asked "as of t"."""

from typing import Annotated

from fastapi import Query

from lore.core.entities.schemas import AT_PATTERN, ID_PATTERN

TimelineQuery = Annotated[
    str | None,
    Query(pattern=ID_PATTERN, description="The time cursor's timeline (with `at`)."),
]
AtQuery = Annotated[
    str | None,
    Query(
        pattern=AT_PATTERN,
        max_length=1000,
        description="The time cursor: a moment, or `present` (the timeline's dimension's).",
    ),
]

__all__ = ["AT_PATTERN", "AtQuery", "TimelineQuery"]
