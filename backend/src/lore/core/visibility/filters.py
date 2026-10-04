"""``VisibilityFilter``: how readers see a module table's rows (``modules.md`` §2.1).

A row is visible to readers when its own ``visibility`` column (if the table has one) isn't
``private`` and every entity it references through ``entity_columns`` is visible (effective
visibility, ``visibility-and-sharing.md`` §2). Module queries apply it with
``VisibilityPolicy.module_rows``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VisibilityFilter:
    model: type  # one of the module's ``models``
    # The row's own visibility column; None for tables without one.
    visibility_column: str | None = "visibility"
    # Columns holding entity ids (nullable ones are fine: NULL references nothing).
    entity_columns: tuple[str, ...] = ()
