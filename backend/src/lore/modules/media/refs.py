"""``media_refs``: who uses a media item (``docs/modules/media.md``, Integration points).

The contexts this module derives are rebuilt for an entity from its stored state whenever a
changeset touches it (``ModuleSpec.derived_hooks``, so undo and every writer are covered):

- ``body``: ``image`` nodes of the body, at the level of their innermost ``visibilityBlock``;
- ``field:<key>``: ``image`` nodes of a ``rich_text`` field and the ids of a ``media`` field, at
  the field's level (its default or the entity's override; a temporal field's facts at their own
  level, the stricter of the two);
- ``cover``: ``cover_media_id`` (public: the entity's own visibility applies on read);
- ``gallery``: the entity's live gallery items, at their visibility.

Other contexts (``map``, ``note``) belong to the modules that write them through
``lore.modules.media.api``. A context that uses an item several times keeps its least restrictive
level. References to items that don't exist are not recorded; a cover that names one is refused
(``422``, path ``cover_media_id``).
"""

from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from sqlalchemy import delete, or_, select

from lore.core.db.base import Visibility
from lore.core.entities.models import Entity
from lore.core.errors import InvalidInputError
from lore.core.facts.models import EntityFact
from lore.core.history.recorder import RecordedChange
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import FieldDef
from lore.modules.media.models import MediaGalleryItem, MediaItem, MediaRef

IMAGE = "image"
MEDIA_FIELD = "media"
RICH_TEXT = "rich_text"
DERIVED = ("body", "cover", "gallery")
_RANK: dict[str, int] = {"public": 0, "spoiler": 1, "private": 2}
_TABLES = frozenset({"entities", "entity_facts", "media_gallery"})


def _stricter(a: Visibility, b: Visibility) -> Visibility:
    return a if _RANK[a] >= _RANK[b] else b


def _looser(a: Visibility, b: Visibility) -> Visibility:
    return a if _RANK[a] <= _RANK[b] else b


def images(doc: Any, level: Visibility = "public") -> Iterator[tuple[str, Visibility]]:
    """``(media id, level)`` of every ``image`` node of a rich-text document."""
    if not isinstance(doc, dict):
        return
    attrs = doc.get("attrs") or {}
    if doc.get("type") == "visibilityBlock" and attrs.get("level") in _RANK:
        level = _stricter(level, attrs["level"])
    if doc.get("type") == IMAGE and isinstance(attrs.get("mediaId"), str):
        yield attrs["mediaId"], level
    for child in doc.get("content") or ():
        yield from images(child, level)


def media_ids(value: Any) -> Iterator[str]:
    """The ids a ``media`` field value holds (one id, or a list for ``multiple`` fields)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        yield from (item for item in value if isinstance(item, str))


def _field_refs(field: FieldDef, value: Any, level: Visibility) -> Iterator[tuple[str, Visibility]]:
    if field.type == RICH_TEXT:
        yield from images(value, level)
    elif field.type == MEDIA_FIELD:
        yield from ((media_id, level) for media_id in media_ids(value))


class Refs:
    """Rebuilds the derived contexts of entities."""

    def __init__(self, context: VaultContext) -> None:
        self.context = context
        self.session = context.session
        enabled = enabled_modules(self.session, context.registry)
        self.kinds = {kind.key: kind for kind in context.registry.kinds_for(enabled)}

    def wanted(self, entity: Entity) -> dict[tuple[str, str], Visibility]:
        """``(media id, context) -> level`` of the entity's derived contexts."""
        found: dict[tuple[str, str], Visibility] = {}

        def add(pairs: Iterable[tuple[str, Visibility]], where: str) -> None:
            for media_id, level in pairs:
                key = (media_id, where)
                found[key] = _looser(found[key], level) if key in found else level

        add(images(entity.body), "body")
        kind = self.kinds.get(entity.kind)
        fields = {field.key: field for field in (kind.fields if kind else ())}
        overrides = entity.field_visibility or {}
        for key, field in fields.items():
            if field.type not in (RICH_TEXT, MEDIA_FIELD):
                continue
            level: Visibility = overrides.get(key) or field.default_visibility
            add(_field_refs(field, (entity.fields or {}).get(key), level), f"field:{key}")
        self._facts(entity, fields, add)
        if entity.cover_media_id:
            add([(entity.cover_media_id, "public")], "cover")
        gallery = self.session.execute(
            select(MediaGalleryItem.media_id, MediaGalleryItem.visibility).where(
                MediaGalleryItem.entity_id == entity.id, MediaGalleryItem.deleted_at.is_(None)
            )
        )
        add(((media_id, level) for media_id, level in gallery), "gallery")
        return found

    def _facts(self, entity: Entity, fields: dict[str, FieldDef], add: Any) -> None:
        keys = sorted(
            k for k, f in fields.items() if f.temporal and f.type in (RICH_TEXT, MEDIA_FIELD)
        )
        if not keys:
            return
        overrides = entity.field_visibility or {}
        facts = self.session.scalars(
            select(EntityFact).where(
                EntityFact.entity_id == entity.id,
                EntityFact.field_key.in_(keys),
                EntityFact.deleted_at.is_(None),
            )
        )
        for fact in facts:
            field = fields[fact.field_key]
            level = _stricter(overrides.get(field.key) or field.default_visibility, fact.visibility)
            add(_field_refs(field, fact.value, level), f"field:{field.key}")

    def rebuild(self, entity_ids: Iterable[str]) -> None:
        for entity_id in sorted(set(entity_ids)):
            entity = self.session.get(Entity, entity_id)
            if entity is None:
                continue  # purged: its refs went with it (ON DELETE CASCADE)
            wanted = self.wanted(entity)
            existing = set(
                self.session.scalars(
                    select(MediaItem.id).where(MediaItem.id.in_({m for m, _ in wanted}))
                )
            )
            self.session.execute(
                delete(MediaRef).where(
                    MediaRef.entity_id == entity_id,
                    or_(MediaRef.context.in_(DERIVED), MediaRef.context.startswith("field:")),
                )
            )
            for (media_id, where), level in sorted(wanted.items()):
                if media_id in existing:
                    self.session.add(
                        MediaRef(media_id=media_id, entity_id=entity_id, context=where,
                                 visibility=level)
                    )  # fmt: skip
        self.session.flush()


def _check_covers(context: VaultContext, changes: Sequence[RecordedChange]) -> None:
    """A changed cover must be an item that exists (in the trash too: undo may bring one
    back)."""
    covers = {
        str(change.after["cover_media_id"])
        for change in changes
        if change.table == "entities"
        and change.after is not None
        and change.after.get("cover_media_id")
        and (change.before or {}).get("cover_media_id") != change.after.get("cover_media_id")
    }
    if not covers:
        return
    found = set(context.session.scalars(select(MediaItem.id).where(MediaItem.id.in_(covers))))
    if covers - found:
        raise InvalidInputError(
            "The cover isn't a media item of this vault.",
            errors=[
                {
                    "path": "cover_media_id",
                    "code": "invalid_value",
                    "message": "No such media item.",
                }
            ],
        )


def rebuild_refs(context: VaultContext, changes: Sequence[RecordedChange]) -> None:
    """The derived hook: the entities a changeset touched get their refs rebuilt."""
    _check_covers(context, changes)
    owners = {owner for change in changes if change.table in _TABLES for owner in change.owners}
    if owners:
        Refs(context).rebuild(owners)


__all__ = ["DERIVED", "IMAGE", "MEDIA_FIELD", "Refs", "images", "media_ids", "rebuild_refs"]
