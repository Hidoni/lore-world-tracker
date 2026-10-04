"""Entity listings: filtered lists, the lazy navigation tree, children, the trash and field-value
suggestions (``api.md`` §2, Entities).

Every query starts from ``EntityQueries._shown``: the conditions an entity must meet to appear in
any listing (its kind's module is enabled, and the request's ``VisibilityPolicy`` shows it).
**Hook point:** the time cursor (``timeline``/``at`` existence filter, M3/M7) adds its conditions
there, so the endpoints' signatures don't change. Readers never see the trash; a visible entity
whose parent they can't see is listed with ``parent_id`` null (a root).

Pagination is keyset based (``api.md`` §1): the cursor holds the sort values of the last item, so
pages stay stable while entities are inserted or deleted.

Orders (decided 2026-10-04): names sort by ``entities.sort_name`` (case and accents ignored,
numbers by value); tree siblings sort by ``sort_key`` with manually ordered entities first, then
the rest by name. An entity whose parent the tree wouldn't show (trashed, module disabled,
filtered out by ``kinds`` or ``dimension``) is shown as a root.
"""

import base64
import binascii
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.orm import aliased

from lore.core.entities.models import (
    Entity,
    EntityAlias,
    EntityTag,
    entity_sort_name,
    fold_text,
)
from lore.core.entities.schemas import (
    EntityPage,
    EntitySummary,
    FieldValue,
    FieldValueList,
    TrashItem,
    TrashPage,
    TreeNode,
    TreePage,
)
from lore.core.entities.service import DIMENSION_KIND, EntityService
from lore.core.errors import InvalidInputError
from lore.core.modules.service import ModuleDisabledError

type EntityTable = Any  # Entity or an aliased(Entity)

MAX_SUGGESTIONS = 100


@dataclass(frozen=True)
class _Order:
    """A keyset order: the columns (ascending, or all descending) and how to read the same values
    from a loaded entity for the cursor."""

    columns: Callable[[EntityTable], list[ColumnElement[Any]]]
    values: Callable[[Entity], list[Any]]
    descending: bool = False
    datetimes: tuple[int, ...] = ()  # positions holding datetimes (ISO strings in the cursor)


def _manual_first(e: EntityTable) -> list[ColumnElement[Any]]:
    return [
        case((e.sort_key.is_(None), 1), else_=0),
        func.coalesce(e.sort_key, ""),
        e.sort_name,
        e.id,
    ]


ORDERS: dict[str, _Order] = {
    "name": _Order(lambda e: [e.sort_name, e.id], lambda e: [e.sort_name, e.id]),
    "created": _Order(lambda e: [e.created_at, e.id], lambda e: [e.created_at, e.id],
                      datetimes=(0,)),
    "updated": _Order(lambda e: [e.updated_at, e.id], lambda e: [e.updated_at, e.id],
                      datetimes=(0,)),
    "sort_key": _Order(
        _manual_first,
        lambda e: [1 if e.sort_key is None else 0, e.sort_key or "", e.sort_name, e.id],
    ),
    "deleted": _Order(lambda e: [e.deleted_at, e.id], lambda e: [e.deleted_at, e.id],
                      descending=True, datetimes=(0,)),
}  # fmt: skip


def _order(sort: str) -> _Order:
    if sort.startswith("-"):
        base = ORDERS[sort[1:]]
        return _Order(base.columns, base.values, not base.descending, base.datetimes)
    return ORDERS[sort]


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[{"path": path, "code": "invalid_value",
                                               "message": message}])  # fmt: skip


def _encode_cursor(sort: str, order: _Order, entity: Entity) -> str:
    values = [v.isoformat() if isinstance(v, datetime) else v for v in order.values(entity)]
    raw = json.dumps({"s": sort, "v": values}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(sort: str, order: _Order, cursor: str) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        values = data["v"]
        if data["s"] != sort or not isinstance(values, list):
            raise ValueError
        for index in order.datetimes:
            values[index] = datetime.fromisoformat(values[index])
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError) as exc:
        raise _invalid("cursor", "The cursor is invalid (or belongs to another sort).") from exc
    return values


def _like_prefix(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


class EntityQueries:
    def __init__(self, service: EntityService) -> None:
        self.service = service
        self.session = service.session
        self.policy = service.policy

    # --- shared conditions ----------------------------------------------------------------------

    def _shown(self, e: EntityTable) -> list[ColumnElement[bool]]:
        """What every listed entity must meet (see the module docstring: the hook point)."""
        return [e.kind.in_(self.service.kinds), *self.policy.entities(e)]

    def _kinds(self, e: EntityTable, kinds: Sequence[str] | None) -> list[ColumnElement[bool]]:
        if not kinds:
            return []
        unknown = [kind for kind in kinds if kind not in self.service.registry.all_kind_keys()]
        if unknown:
            raise _invalid("kind", f"Unknown kind {unknown[0]!r}.")
        return [e.kind.in_(kinds)]

    @staticmethod
    def _dimension(
        e: EntityTable, dimension: str | None, *, include_multiversal: bool = True
    ) -> list[ColumnElement[bool]]:
        if dimension is None:
            return []
        if not include_multiversal:
            return [e.dimension_id == dimension]
        multiversal = and_(e.dimension_id.is_(None), e.kind != DIMENSION_KIND)
        return [or_(e.dimension_id == dimension, multiversal)]

    def _page[T](
        self,
        statement: Select[Any],
        *,
        e: EntityTable,
        sort: str,
        cursor: str | None,
        limit: int,
        build: Callable[[list[Entity]], list[T]],
    ) -> tuple[list[T], str | None]:
        order = _order(sort)
        columns = order.columns(e)
        if cursor is not None:
            values = _decode_cursor(sort, order, cursor)
            if len(values) != len(columns):
                raise _invalid("cursor", "The cursor is invalid (or belongs to another sort).")
            bound = tuple_(*(literal(v, c.type) for c, v in zip(columns, values, strict=True)))
            key = tuple_(*columns)
            statement = statement.where(key < bound if order.descending else key > bound)
        ordering = [c.desc() for c in columns] if order.descending else columns
        rows = list(self.session.scalars(statement.order_by(*ordering).limit(limit + 1)))
        next_cursor = _encode_cursor(sort, order, rows[limit - 1]) if len(rows) > limit else None
        return build(rows[:limit]), next_cursor

    # --- lists ----------------------------------------------------------------------------------

    def list_entities(
        self,
        *,
        kinds: Sequence[str] | None = None,
        dimension: str | None = None,
        include_multiversal: bool = True,
        parent: str | None = None,
        tags: Sequence[str] | None = None,
        q: str | None = None,
        include_trashed: bool = False,
        sort: str = "name",
        cursor: str | None = None,
        limit: int = 50,
    ) -> EntityPage:
        e = Entity
        conditions = [
            *self._shown(e),
            *self._kinds(e, kinds),
            *self._dimension(e, dimension, include_multiversal=include_multiversal),
        ]
        if not include_trashed:
            conditions.append(e.deleted_at.is_(None))
        if parent is not None:
            conditions += [e.parent_id == parent, *self.policy.entity_ref(e.parent_id)]
        for tag_id in tags or ():
            conditions.append(
                exists().where(EntityTag.entity_id == e.id, EntityTag.tag_id == tag_id)
            )
        if q:
            # Until search (#39): a name/alias prefix, case-insensitive for ASCII only.
            pattern = _like_prefix(q)
            conditions.append(
                or_(
                    e.name.like(pattern, escape="\\"),
                    exists().where(
                        EntityAlias.entity_id == e.id,
                        EntityAlias.alias.like(pattern, escape="\\"),
                    ),
                )
            )
        items, next_cursor = self._page(
            select(e).where(*conditions),
            e=e,
            sort=sort,
            cursor=cursor,
            limit=limit,
            build=self._summaries,
        )
        return EntityPage(items=items, next_cursor=next_cursor)

    def trash(self, *, cursor: str | None = None, limit: int = 50) -> TrashPage:
        """Trashed entities, most recently trashed first (author-only)."""
        self.policy.require_author("The trash isn't available to readers.")
        statement = select(Entity).where(*self._shown(Entity), Entity.deleted_at.is_not(None))
        items, next_cursor = self._page(
            statement, e=Entity, sort="deleted", cursor=cursor, limit=limit, build=self._trash_items
        )
        return TrashPage(items=items, next_cursor=next_cursor)

    def _summaries(self, entities: list[Entity]) -> list[EntitySummary]:
        parents = self._visible_parents(entities)
        return [self._summary(entity, parents) for entity in entities]

    def _visible_parents(self, entities: Sequence[Entity]) -> frozenset[str]:
        return self.policy.visible_ids(self.session, (e.parent_id for e in entities))

    def _summary(self, entity: Entity, parents: frozenset[str]) -> EntitySummary:
        kind_fields = self.service.kind_fields(self.service.kinds[entity.kind])
        fields, _ = self.policy.fields(
            self.session,
            kind_fields.active,
            entity.fields,
            entity.field_visibility,
            self.service.richtext,
        )
        return EntitySummary(
            id=entity.id,
            kind=entity.kind,
            dimension_id=entity.dimension_id,
            parent_id=entity.parent_id if entity.parent_id in parents else None,
            name=entity.name,
            slug=entity.slug,
            summary=entity.summary,
            fields=fields,
            visibility=entity.visibility,
            icon=entity.icon,
            color=entity.color,
            sort_key=entity.sort_key,
            revision=entity.revision,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )

    def _trash_items(self, entities: list[Entity]) -> list[TrashItem]:
        child = aliased(Entity)
        counts: dict[str | None, int] = dict(
            self.session.execute(
                select(child.parent_id, func.count())
                .where(
                    child.parent_id.in_([e.id for e in entities]),
                    child.deleted_at.is_(None),
                    *self._shown(child),
                )
                .group_by(child.parent_id)
            ).all()
        )
        parents = self._visible_parents(entities)
        return [
            TrashItem(**self._summary(e, parents).model_dump(), orphan_count=counts.get(e.id, 0))
            for e in entities
        ]

    # --- tree and children ----------------------------------------------------------------------

    def _in_tree(
        self, e: EntityTable, dimension: str | None, kinds: Sequence[str] | None
    ) -> list[ColumnElement[bool]]:
        return [
            *self._shown(e),
            e.deleted_at.is_(None),
            *self._kinds(e, kinds),
            *self._dimension(e, dimension),
        ]

    def tree(
        self,
        *,
        dimension: str | None = None,
        parent: str | None = None,
        kinds: Sequence[str] | None = None,
        cursor: str | None = None,
        limit: int = 200,
    ) -> TreePage:
        """One level of the navigation tree: the roots, or the children of ``parent``.
        Multiversal entities appear in every dimension (``frontend.md`` §3)."""
        e = Entity
        conditions = self._in_tree(e, dimension, kinds)
        if parent is not None:
            conditions += [e.parent_id == parent, *self.policy.entity_ref(e.parent_id)]
        else:
            shown_parent = aliased(Entity)
            conditions.append(
                or_(
                    e.parent_id.is_(None),
                    ~exists().where(
                        shown_parent.id == e.parent_id,
                        *self._in_tree(shown_parent, dimension, kinds),
                    ),
                )
            )
        items, next_cursor = self._page(
            select(e).where(*conditions),
            e=e,
            sort="sort_key",
            cursor=cursor,
            limit=limit,
            build=lambda rows: self._nodes(rows, dimension, kinds),
        )
        return TreePage(items=items, next_cursor=next_cursor)

    def children(
        self,
        entity_id: str,
        *,
        kinds: Sequence[str] | None = None,
        cursor: str | None = None,
        limit: int = 200,
    ) -> TreePage:
        """The children of an entity (every dimension), sorted like the tree."""
        self.service.load_visible(entity_id)  # 404 not_found / module_disabled
        e = Entity
        conditions = [*self._in_tree(e, None, kinds), e.parent_id == entity_id]
        items, next_cursor = self._page(
            select(e).where(*conditions),
            e=e,
            sort="sort_key",
            cursor=cursor,
            limit=limit,
            build=lambda rows: self._nodes(rows, None, kinds),
        )
        return TreePage(items=items, next_cursor=next_cursor)

    def _nodes(
        self, entities: list[Entity], dimension: str | None, kinds: Sequence[str] | None
    ) -> list[TreeNode]:
        child = aliased(Entity)
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        rows = self.session.execute(
            select(child.parent_id, child.kind, func.count())
            .where(child.parent_id.in_([e.id for e in entities]),
                   *self._in_tree(child, dimension, kinds))
            .group_by(child.parent_id, child.kind)
            .order_by(child.kind)
        )  # fmt: skip
        for parent_id, kind, count in rows:
            counts[str(parent_id)][kind] = count
        parents = self._visible_parents(entities)
        return [
            TreeNode(
                id=e.id,
                kind=e.kind,
                name=e.name,
                icon=e.icon,
                color=e.color,
                dimension_id=e.dimension_id,
                parent_id=e.parent_id if e.parent_id in parents else None,
                multiversal=e.dimension_id is None and e.kind != DIMENSION_KIND,
                visibility=e.visibility,
                sort_key=e.sort_key,
                has_children=bool(counts.get(e.id)),
                child_counts=counts.get(e.id, {}),
            )
            for e in entities
        ]

    # --- field values ---------------------------------------------------------------------------

    def field_values(
        self, *, kind: str, field: str, q: str | None = None, limit: int = 20
    ) -> FieldValueList:
        """Distinct values of a ``text`` field among the kind's entities (not in the trash), for
        autocomplete. Case/accent variants are merged (decided 2026-10-04)."""
        registered = self.service.kinds.get(kind)
        if registered is None:
            if kind in self.service.registry.all_kind_keys():
                raise ModuleDisabledError(f"The module of kind {kind!r} is disabled.")
            raise _invalid("kind", f"Unknown kind {kind!r}.")
        definition = self.service.kind_fields(registered).active.get(field)
        if definition is None or definition.type != "text":
            raise _invalid("field", f"{field!r} is not a text field of this kind.")

        path = f'$."{field}"'  # field keys match ^[a-z][a-z0-9_.]*$: nothing to escape
        conditions = [
            *self._shown(Entity),
            *self.policy.field(Entity, definition),
            Entity.kind == kind,
            Entity.deleted_at.is_(None),
        ]
        if definition.multiple:
            values = func.json_each(Entity.fields, path).table_valued("value", "type")
            statement = (
                select(values.c.value, func.count())
                .select_from(Entity)
                .join(values, true())
                .where(*conditions, values.c.type == "text")
                .group_by(values.c.value)
            )
        else:
            value = func.json_extract(Entity.fields, path)
            statement = (
                select(value, func.count())
                .where(*conditions, func.json_type(Entity.fields, path) == "text")
                .group_by(value)
            )

        spellings: dict[str, Counter[str]] = defaultdict(Counter)
        for text, count in self.session.execute(statement):
            spelling = str(text).strip()
            if spelling:
                spellings[fold_text(spelling)][spelling] += count
        prefix = fold_text(q.strip()) if q else ""
        merged = [
            FieldValue(
                value=min(counter, key=lambda s: (-counter[s], entity_sort_name(s), s)),
                count=sum(counter.values()),
            )
            for key, counter in spellings.items()
            if key.startswith(prefix)
        ]
        merged.sort(key=lambda item: (-item.count, entity_sort_name(item.value), item.value))
        return FieldValueList(items=merged[:limit])
