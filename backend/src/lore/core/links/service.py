"""The link service: create, update and trash typed links, and list an entity's links
(``data-model.md`` §6.1-§6.2, ``time-model.md`` §10.3).

Rules (decided 2026-10-04 where noted):

- The type must be offered (``LinkTypeCatalog``) and not archived; source and target kinds must
  fit it (``422 link_type_not_allowed``). Endpoints must exist, not be in the trash and be of
  available kinds. An entity can't link to itself (decided).
- Symmetric types are stored once with ``source_id < target_id``.
- Validity: ``temporal: never`` refuses bounds, ``required`` needs at least one. A link with bounds
  needs a ``timeline_id`` (default: the prime timeline of its source's dimension, else its
  target's); a timeless link has none. Bounds are slots ``link:<id>.valid_from|valid_to``,
  resolved and propagated by ``TimeWriter`` (#102): they may be anchored to events and referenced
  by other dates.
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
from sqlalchemy import ColumnElement, Select, and_, case, func, or_, select, true
from sqlalchemy.orm import Session, aliased

from lore.chronology.schema import TimePoint
from lore.core.consistency.schemas import request_suppress
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
    UnlinkedMentions,
)
from lore.core.links.unlinked import UnlinkedMentionFinder
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import ModuleDisabledError, enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.richtext.models import Mention
from lore.core.time.changes import report as report_time
from lore.core.time.dependencies import SlotNode
from lore.core.time.dimensions import prime_timeline
from lore.core.time.models import Timeline
from lore.core.time.propagate import TimeWriter
from lore.core.time.redact import ReaderTimes
from lore.core.time.state import AsOf, Coverage, as_of_for, maybe_covers, timeline_resolver
from lore.core.time.timeline_view import TimelineView
from lore.core.types import Affected, Certainty
from lore.core.vaults import OpenVault
from lore.core.visibility import AUTHOR, VisibilityPolicy

TIMELINE_KIND = "timeline"
LINK = "link"
SLOTS = ("valid_from", "valid_to")


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
        valid_from_t=link.valid_from_t,
        valid_to_t=link.valid_to_t,
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
        self,
        session: Session,
        registry: ModuleRegistry,
        policy: VisibilityPolicy = AUTHOR,
        vault: OpenVault | None = None,
    ) -> None:
        self.session = session
        self.registry = registry
        self.policy = policy  # applied by reads; writes are author-only
        self.vault = vault  # reads for readers need it (resolving hidden anchors)
        self._reader_times: ReaderTimes | None = None
        enabled = enabled_modules(session, registry)
        self.kinds = {kind.key for kind in registry.kinds_for(enabled)}
        self.catalog = LinkTypeCatalog(session, registry, enabled)

    def _shown(self, link: Link) -> LinkOut:
        """A link as the policy may see it: for readers, validity bounds anchored to hidden
        records become their resolved moments (``visibility-and-sharing.md`` §2)."""
        out = link_out(link)
        if not self.policy.reader or (out.valid_from is None and out.valid_to is None):
            return out
        if self.vault is None:
            raise RuntimeError("reader link reads need the vault")
        dimension_id = self.session.scalar(
            select(Timeline.dimension_id).where(Timeline.entity_id == link.timeline_id)
        )
        times = self._reader_times
        if times is None:
            times = self._reader_times = ReaderTimes(
                VaultContext(self.vault, self.session, self.registry), self.policy
            )
        shown = [times.point(point, dimension_id) for point in (out.valid_from, out.valid_to)]
        out.valid_from, out.valid_to = (
            None if point is None else TimePoint.model_validate(point) for point in shown
        )
        return out

    # --- writes ---------------------------------------------------------------------------------

    def create(self, data: LinkCreate) -> LinkWriteResult:
        request_suppress(self.session, data.suppress)
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
        sent = set(data.model_fields_set) | {"data"}
        self._apply(link, info, data, sent, source=source, target=target)
        self.session.add(link)
        self.session.flush()
        self._write_times(link, {s for s in SLOTS if getattr(link, f"{s}_spec") is not None})
        self._check_limits(info, link)  # after the bounds resolve: periods are compared
        return link

    def update(self, link_id: str, data: LinkUpdate) -> LinkWriteResult:
        request_suppress(self.session, data.suppress)
        link, info = self._load(link_id)
        if link.deleted_at is not None:
            raise ConflictError("The link is in the trash.")
        if data.revision != link.revision:
            raise RevisionConflictError(
                f"The link was changed meanwhile (revision {link.revision}, the edit is based "
                f"on {data.revision}).",
                context={"current": link_out(link).model_dump(mode="json")},
            )
        sent = data.model_fields_set - {"revision", "suppress"}
        if sent:
            link.updated_at = utc_now()  # first: one UPDATE even if a query autoflushes
        if "visibility" in sent:
            if data.visibility is None:
                raise _invalid("visibility", "Visibility must be public, spoiler or private.")
            link.visibility = data.visibility
        if "sort_key" in sent:
            link.sort_key = data.sort_key
        timeline_before = link.timeline_id
        self._apply(link, info, data, sent)
        self.session.flush()
        slots = {slot for slot in SLOTS if slot in sent}
        if link.timeline_id != timeline_before:  # another dimension: the bounds resolve again
            slots.update(s for s in SLOTS if getattr(link, f"{s}_spec") is not None)
        self._write_times(link, slots)
        self._check_limits(info, link)
        return LinkWriteResult(link=link_out(link), affected=self.affected([link]))

    def trash(self, link_id: str) -> LinkDeleteResult:
        """Move to the trash (idempotent)."""
        link, _info = self._load(link_id)
        if link.deleted_at is None:
            link.deleted_at = utc_now()
            self.session.flush()
            self._touch_dependents([link])
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
        self._touch_dependents(links)
        return links

    def affected(self, links: Sequence[Link]) -> Affected:
        ids = list(dict.fromkeys(i for link in links for i in (link.source_id, link.target_id)))
        dimensions = self.session.scalars(
            select(Entity.dimension_id).where(Entity.id.in_(ids), Entity.dimension_id.is_not(None))
        )
        affected = Affected(
            entities=ids,
            dimensions=sorted({d for d in dimensions if d is not None}),
            time_changed=False,  # validity bounds resolve with #102
            search_changed=False,
        )
        return report_time(self.session, self.registry, affected)

    # --- reads ----------------------------------------------------------------------------------

    def entity_links(
        self,
        entity_id: str,
        *,
        direction: Literal["out", "in", "both"] = "both",
        types: Sequence[str] | None = None,
        include_trashed: bool = False,
        as_of: AsOf | None = None,
    ) -> EntityLinks:
        """The entity's links, by type, then manual order, then the other end's name.
        ``include_trashed`` also lists links whose other end is in the trash (never for readers).
        With ``as_of`` (the time cursor, ``time-model.md`` §10.5 item 3): timeless links, and the
        temporal links the timeline sees whose validity covers the moment (certainly or
        possibly, ``certainty``)."""
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
        if as_of is not None:
            conditions.append(or_(timeless(Link), Link.id.in_(self._covering(entity_id, as_of))))
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
        certainty = self._certainty([link for link, _end in rows], as_of)
        items = []
        for link, end in rows:
            if as_of is not None and link.id not in certainty:
                continue  # its bounds' extents say it doesn't cover the moment after all
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
                    link=self._shown(link),
                    direction=side,
                    label=label,
                    other=_linked(end),
                    certainty=certainty.get(link.id),
                )
            )
        return EntityLinks(items=items)

    def _covering(self, entity_id: str, as_of: AsOf) -> Select[tuple[str]]:
        """Ids of the entity's temporal links the timeline sees (lineage, overrides) that may
        cover the moment."""
        view = TimelineView.for_timeline(self.session, as_of.timeline_id)
        shown = view.select(
            Link,
            where=lambda row: [
                row.deleted_at.is_(None),
                or_(row.source_id == entity_id, row.target_id == entity_id),
            ],
        ).subquery()
        return select(shown.c.id).where(*maybe_covers(shown.c, as_of.t))

    def _certainty(self, links: Sequence[Link], as_of: AsOf | None) -> dict[str, Certainty]:
        """For the time cursor: the certainty of each link covering the moment (timeless ones
        are certain); links missing from the result don't cover it."""
        if as_of is None:
            return {}
        bounded = [link for link in links if link.timeline_id is not None]
        result: dict[str, Certainty] = {
            link.id: "certain" for link in links if link.timeline_id is None
        }
        if bounded:
            if self.vault is None:
                raise RuntimeError("as-of link reads need the vault")
            context = VaultContext(self.vault, self.session, self.registry)
            # Extents only tell how precise a bound is: the author's resolver reads them.
            coverage = Coverage(timeline_resolver(context, AUTHOR, as_of.timeline_id), LINK,
                                as_of.t)  # fmt: skip
            coverage.preload(bounded)
            for link in bounded:
                found = coverage.of(link)
                if found is not None:
                    result[link.id] = found
        return result

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

    def unlinked_mentions(self, entity_id: str, *, limit: int) -> UnlinkedMentions:
        """Where other entities' bodies name this one (name or alias) without linking to it
        (``unlinked.py``), by source name."""
        entity = self.session.get(Entity, entity_id)
        if entity is None or not self.policy.visible_ids(self.session, [entity_id]):
            raise NotFoundError(f"No entity {entity_id}.")
        if entity.kind not in self.kinds:
            raise ModuleDisabledError(f"The module of kind {entity.kind!r} is disabled.")
        finder = UnlinkedMentionFinder(self.session, self.registry, self.policy, self.kinds)
        return finder.find(entity, limit=limit, linked=_linked)

    def backlinks(
        self, entity_id: str, *, include_trashed: bool = False, as_of: AsOf | None = None
    ) -> Backlinks:
        """Entities pointing at this one through incoming links (and symmetric ones) or mentions
        in their text, by name (decided 2026-10-04). Self-mentions aren't recorded. ``as_of``
        filters the links (mentions are timeless)."""
        incoming = self.entity_links(
            entity_id, direction="in", include_trashed=include_trashed, as_of=as_of
        )
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
        *,
        source: Entity | None = None,
        target: Entity | None = None,
    ) -> None:
        """Role, data and validity (shared by create and update). A link given bounds without a
        timeline gets the prime timeline of its ends' dimension; one losing its bounds loses its
        timeline."""
        if "role" in sent:
            link.role = data.role
        if "data" in sent:
            if data.data is None:
                raise _invalid("data", "data must be an object.")
            errors = data_errors(info.definition.data_schema, data.data)
            if errors:
                raise InvalidInputError("The link data doesn't match its type.", errors=errors)
            link.data = data.data
        self._apply_validity(link, data, sent, source, target)
        self._check_validity(info, link)

    def _apply_validity(
        self,
        link: Link,
        data: LinkCreate | LinkUpdate,
        sent: set[str],
        source: Entity | None,
        target: Entity | None,
    ) -> None:
        if "valid_from" in sent:
            link.valid_from_spec = data.valid_from
            if data.valid_from is None:
                link.valid_from_t = None
        if "valid_to" in sent:
            link.valid_to_spec = data.valid_to
            if data.valid_to is None:
                link.valid_to_t = None
        if link.valid_from_spec is None and link.valid_to_spec is None:
            link.time_status = None
        if "timeline_id" in sent:
            link.timeline_id = data.timeline_id
        elif "valid_from" in sent or "valid_to" in sent:
            bounded = link.valid_from_spec is not None or link.valid_to_spec is not None
            if not bounded:
                link.timeline_id = None
            elif link.timeline_id is None:
                link.timeline_id = self._default_timeline(link, source, target)

    def _default_timeline(
        self, link: Link, source: Entity | None, target: Entity | None
    ) -> str | None:
        """The prime timeline of the dimension of the link's source (else its target)."""
        ends = [source or self.session.get(Entity, link.source_id),
                target or self.session.get(Entity, link.target_id)]  # fmt: skip
        for end in ends:
            if end is not None and end.dimension_id is not None:
                prime = prime_timeline(self.session, end.dimension_id)
                if prime is not None:
                    return prime.id
        return None  # both ends multiversal: the timeline must be given

    # --- time -----------------------------------------------------------------------------------

    def _writer(self) -> TimeWriter:
        if self.vault is None:
            raise RuntimeError("link time writes need the vault")
        return TimeWriter(VaultContext(self.vault, self.session, self.registry))

    def _write_times(self, link: Link, slots: set[str]) -> None:
        """Store the changed bounds' specs and propagate (resolving them and what is anchored to
        them); ``422 time_constraint`` when a bound can't resolve."""
        if not slots:
            return
        writer = self._writer()
        for slot in sorted(slots):
            writer.set_spec(LINK, link.id, slot, getattr(link, f"{slot}_spec"))
        writer.propagate(path="")

    def _touch_dependents(self, links: Sequence[Link]) -> None:
        """Trashed links: what is anchored to their bounds keeps its last moments
        (``trashed_ref``)."""
        bounded = [link for link in links if link.timeline_id is not None]
        if not bounded:
            return
        writer = self._writer()
        nodes = [SlotNode(LINK, link.id, slot) for link in bounded for slot in SLOTS]
        writer.touch(*(d for node in nodes for d in writer.index.dependents_of(node)))
        writer.propagate(path="")

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
        """Uniqueness and cardinality. ``per_pair`` counts every link of the pair; the others
        count the links that hold at the same time as this one (``_concurrent``)."""
        definition = info.definition
        others = select(Link.id).where(
            Link.link_type == link.link_type,
            Link.deleted_at.is_(None),
            Link.id != link.id,
            self._concurrent(link) if definition.unique != "per_pair" else true(),
        )
        if definition.unique in ("per_pair", "per_pair_per_period"):
            pair = others.where(Link.source_id == link.source_id, Link.target_id == link.target_id)
            existing = list(self.session.scalars(pair))
            if existing:
                raise ConflictError(
                    f"These entities already have a {definition.label!r} link"
                    + (" then." if definition.unique == "per_pair_per_period" else "."),
                    context={"links": existing},
                )
        concurrent = select(Link.id).where(
            Link.link_type == link.link_type,
            Link.deleted_at.is_(None),
            Link.id != link.id,
            self._concurrent(link),
        )
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
                select(func.count()).select_from(concurrent.where(touching).subquery())
            )
            if (count or 0) >= limit:
                raise ConflictError(
                    f"{definition.label!r} allows at most {limit} such links per entity"
                    + (" at a time." if link.timeline_id is not None else "."),
                    context={"limit": name, "max": limit},
                )

    @staticmethod
    def _concurrent(link: Link) -> ColumnElement[bool]:
        """Links holding at the same time as ``link`` (resolved periods; open bounds are
        unbounded): a timeless link holds at every time, so it meets every link; a temporal one
        meets the timeless ones and those of its timeline whose periods overlap it."""
        if link.timeline_id is None:
            return true()
        overlap = and_(
            Link.timeline_id == link.timeline_id,
            true() if link.valid_to_t is None else or_(
                Link.valid_from_t.is_(None), Link.valid_from_t < link.valid_to_t
            ),
            true() if link.valid_from_t is None else or_(
                Link.valid_to_t.is_(None), Link.valid_to_t > link.valid_from_t
            ),
        )  # fmt: skip
        return or_(timeless(Link), overlap)


def link_cursor(
    context: VaultContext,
    policy: VisibilityPolicy,
    entity_id: str,
    timeline_id: str | None,
    at: str | None,
) -> AsOf | None:
    """The time cursor of an entity's link list: the timeline defaults to the prime timeline of
    the entity's dimension (multiversal entities need one). ``404`` for a hidden entity."""
    if at is None:
        return None
    entity = context.session.get(Entity, entity_id)
    if entity is None or not policy.visible_ids(context.session, [entity_id]):
        raise NotFoundError(f"No entity {entity_id}.")
    return as_of_for(
        context, policy, timeline_id=timeline_id, at=at, dimension_id=entity.dimension_id
    )
