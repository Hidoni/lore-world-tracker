"""``VisibilityPolicy``: what a request may see (``visibility-and-sharing.md`` §1-§3).

One policy is constructed per request (``lore.core.api.deps.PolicyDep``): ``AUTHOR`` sees
everything; ``READER`` (a read-only server, or ``?as_reader=true``) never sees private content,
not even indirectly. Query helpers take the policy and add its SQL conditions; only rich text is
filtered in Python (``filter_richtext``).

Reader rules (decided 2026-10-04 where noted):

- An entity is visible when it isn't private, isn't in the trash (the trash is author-only,
  decided), and its home dimension and origin timeline (if any) are visible too. A visible entity
  whose parent is hidden is shown as a root: its ``parent_id`` is removed (decided).
- Aliases, links and module rows need their own visibility not to be private; links (and module
  rows) also need every entity they reference to be visible, including their timeline.
- A field value is hidden when the field's effective visibility (the entity's override, else the
  field's ``default_visibility``) is private; ``rich_text`` values are filtered like bodies.
- History, the trash and consistency findings are author-only (``require_author``).
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import ColumnElement, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from lore.core.db.base import Visibility
from lore.core.entities.models import Entity
from lore.core.errors import NotFoundError
from lore.core.registry.types import FieldDef
from lore.core.richtext.extract import filter_for_reader
from lore.core.richtext.handlers import Node, RichTextNodeHandler
from lore.core.visibility.filters import VisibilityFilter

PRIVATE: Visibility = "private"
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Bound on the ids sent in one IN (...) (SQLite's default variable limit is 32766).
_ID_BATCH = 10_000

type EntityTable = Any  # Entity or an aliased(Entity)
type Conditions = list[ColumnElement[bool]]


def _ids_in(doc: Any, found: set[str]) -> None:
    """Every id-shaped string anywhere in a document (mark and node attributes, module nodes)."""
    if isinstance(doc, str):
        found.update(_ID.findall(doc))
    elif isinstance(doc, Mapping):
        for value in doc.values():
            _ids_in(value, found)
    elif isinstance(doc, list):
        for value in doc:
            _ids_in(value, found)


class VisibilityPolicy:
    """The author policy; ``ReaderPolicy`` overrides every hook. Methods returning conditions
    return lists to splat into ``where(...)`` (empty: no restriction)."""

    reader: bool = False

    # --- SQL conditions -------------------------------------------------------------------------

    def entities(self, e: EntityTable) -> Conditions:
        """Conditions for an entity row (``Entity`` or an alias) to be visible."""
        return []

    def entity_ref(self, column: Any) -> Conditions:
        """Conditions for a (nullable) column holding an entity id: NULL, or a visible entity."""
        return []

    def rows(self, row: Any) -> Conditions:
        """Conditions on a row's own ``visibility`` column (aliases, links, module rows)."""
        return []

    def links(self, link: Any) -> Conditions:
        """Conditions for a link row: its own visibility, both ends and its timeline."""
        return []

    def field(self, entity: EntityTable, field: FieldDef) -> Conditions:
        """Conditions for an entity's value of ``field`` to be visible."""
        return []

    def module_rows(self, spec: VisibilityFilter, row: Any = None) -> Conditions:
        """Conditions for a module table's row (``row``: the model or an alias of it)."""
        return []

    # --- Python-side checks ---------------------------------------------------------------------

    def require_author(self, detail: str) -> None:
        """``404 not_found`` for readers: for author-only resources (history, the trash)."""

    def shows(self, visibility: str) -> bool:
        return True

    def field_level(self, field: FieldDef, overrides: Mapping[str, Any]) -> str:
        return str(overrides.get(field.key, field.default_visibility))

    def visible_ids(self, session: Session, ids: Iterable[str | None]) -> frozenset[str]:
        """The ids (of ``ids``) of entities this policy shows."""
        return frozenset(i for i in ids if i is not None)

    def filter_richtext(
        self,
        session: Session,
        doc: Node | None,
        handlers: Mapping[str, RichTextNodeHandler] | None = None,
    ) -> Node | None:
        """A rich-text document as this policy may see it."""
        return doc

    def fields(
        self,
        session: Session,
        active: Mapping[str, FieldDef],
        values: Mapping[str, Any],
        overrides: Mapping[str, Any],
        handlers: Mapping[str, RichTextNodeHandler] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """An entity's active field values and visibility overrides, as this policy may see
        them."""
        return (
            {key: value for key, value in values.items() if key in active},
            {key: value for key, value in overrides.items() if key in active},
        )


class AuthorPolicy(VisibilityPolicy):
    """Sees everything."""


class ReaderPolicy(VisibilityPolicy):
    reader = True

    def entities(self, e: EntityTable) -> Conditions:
        dimension = aliased(Entity)
        timeline = aliased(Entity)
        return [
            e.visibility != PRIVATE,
            e.deleted_at.is_(None),
            or_(
                e.dimension_id.is_(None),
                exists().where(dimension.id == e.dimension_id, *self._own(dimension)),
            ),
            or_(
                e.origin_timeline_id.is_(None),
                exists().where(timeline.id == e.origin_timeline_id, *self._own(timeline)),
            ),
        ]

    @staticmethod
    def _own(e: EntityTable) -> Conditions:
        return [e.visibility != PRIVATE, e.deleted_at.is_(None)]

    def entity_ref(self, column: Any) -> Conditions:
        target = aliased(Entity)
        return [or_(column.is_(None), exists().where(target.id == column, *self.entities(target)))]

    def rows(self, row: Any) -> Conditions:
        return [row.visibility != PRIVATE]

    def links(self, link: Any) -> Conditions:
        return [
            *self.rows(link),
            *self.entity_ref(link.source_id),
            *self.entity_ref(link.target_id),
            *self.entity_ref(link.timeline_id),
        ]

    def field(self, entity: EntityTable, field: FieldDef) -> Conditions:
        override = entity.field_visibility[field.key].as_string()
        return [func.coalesce(override, literal(field.default_visibility)) != PRIVATE]

    def module_rows(self, spec: VisibilityFilter, row: Any = None) -> Conditions:
        table = spec.model if row is None else row
        conditions: Conditions = []
        if spec.visibility_column is not None:
            conditions.append(getattr(table, spec.visibility_column) != PRIVATE)
        for column in spec.entity_columns:
            conditions.extend(self.entity_ref(getattr(table, column)))
        return conditions

    def require_author(self, detail: str) -> None:
        raise NotFoundError(detail)

    def shows(self, visibility: str) -> bool:
        return visibility != PRIVATE

    def visible_ids(self, session: Session, ids: Iterable[str | None]) -> frozenset[str]:
        wanted = sorted({i for i in ids if i is not None})
        visible: set[str] = set()
        for start in range(0, len(wanted), _ID_BATCH):
            batch = wanted[start : start + _ID_BATCH]
            visible.update(
                session.scalars(
                    select(Entity.id).where(Entity.id.in_(batch), *self.entities(Entity))
                )
            )
        return frozenset(visible)

    def filter_richtext(
        self,
        session: Session,
        doc: Node | None,
        handlers: Mapping[str, RichTextNodeHandler] | None = None,
    ) -> Node | None:
        if doc is None:
            return None
        referenced: set[str] = set()
        _ids_in(doc, referenced)
        return filter_for_reader(doc, self.visible_ids(session, referenced), handlers)

    def fields(
        self,
        session: Session,
        active: Mapping[str, FieldDef],
        values: Mapping[str, Any],
        overrides: Mapping[str, Any],
        handlers: Mapping[str, RichTextNodeHandler] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        shown = {
            key for key, field in active.items() if self.shows(self.field_level(field, overrides))
        }
        result: dict[str, Any] = {}
        for key, value in values.items():
            if key not in shown:
                continue
            rich = active[key].type == "rich_text" and isinstance(value, dict)
            result[key] = self.filter_richtext(session, value, handlers) if rich else value
        return result, {key: value for key, value in overrides.items() if key in shown}


AUTHOR: VisibilityPolicy = AuthorPolicy()
READER: VisibilityPolicy = ReaderPolicy()
