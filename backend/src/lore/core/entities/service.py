"""The entity service: create, read, update, trash, restore and purge entities of every kind
(``data-model.md`` §3-§4, ``api.md`` §1-§2).

It works inside the caller's transaction (one request = one transaction) and only flushes.
Entities of kinds whose module is disabled are unavailable (``404 module_disabled``).
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import func, or_, select

from lore.core.db.base import VISIBILITIES, Visibility, new_id
from lore.core.db.types import utc_now
from lore.core.entities.errors import ParentNotAllowedError, RevisionConflictError
from lore.core.entities.models import (
    Entity,
    EntityAlias,
    EntityTag,
    Tag,
    fold_text,
    tag_name_key,
)
from lore.core.entities.schemas import (
    AliasIn,
    AliasOut,
    EntityCreate,
    EntityDeleteResult,
    EntityOut,
    EntityUpdate,
    EntityWriteResult,
    TagOut,
)
from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.fields import KindFields
from lore.core.links.models import Link
from lore.core.links.schemas import EntityLinkAdd, LinkCreate
from lore.core.links.service import LinkService
from lore.core.modules.registry import RegisteredKind
from lore.core.modules.service import ModuleDisabledError, enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.richtext import SCHEMA_VERSION as RICHTEXT_SCHEMA_VERSION
from lore.core.types import Affected
from lore.core.vaults.meta import get_meta

DIMENSION_KIND = "dimension"
SLUG_MAX = 80
# Members whose change affects the search index (name, aliases, text, fields, tags, filters).
_SEARCH_MEMBERS = frozenset(
    {"name", "summary", "body", "fields", "field_visibility", "visibility", "aliases", "tags",
     "dimension_id", "parent_id"}
)  # fmt: skip


def slugify(name: str) -> str:
    """The cosmetic slug of a name (not unique; URLs use ids): accents removed, case-folded, runs
    of anything but letters and digits replaced by a hyphen. Other scripts are kept."""
    slug = re.sub(r"[\W_]+", "-", fold_text(name)).strip("-")
    return slug[:SLUG_MAX].rstrip("-") or "entity"


def _error(path: str, message: str, code: str = "invalid_value") -> ErrorItem:
    return {"path": path, "code": code, "message": message}


def _invalid(path: str, message: str) -> InvalidInputError:
    return InvalidInputError(message, errors=[_error(path, message)])


def _parent_error(message: str) -> ParentNotAllowedError:
    return ParentNotAllowedError(
        message, errors=[_error("parent_id", message, "parent_not_allowed")]
    )


def _sequence_key(index: int) -> str:
    """Sort keys for a list that is replaced as a whole (aliases): fixed width, so text order is
    list order."""
    return f"{index:06d}"


def _unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value is not None))


class EntityService:
    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        self.registry = context.registry
        enabled = enabled_modules(self.session, self.registry)
        self.kinds = {kind.key: kind for kind in self.registry.kinds_for(enabled)}
        self.field_types = self.registry.field_types_for(enabled)
        self.extensions = self.registry.kind_extensions_for(enabled)
        self._kind_fields: dict[str, KindFields] = {}

    # --- reads ----------------------------------------------------------------------------------

    def get(self, entity_id: str) -> EntityOut:
        """An entity, also when it is in the trash."""
        return self.to_out(self._load(entity_id))

    def to_out(self, entity: Entity) -> EntityOut:
        kind_fields = self.kind_fields(self._kind_of(entity))
        aliases = self.session.scalars(
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity.id)
            .order_by(EntityAlias.sort_key, EntityAlias.id)
        )
        tags = self.session.scalars(
            select(Tag)
            .join(EntityTag, EntityTag.tag_id == Tag.id)
            .where(EntityTag.entity_id == entity.id)
            .order_by(Tag.name_key)
        )
        extension = self.extensions.get(entity.kind)
        return EntityOut(
            id=entity.id,
            kind=entity.kind,
            dimension_id=entity.dimension_id,
            origin_timeline_id=entity.origin_timeline_id,
            parent_id=entity.parent_id,
            name=entity.name,
            slug=entity.slug,
            summary=entity.summary,
            body=entity.body,
            body_schema_version=entity.body_schema_version,
            fields=kind_fields.visible(entity.fields),
            field_visibility=kind_fields.visible(entity.field_visibility),
            visibility=entity.visibility,
            icon=entity.icon,
            color=entity.color,
            cover_media_id=entity.cover_media_id,
            sort_key=entity.sort_key,
            aliases=[
                AliasOut(
                    id=alias.id,
                    alias=alias.alias,
                    alias_kind=alias.alias_kind,  # type: ignore[arg-type]
                    visibility=alias.visibility,
                )
                for alias in aliases
            ],
            tags=[TagOut(id=tag.id, name=tag.name, color=tag.color) for tag in tags],
            ext=extension.read(self.context, entity) if extension else None,
            revision=entity.revision,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )

    def kind_fields(self, kind: RegisteredKind) -> KindFields:
        if kind.key not in self._kind_fields:
            self._kind_fields[kind.key] = KindFields.build(kind.fields, self.field_types)
        return self._kind_fields[kind.key]

    # --- writes ---------------------------------------------------------------------------------

    def create(self, data: EntityCreate) -> EntityWriteResult:
        kind = self.kinds.get(data.kind)
        if kind is None:
            if data.kind in self.registry.all_kind_keys():
                raise ModuleDisabledError(f"The module of kind {data.kind!r} is disabled.")
            raise _invalid("kind", f"Unknown kind {data.kind!r}.")
        self._check_body(kind, data.body)
        self._check_dimension(kind, data.dimension_id)
        extension = self._extension_for(kind, data.ext)
        kind_fields = self.kind_fields(kind)
        entity = Entity(
            id=new_id(),
            kind=kind.key,
            dimension_id=data.dimension_id,
            name=data.name,
            slug=slugify(data.name),
            summary=data.summary,
            body=data.body,
            body_schema_version=RICHTEXT_SCHEMA_VERSION if data.body is not None else None,
            fields=kind_fields.merge_values({}, data.fields),
            field_visibility=kind_fields.merge_visibility({}, data.field_visibility),
            visibility=data.visibility or self._default_visibility(),
            icon=data.icon,
            color=data.color.lower() if data.color else None,
            sort_key=data.sort_key,
        )
        if data.parent_id is not None:
            self._check_parent(None, kind, data.dimension_id, data.parent_id)
            entity.parent_id = data.parent_id
        self.session.add(entity)
        self.session.flush()
        self._replace_aliases(entity, data.aliases)
        self._replace_tags(entity, data.tags)
        if extension is not None:
            extension.write(self.context, entity, data.ext, True)
        links = self._add_links(entity, data.links_add)
        self.session.flush()
        affected = self._affected([entity.id, entity.parent_id], [entity.dimension_id], True)
        return EntityWriteResult(
            entity=self.to_out(entity), affected=self._with_links(affected, links)
        )

    def update(self, entity_id: str, data: EntityUpdate) -> EntityWriteResult:
        entity = self._load(entity_id)
        kind = self._kind_of(entity)
        if entity.deleted_at is not None:
            raise ConflictError("The entity is in the trash: restore it before editing it.")
        if data.revision != entity.revision:
            raise RevisionConflictError(
                f"The entity was changed meanwhile (revision {entity.revision}, "
                f"the edit is based on {data.revision}).",
                context={"current": self.to_out(entity).model_dump(mode="json")},
            )
        sent = data.model_fields_set - {"revision"}
        old_parent, old_dimension = entity.parent_id, entity.dimension_id
        if sent:
            # First, so queries that autoflush midway don't update the row (and revision) twice;
            # also bumps the revision when only aliases, tags, ext or links change.
            entity.updated_at = utc_now()

        self._apply_members(entity, kind, data, sent)
        self._move(entity, kind, data, sent)
        if "aliases" in sent:
            self._replace_aliases(entity, data.aliases)
        if "tags" in sent:
            self._replace_tags(entity, data.tags)
        if "ext" in sent:
            extension = self._extension_for(kind, data.ext)
            if extension is not None:
                extension.write(self.context, entity, data.ext, False)
        links: list[Link] = []
        if "links_remove" in sent:  # first, so a link can be replaced under a uniqueness rule
            links += self._links().trash_for_entity(entity.id, data.links_remove)
        if "links_add" in sent:
            links += self._add_links(entity, data.links_add)
        self.session.flush()
        affected = self._affected(
            [entity.id, old_parent, entity.parent_id],
            [old_dimension, entity.dimension_id],
            bool(sent & _SEARCH_MEMBERS),
        )
        return EntityWriteResult(
            entity=self.to_out(entity), affected=self._with_links(affected, links)
        )

    def _apply_members(
        self, entity: Entity, kind: RegisteredKind, data: EntityUpdate, sent: set[str]
    ) -> None:
        """Apply the sent scalar members and field changes of a PATCH."""
        kind_fields = self.kind_fields(kind)
        if "name" in sent:
            if data.name is None:
                raise _invalid("name", "The name can't be empty.")
            entity.name, entity.slug = data.name, slugify(data.name)
        if "visibility" in sent:
            if data.visibility is None:
                raise _invalid("visibility", "Visibility must be public, spoiler or private.")
            entity.visibility = data.visibility
        if "summary" in sent:
            entity.summary = data.summary
        if "body" in sent:
            self._check_body(kind, data.body)
            entity.body = data.body
            entity.body_schema_version = RICHTEXT_SCHEMA_VERSION if data.body is not None else None
        if "fields" in sent:
            entity.fields = kind_fields.merge_values(entity.fields, data.fields)
        elif sent:
            # Required fields are checked on every save, also when the PATCH doesn't touch them.
            kind_fields.merge_values(entity.fields, {})
        if "field_visibility" in sent:
            entity.field_visibility = kind_fields.merge_visibility(
                entity.field_visibility, data.field_visibility
            )
        if "icon" in sent:
            entity.icon = data.icon
        if "color" in sent:
            entity.color = data.color.lower() if data.color else None
        if "sort_key" in sent:
            entity.sort_key = data.sort_key

    def trash(self, entity_id: str) -> EntityDeleteResult:
        """Move to the trash (idempotent). Children stay where they are: the trash view shows
        them as orphans of the trashed parent."""
        entity = self._load(entity_id)
        if entity.deleted_at is None:
            entity.deleted_at = utc_now()
            self.session.flush()
        return EntityDeleteResult(
            id=entity.id,
            purged=False,
            entity=self.to_out(entity),
            affected=self._affected([entity.id, entity.parent_id], [entity.dimension_id], True),
        )

    def restore(self, entity_id: str) -> EntityWriteResult:
        """Take out of the trash (idempotent)."""
        entity = self._load(entity_id)
        if entity.deleted_at is not None:
            entity.deleted_at = None
            self.session.flush()
        return EntityWriteResult(
            entity=self.to_out(entity),
            affected=self._affected([entity.id, entity.parent_id], [entity.dimension_id], True),
        )

    def purge(self, entity_id: str) -> EntityDeleteResult:
        """Delete permanently; only from the trash. Purge hooks run first, then the entity's
        aliases, tag assignments and links are deleted with it. Children (also trashed ones) and
        other records still referencing the entity (a dimension's contents, …) block the purge
        (``409 conflict``)."""
        entity = self._load(entity_id)
        if entity.deleted_at is None:
            raise ConflictError("Only entities in the trash can be purged: trash it first.")
        self._check_purgeable(entity)
        for hook in self.registry.purge_hooks():
            hook(self.context, entity)

        touched: list[str | None] = [entity.id, entity.parent_id]
        # Links with an override row (branches, M5) are handled by that module's purge hook.
        for link in self.session.scalars(
            select(Link).where(or_(Link.source_id == entity.id, Link.target_id == entity.id))
        ):
            touched += [link.source_id, link.target_id]
            self.session.delete(link)
        for alias in self.session.scalars(
            select(EntityAlias).where(EntityAlias.entity_id == entity.id)
        ):
            self.session.delete(alias)
        for assignment in self.session.scalars(
            select(EntityTag).where(EntityTag.entity_id == entity.id)
        ):
            self.session.delete(assignment)
        self.session.flush()
        self.session.delete(entity)
        self.session.flush()
        affected = self._affected(touched, [entity.dimension_id], True)
        return EntityDeleteResult(id=entity.id, purged=True, entity=None, affected=affected)

    # --- rules ----------------------------------------------------------------------------------

    def load(self, entity_id: str) -> Entity:
        """The entity, also in the trash: ``404 not_found``, or ``404 module_disabled`` when its
        kind's module is disabled."""
        return self._load(entity_id)

    def _load(self, entity_id: str) -> Entity:
        entity = self.session.get(Entity, entity_id)
        if entity is None:
            raise NotFoundError(f"No entity {entity_id}.")
        self._kind_of(entity)
        return entity

    def _kind_of(self, entity: Entity) -> RegisteredKind:
        kind = self.kinds.get(entity.kind)
        if kind is None:
            raise ModuleDisabledError(
                f"Entities of kind {entity.kind!r} are unavailable: their module is disabled."
            )
        return kind

    def _default_visibility(self) -> Visibility:
        settings = get_meta(self.session, "settings")
        defaults = settings.get("defaults") if isinstance(settings, dict) else None
        value = defaults.get("visibility") if isinstance(defaults, dict) else None
        return value if value in VISIBILITIES else "public"

    def _check_body(self, kind: RegisteredKind, body: dict[str, Any] | None) -> None:
        if body is not None and not kind.definition.capabilities.has_body:
            raise _invalid("body", f"{kind.definition.label} entities have no body.")

    def _extension_for(self, kind: RegisteredKind, ext: dict[str, Any] | None) -> Any:
        extension = self.extensions.get(kind.key)
        if extension is None and ext:
            raise _invalid("ext", f"{kind.definition.label} entities take no extension data.")
        return extension

    def _check_dimension(self, kind: RegisteredKind, dimension_id: str | None) -> None:
        """A dimension has no home dimension; other kinds need one unless they can be
        multiversal. The home dimension must be a dimension that isn't in the trash."""
        label = kind.definition.label
        if kind.key == DIMENSION_KIND:
            if dimension_id is not None:
                raise _invalid("dimension_id", "A dimension has no home dimension.")
            return
        if dimension_id is None:
            if not kind.definition.capabilities.can_be_multiversal:
                raise _invalid("dimension_id", f"{label} entities need a home dimension.")
            return
        dimension = self.session.get(Entity, dimension_id)
        if dimension is None or dimension.kind != DIMENSION_KIND:
            raise _invalid("dimension_id", "The home dimension must be a dimension.")
        if dimension.deleted_at is not None:
            raise _invalid("dimension_id", "The home dimension is in the trash.")

    def _check_parent(
        self,
        entity_id: str | None,
        kind: RegisteredKind,
        dimension_id: str | None,
        parent_id: str,
    ) -> None:
        """Parent rules (``data-model.md`` §3.4)."""
        parent = self.session.get(Entity, parent_id)
        if parent is None:
            raise _parent_error(f"No entity {parent_id}.")
        if parent.deleted_at is not None:
            raise _parent_error("The parent is in the trash.")
        parent_kind = self.kinds.get(parent.kind)
        if parent_kind is None:
            raise _parent_error("The parent's module is disabled.")
        if parent.kind not in kind.definition.allowed_parents:
            raise _parent_error(
                f"{kind.definition.label} entities can't be placed under a "
                f"{parent_kind.definition.label.lower()}."
            )
        if entity_id is not None and entity_id in self._ancestors_and_self(parent_id):
            raise _parent_error("The parent can't be the entity itself or one of its descendants.")
        if not _same_tree(parent.dimension_id, dimension_id):
            raise _parent_error(
                "The parent is in another dimension (one of them must be multiversal)."
            )

    def _ancestors_and_self(self, entity_id: str) -> set[str]:
        chain = (
            select(Entity.id, Entity.parent_id)
            .where(Entity.id == entity_id)
            .cte("chain", recursive=True)
        )
        # UNION (not UNION ALL) also terminates on a cycle.
        chain = chain.union(
            select(Entity.id, Entity.parent_id).join(chain, Entity.id == chain.c.parent_id)
        )
        return set(self.session.scalars(select(chain.c.id)))

    def _move(
        self, entity: Entity, kind: RegisteredKind, data: EntityUpdate, sent: set[str]
    ) -> None:
        """Apply a change of home dimension and/or parent."""
        new_dimension = data.dimension_id if "dimension_id" in sent else entity.dimension_id
        new_parent = data.parent_id if "parent_id" in sent else entity.parent_id
        capabilities = kind.definition.capabilities
        if new_dimension != entity.dimension_id:
            if capabilities.is_system or capabilities.is_time_bound:
                raise _invalid(
                    "dimension_id",
                    f"The home dimension of {kind.definition.plural.lower()} can't change.",
                )
            self._check_dimension(kind, new_dimension)
            self._check_children(entity, new_dimension)
        if new_parent is not None and new_parent != entity.parent_id:
            self._check_parent(entity.id, kind, new_dimension, new_parent)
        elif new_parent is not None and new_dimension != entity.dimension_id:
            parent = self.session.get(Entity, new_parent)
            if parent is not None and not _same_tree(parent.dimension_id, new_dimension):
                raise _parent_error(
                    "The parent is in another dimension (one of them must be multiversal)."
                )
        entity.dimension_id, entity.parent_id = new_dimension, new_parent

    def _check_children(self, entity: Entity, dimension_id: str | None) -> None:
        if dimension_id is None:
            return
        stranded = self.session.scalar(
            select(func.count())
            .select_from(Entity)
            .where(
                Entity.parent_id == entity.id,
                Entity.dimension_id.is_not(None),
                Entity.dimension_id != dimension_id,
            )
        )
        if stranded:
            raise _invalid(
                "dimension_id",
                f"{stranded} children are in the current dimension: move them first, or make "
                "the entity multiversal.",
            )

    def _check_purgeable(self, entity: Entity) -> None:
        references = {
            "children": select(func.count())
            .select_from(Entity)
            .where(Entity.parent_id == entity.id),
            "entities in this dimension": select(func.count())
            .select_from(Entity)
            .where(Entity.dimension_id == entity.id),
            "branch-only entities of this timeline": select(func.count())
            .select_from(Entity)
            .where(Entity.origin_timeline_id == entity.id),
            "links in this timeline": select(func.count())
            .select_from(Link)
            .where(Link.timeline_id == entity.id),
        }
        counts = {label: self.session.scalar(query) or 0 for label, query in references.items()}
        blocking = {label: count for label, count in counts.items() if count}
        if blocking:
            listed = ", ".join(f"{count} {label}" for label, count in blocking.items())
            raise ConflictError(
                f"The entity is still referenced ({listed}): purge those first.",
                context={"references": blocking},
            )

    # --- aliases and tags -----------------------------------------------------------------------

    # --- inline links (composite writes, api.md §1) ----------------------------------------------

    def _links(self) -> LinkService:
        return LinkService(self.session, self.registry)

    def _add_links(self, entity: Entity, items: Sequence[EntityLinkAdd]) -> list[Link]:
        """Create ``links_add``: the entity fills the end the item leaves out. Error paths are
        prefixed ``links_add.<index>``."""
        if not items:
            return []
        service = self._links()
        links = []
        for index, item in enumerate(items):
            prefix = f"links_add.{index}"
            if (item.source_id is None) == (item.target_id is None):
                raise _invalid(prefix, "Give exactly one of source_id and target_id.")
            members = item.model_dump(
                include=item.model_fields_set - {"link_type", "source_id", "target_id"}
            )
            try:
                links.append(
                    service.add(
                        LinkCreate(
                            **members,
                            link_type=item.link_type,
                            source_id=item.source_id or entity.id,
                            target_id=item.target_id or entity.id,
                        )
                    )
                )
            except InvalidInputError as exc:
                exc.errors = [
                    {**error, "path": f"{prefix}.{error['path']}"} for error in exc.errors or []
                ] or [_error(prefix, exc.detail, exc.code)]
                raise
        return links

    def _with_links(self, affected: Affected, links: Sequence[Link]) -> Affected:
        if not links:
            return affected
        extra = self._links().affected(links)
        return affected.model_copy(
            update={
                "entities": _unique([*affected.entities, *extra.entities]),
                "dimensions": _unique([*affected.dimensions, *extra.dimensions]),
            }
        )

    def _replace_aliases(self, entity: Entity, items: Sequence[AliasIn]) -> None:
        existing = {
            alias.id: alias
            for alias in self.session.scalars(
                select(EntityAlias).where(EntityAlias.entity_id == entity.id)
            )
        }
        kept: set[str] = set()
        errors: list[ErrorItem] = []
        for index, item in enumerate(items):
            if item.id is not None:
                if item.id not in existing or item.id in kept:
                    errors.append(_error(f"aliases.{index}.id", "not an alias of this entity"))
                    continue
                alias = existing[item.id]
                kept.add(item.id)
            else:
                alias = EntityAlias(id=new_id(), entity_id=entity.id)
                self.session.add(alias)
            alias.alias = item.alias
            alias.alias_kind = item.alias_kind
            alias.visibility = item.visibility
            alias.sort_key = _sequence_key(index)
        if errors:
            raise InvalidInputError("Some aliases are invalid.", errors=errors)
        for alias_id, alias in existing.items():
            if alias_id not in kept:
                self.session.delete(alias)

    def _replace_tags(self, entity: Entity, names: Sequence[str]) -> None:
        """Set the entity's tags by name (case-insensitive), creating missing tags."""
        wanted: dict[str, str] = {}
        for name in names:
            wanted.setdefault(tag_name_key(name), name)
        tags = {
            tag.name_key: tag
            for tag in self.session.scalars(select(Tag).where(Tag.name_key.in_(wanted)))
        }
        for key, name in wanted.items():
            if key not in tags:
                tags[key] = Tag(id=new_id(), name=name)
                self.session.add(tags[key])
        self.session.flush()
        wanted_ids = {tags[key].id for key in wanted}
        current = {
            row.tag_id: row
            for row in self.session.scalars(
                select(EntityTag).where(EntityTag.entity_id == entity.id)
            )
        }
        for tag_id, row in current.items():
            if tag_id not in wanted_ids:
                self.session.delete(row)
        for tag_id in wanted_ids - set(current):
            self.session.add(EntityTag(entity_id=entity.id, tag_id=tag_id))

    def _affected(
        self, entities: Iterable[str | None], dimensions: Iterable[str | None], search: bool
    ) -> Affected:
        return Affected(
            entities=_unique(entities),
            dimensions=_unique(dimensions),
            time_changed=False,  # time propagation arrives with M3
            search_changed=search,
        )


def _same_tree(parent_dimension: str | None, child_dimension: str | None) -> bool:
    """A parent must be in the child's dimension, unless one of them is multiversal."""
    return (
        parent_dimension is None or child_dimension is None or parent_dimension == child_dimension
    )
