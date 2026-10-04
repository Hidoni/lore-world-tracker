"""The link service: create, update and trash typed links, and list an entity's links
(``data-model.md`` §6.1-§6.2, ``time-model.md`` §10.3).

Rules (decided 2026-10-04 where noted):

- The type must be offered (``LinkTypeCatalog``) and not archived; source and target kinds must
  fit it (``422 link_type_not_allowed``). Endpoints must exist, not be in the trash and be of
  available kinds. An entity can't link to itself (decided).
- Symmetric types are stored once with ``source_id < target_id``.
- Validity: ``temporal: never`` refuses bounds, ``required`` needs at least one. A link with bounds
  needs a ``timeline_id``; a timeless link has none. Bounds are stored as time-point specs and
  resolved (``*_t``, ``time_status``) by #102.
- Uniqueness and cardinality (``409 conflict``): ``per_pair`` counts every link of the pair.
  ``per_pair_per_period`` and ``max_*`` limits only count timeless links until validity periods
  resolve in #102 (decided): links with bounds are always accepted meanwhile.
- ``data`` must match the type's ``data_schema`` (JSON Schema draft 2020-12).
- Trashed links, links of types that aren't offered and links whose other end is trashed (unless
  asked for) or of an unavailable kind are hidden from entity link lists.
- Reads apply the request's ``VisibilityPolicy``: readers only see visible links between visible
  entities, and mention counts of private blocks are never reported to them.
"""

from collections.abc import Callable, Sequence
from typing import Any, Literal

from jsonschema import Draft202012Validator
from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity
from lore.core.errors import (
    ConflictError,
    ErrorItem,
    InvalidInputError,
    LoreError,
    NotFoundError,
)
from lore.core.links.catalog import LinkTypeCatalog, LinkTypeInfo, allows
from lore.core.links.models import Link
from lore.core.links.schemas import (
    Backlink,
    Backlinks,
    EntityLink,
    EntityLinks,
    LinkCreate,
    LinkDeleteResult,
    LinkedEntity,
    LinkOut,
    LinkUpdate,
    LinkWriteResult,
    MentionCountsOut,
)
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import ModuleDisabledError, enabled_modules
from lore.core.richtext.models import Mention
from lore.core.types import Affected
from lore.core.visibility import AUTHOR, VisibilityPolicy

TIMELINE_KIND = "timeline"


class LinkTypeNotAllowedError(InvalidInputError):
    code = "link_type_not_allowed"
    title = "Link type not allowed"


def _error(path: str, message: str, code: str = "invalid_value") -> ErrorItem:
    return {"path": path, "code": code, "message": message}


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[_error(path, message)])


def data_errors(schema: dict[str, Any] | None, data: Any, prefix: str = "data") -> list[ErrorItem]:
    """Where ``data`` breaks the JSON Schema (none without a schema)."""
    if schema is None:
        return []
    return [
        _error(".".join([prefix, *(str(part) for part in error.absolute_path)]), error.message)
        for error in Draft202012Validator(schema).iter_errors(data)
    ]


def link_out(link: Link) -> LinkOut:
    return LinkOut(
        id=link.id,
        link_type=link.link_type,
        source_id=link.source_id,
        target_id=link.target_id,
        role=link.role,
        data=link.data,
        visibility=link.visibility,
        timeline_id=link.timeline_id,
        valid_from=link.valid_from_spec,
        valid_to=link.valid_to_spec,
        time_status=link.time_status,
        sort_key=link.sort_key,
        revision=link.revision,
        created_at=link.created_at,
        updated_at=link.updated_at,
        deleted_at=link.deleted_at,
    )


def _linked(entity: Entity) -> LinkedEntity:
    return LinkedEntity(
        id=entity.id,
        kind=entity.kind,
        name=entity.name,
        icon=entity.icon,
        color=entity.color,
        dimension_id=entity.dimension_id,
        deleted_at=entity.deleted_at,
    )


def timeless(link: type[Link] | Any) -> ColumnElement[bool]:
    """A link without validity bounds has no timeline (``time-model.md`` §10.1)."""
    result: ColumnElement[bool] = link.timeline_id.is_(None)
    return result


class LinkService:
    def __init__(
        self, session: Session, registry: ModuleRegistry, policy: VisibilityPolicy = AUTHOR
    ) -> None:
        self.session = session
        self.registry = registry
        self.policy = policy  # applied by reads; writes are author-only
        enabled = enabled_modules(session, registry)
        self.kinds = {kind.key for kind in registry.kinds_for(enabled)}
        self.catalog = LinkTypeCatalog(session, registry, enabled)

    # --- writes ---------------------------------------------------------------------------------

    def create(self, data: LinkCreate) -> LinkWriteResult:
        link = self.add(data)
        return LinkWriteResult(link=link_out(link), affected=self.affected([link]))

    def add(self, data: LinkCreate) -> Link:
        """Validate and insert a link (flushed). Used by ``POST /links`` and entity writes."""
        info = self._offered_type(data.link_type)
        if info.definition.archived:
            raise LinkTypeNotAllowedError(
                f"The link type {info.definition.label!r} is archived: new links can't use it."
            )
        source = self._endpoint(data.source_id, "source_id")
        target = self._endpoint(data.target_id, "target_id")
        if source.id == target.id:
            raise _invalid("target_id", "An entity can't be linked to itself.")
        self._check_kinds(info, source, target)
        if info.definition.symmetric and target.id < source.id:
            source, target = target, source
        link = Link(
            id=new_id(),
            link_type=info.key,
            source_id=source.id,
            target_id=target.id,
            visibility=data.visibility,
            sort_key=data.sort_key,
        )
        self._apply(link, info, data, set(data.model_fields_set) | {"data"})
        self._check_limits(info, link)
        self.session.add(link)
        self.session.flush()
        return link

    def update(self, link_id: str, data: LinkUpdate) -> LinkWriteResult:
        link, info = self._load(link_id)
        if link.deleted_at is not None:
            raise ConflictError("The link is in the trash.")
        if data.revision != link.revision:
            raise RevisionConflictError(
                f"The link was changed meanwhile (revision {link.revision}, the edit is based "
                f"on {data.revision}).",
                context={"current": link_out(link).model_dump(mode="json")},
            )
        sent = data.model_fields_set - {"revision"}
        if sent:
            link.updated_at = utc_now()  # first: one UPDATE even if a query autoflushes
        if "visibility" in sent:
            if data.visibility is None:
                raise _invalid("visibility", "Visibility must be public, spoiler or private.")
            link.visibility = data.visibility
        if "sort_key" in sent:
            link.sort_key = data.sort_key
        self._apply(link, info, data, sent)
        self._check_limits(info, link)
        self.session.flush()
        return LinkWriteResult(link=link_out(link), affected=self.affected([link]))

    def trash(self, link_id: str) -> LinkDeleteResult:
        """Move to the trash (idempotent)."""
        link, _info = self._load(link_id)
        if link.deleted_at is None:
            link.deleted_at = utc_now()
            self.session.flush()
        return LinkDeleteResult(id=link.id, link=link_out(link), affected=self.affected([link]))

    def trash_for_entity(self, entity_id: str, link_ids: Sequence[str]) -> list[Link]:
        """Trash links of an entity (``links_remove`` of an entity write)."""
        links: list[Link] = []
        errors: list[ErrorItem] = []
        for index, link_id in enumerate(link_ids):
            link = self.session.get(Link, link_id)
            if link is None or entity_id not in (link.source_id, link.target_id):
                errors.append(_error(f"links_remove.{index}", "not a link of this entity"))
            elif link.deleted_at is None:
                link.deleted_at = utc_now()
                links.append(link)
        if errors:
            raise InvalidInputError("Some links can't be removed.", errors=errors)
        self.session.flush()
        return links

    def affected(self, links: Sequence[Link]) -> Affected:
        ids = list(dict.fromkeys(i for link in links for i in (link.source_id, link.target_id)))
        dimensions = self.session.scalars(
            select(Entity.dimension_id).where(Entity.id.in_(ids), Entity.dimension_id.is_not(None))
        )
        return Affected(
            entities=ids,
            dimensions=sorted({d for d in dimensions if d is not None}),
            time_changed=False,  # validity resolution arrives with #102
            search_changed=False,
        )

    # --- reads ----------------------------------------------------------------------------------

    def entity_links(
        self,
        entity_id: str,
        *,
        direction: Literal["out", "in", "both"] = "both",
        types: Sequence[str] | None = None,
        include_trashed: bool = False,
    ) -> EntityLinks:
        """The entity's links, by type, then manual order, then the other end's name.
        ``include_trashed`` also lists links whose other end is in the trash (never for readers).
        Hook point: the time cursor (#102) adds conditions here."""
        entity = self.session.get(Entity, entity_id)
        if entity is None or not self.policy.visible_ids(self.session, [entity_id]):
            raise NotFoundError(f"No entity {entity_id}.")
        if entity.kind not in self.kinds:
            raise ModuleDisabledError(f"The module of kind {entity.kind!r} is disabled.")
        offered = {info.key: info for info in self.catalog.offered()}
        symmetric = [key for key, info in offered.items() if info.definition.symmetric]
        other = aliased(Entity)
        other_id = case((Link.source_id == entity_id, Link.target_id), else_=Link.source_id)
        conditions = [
            Link.deleted_at.is_(None),
            Link.link_type.in_(offered),
            or_(Link.source_id == entity_id, Link.target_id == entity_id),
            other.kind.in_(self.kinds),
            *self.policy.links(Link),
            *self.policy.entities(other),
        ]
        if not include_trashed:
            conditions.append(other.deleted_at.is_(None))
        if types:
            conditions.append(Link.link_type.in_(types))
        if direction == "out":
            conditions.append(or_(Link.source_id == entity_id, Link.link_type.in_(symmetric)))
        elif direction == "in":
            conditions.append(or_(Link.target_id == entity_id, Link.link_type.in_(symmetric)))
        rows = self.session.execute(
            select(Link, other)
            .join(other, other.id == other_id)
            .where(*conditions)
            .order_by(
                Link.link_type,
                case((Link.sort_key.is_(None), 1), else_=0),
                func.coalesce(Link.sort_key, ""),
                other.sort_name,
                Link.id,
            )
        ).all()
        items = []
        for link, end in rows:
            definition = offered[link.link_type].definition
            if definition.symmetric:
                side: Literal["out", "in", "both"] = "both"
                label = definition.label
            elif link.source_id == entity_id:
                side, label = "out", definition.label
            else:
                side, label = "in", definition.inverse_label or definition.label
            items.append(
                EntityLink(
                    link=link_out(link),
                    direction=side,
                    label=label,
                    other=_linked(end),
                )
            )
        return EntityLinks(items=items)

    def stored_problems(self, link: Link) -> list[str]:
        """Rules a stored link (not trashed) breaks (used to vet an undo): its type, the kinds of
        its ends, validity, uniqueness and cardinality. Trashed ends are allowed states."""
        info = self.catalog.get(link.link_type)
        if info is None:
            if self.catalog.is_known(link.link_type):
                return []  # a disabled module's links are kept as they are
            return [f"The link type {link.link_type!r} no longer exists."]
        source = self.session.get(Entity, link.source_id)
        target = self.session.get(Entity, link.target_id)
        problems: list[str] = []
        checks: list[Callable[[], None]] = [
            lambda: self._check_validity(info, link),
            lambda: self._check_limits(info, link),
        ]
        if source is not None and target is not None:
            checks.insert(0, lambda: self._check_kinds(info, source, target))
        for check in checks:
            try:
                check()
            except LoreError as exc:
                problems.append(exc.detail)
        return problems

    def backlinks(self, entity_id: str, *, include_trashed: bool = False) -> Backlinks:
        """Entities pointing at this one through incoming links (and symmetric ones) or mentions
        in their text, by name (decided 2026-10-04). Self-mentions aren't recorded."""
        incoming = self.entity_links(entity_id, direction="in", include_trashed=include_trashed)
        source = aliased(Entity)
        conditions = [
            Mention.target_entity_id == entity_id,
            Mention.source_entity_id != entity_id,
            source.kind.in_(self.kinds),
            *self.policy.entities(source),
        ]
        if not include_trashed:
            conditions.append(source.deleted_at.is_(None))
        mentioned = self.session.execute(
            select(Mention, source)
            .join(source, source.id == Mention.source_entity_id)
            .where(*conditions)
        ).all()
        by_source: dict[str, Backlink] = {}
        for item in incoming.items:
            entry = by_source.setdefault(
                item.other.id,
                Backlink(
                    entity=item.other,
                    links=[],
                    mentions=MentionCountsOut(public=0, spoiler=0, private=0),
                ),
            )
            entry.links.append(item)
        for mention, end in mentioned:
            counts = MentionCountsOut(
                public=mention.count_public,
                spoiler=mention.count_spoiler,
                private=mention.count_private if self.policy.shows("private") else 0,
            )
            if counts.public + counts.spoiler + counts.private == 0:
                continue  # only private mentions, hidden from this policy
            entry = by_source.setdefault(
                end.id,
                Backlink(
                    entity=_linked(end),
                    links=[],
                    mentions=MentionCountsOut(public=0, spoiler=0, private=0),
                ),
            )
            entry.mentions = counts
        sort_names = dict(
            self.session.execute(
                select(Entity.id, Entity.sort_name).where(Entity.id.in_(list(by_source)))
            ).all()
        )
        ordered = sorted(by_source.values(), key=lambda b: (sort_names[b.entity.id], b.entity.id))
        return Backlinks(items=ordered)

    # --- rules ----------------------------------------------------------------------------------

    def _offered_type(self, key: str) -> LinkTypeInfo:
        info = self.catalog.get(key)
        if info is not None:
            return info
        if self.catalog.is_known(key):
            raise ModuleDisabledError(
                f"The link type {key!r} is unavailable: a module it needs is disabled."
            )
        raise _invalid("link_type", f"Unknown link type {key!r}.")

    def _load(self, link_id: str) -> tuple[Link, LinkTypeInfo]:
        link = self.session.get(Link, link_id)
        if link is None:
            raise NotFoundError(f"No link {link_id}.")
        info = self.catalog.get(link.link_type)
        ends = self.session.scalars(
            select(Entity.kind).where(Entity.id.in_([link.source_id, link.target_id]))
        )
        if info is None or any(kind not in self.kinds for kind in ends):
            raise ModuleDisabledError("The link is unavailable: a module it needs is disabled.")
        return link, info

    def _endpoint(self, entity_id: str, path: str) -> Entity:
        entity = self.session.get(Entity, entity_id)
        if entity is None or entity.kind not in self.kinds:
            raise _invalid(path, f"No entity {entity_id}.")
        if entity.deleted_at is not None:
            raise _invalid(path, "The entity is in the trash.")
        return entity

    def _check_kinds(self, info: LinkTypeInfo, source: Entity, target: Entity) -> None:
        definition = info.definition
        fits = allows(definition.source_kinds, source.kind) and allows(
            definition.target_kinds, target.kind
        )
        if not fits and definition.symmetric:
            fits = allows(definition.source_kinds, target.kind) and allows(
                definition.target_kinds, source.kind
            )
        if not fits:
            raise LinkTypeNotAllowedError(
                f"A {definition.label!r} link can't connect a {source.kind} to a {target.kind}."
            )

    def _apply(
        self,
        link: Link,
        info: LinkTypeInfo,
        data: LinkCreate | LinkUpdate,
        sent: set[str],
    ) -> None:
        """Role, data and validity (shared by create and update)."""
        if "role" in sent:
            link.role = data.role
        if "data" in sent:
            if data.data is None:
                raise _invalid("data", "data must be an object.")
            errors = data_errors(info.definition.data_schema, data.data)
            if errors:
                raise InvalidInputError("The link data doesn't match its type.", errors=errors)
            link.data = data.data
        if "valid_from" in sent:
            link.valid_from_spec = (
                data.valid_from.model_dump(mode="json") if data.valid_from else None
            )
        if "valid_to" in sent:
            link.valid_to_spec = data.valid_to.model_dump(mode="json") if data.valid_to else None
        if "timeline_id" in sent:
            link.timeline_id = data.timeline_id
        self._check_validity(info, link)

    def _check_validity(self, info: LinkTypeInfo, link: Link) -> None:
        bounded = link.valid_from_spec is not None or link.valid_to_spec is not None
        temporal = info.definition.temporal
        if bounded and temporal == "never":
            raise _invalid("valid_from", f"{info.definition.label!r} links are timeless.")
        if not bounded and temporal == "required":
            raise _invalid("valid_from", f"{info.definition.label!r} links need a validity bound.")
        if bounded and link.timeline_id is None:
            raise _invalid("timeline_id", "A link with validity bounds needs a timeline.")
        if not bounded and link.timeline_id is not None:
            raise _invalid("timeline_id", "A timeless link has no timeline.")
        if link.timeline_id is not None:
            timeline = self.session.get(Entity, link.timeline_id)
            if timeline is None or timeline.kind != TIMELINE_KIND:
                raise _invalid("timeline_id", "The timeline must be a timeline.")
            if timeline.deleted_at is not None:
                raise _invalid("timeline_id", "The timeline is in the trash.")

    def _check_limits(self, info: LinkTypeInfo, link: Link) -> None:
        definition = info.definition
        others = select(Link.id).where(
            Link.link_type == link.link_type, Link.deleted_at.is_(None), Link.id != link.id
        )
        is_timeless = link.timeline_id is None
        if definition.unique == "per_pair" or (
            definition.unique == "per_pair_per_period" and is_timeless
        ):
            pair = others.where(Link.source_id == link.source_id, Link.target_id == link.target_id)
            if definition.unique == "per_pair_per_period":
                pair = pair.where(timeless(Link))
            existing = list(self.session.scalars(pair))
            if existing:
                raise ConflictError(
                    f"These entities already have a {definition.label!r} link.",
                    context={"links": existing},
                )
        if not is_timeless:
            return  # max_* limits count timeless links only until #102 (decided 2026-10-04)
        limits = (
            (
                "max_targets_per_source",
                definition.max_targets_per_source,
                link.source_id,
                Link.source_id,
            ),
            (
                "max_sources_per_target",
                definition.max_sources_per_target,
                link.target_id,
                Link.target_id,
            ),
        )
        for name, limit, entity_id, column in limits:
            if limit is None:
                continue
            touching = (
                or_(Link.source_id == entity_id, Link.target_id == entity_id)
                if definition.symmetric
                else column == entity_id
            )
            count = self.session.scalar(
                select(func.count()).select_from(others.where(touching, timeless(Link)).subquery())
            )
            if (count or 0) >= limit:
                raise ConflictError(
                    f"{definition.label!r} allows at most {limit} such links per entity.",
                    context={"limit": name, "max": limit},
                )
