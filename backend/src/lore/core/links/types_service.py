"""User-defined link types (``link_type_defs``, keys ``custom.<slug>``): create, edit, archive,
delete (``data-model.md`` §6.2). Decided 2026-10-04:

- Deleting a type that links still use (trashed ones included) is refused (``409 conflict``,
  ``context.links``): archive it instead. Archived types keep their links (shown and editable)
  but take no new ones.
- An edit that existing links would break is refused (``409 conflict``,
  ``context.conflicts: {<rule>: <count>}``): narrower kinds, a stricter uniqueness, a lower
  maximum, a temporal policy or data schema the links don't meet. ``symmetric`` can't change
  once the type has links.
"""

import re
from collections import Counter
from typing import Any

from jsonschema import Draft202012Validator, SchemaError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from lore.core.db.types import utc_now
from lore.core.entities.errors import RevisionConflictError
from lore.core.entities.models import Entity, fold_text
from lore.core.errors import (
    ConflictError,
    ErrorItem,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
)
from lore.core.links.catalog import (
    LinkTypeCatalog,
    LinkTypeInfo,
    allows,
    custom_definition,
    link_type_out,
)
from lore.core.links.models import CustomLinkType, Link
from lore.core.links.schemas import (
    LinkTypeCreate,
    LinkTypeDeleted,
    LinkTypeList,
    LinkTypeOut,
    LinkTypeUpdate,
)
from lore.core.links.service import data_errors
from lore.core.modules.registry import CORE, ModuleRegistry
from lore.core.modules.service import enabled_modules
from lore.core.registry.types import ANY_KIND, LinkTypeDef

CUSTOM_PREFIX = "custom."
_EDITABLE = (
    "label",
    "inverse_label",
    "description",
    "source_kinds",
    "target_kinds",
    "symmetric",
    "temporal",
    "unique",
    "max_targets_per_source",
    "max_sources_per_target",
    "data_schema",
    "graph",
    "archived",
)


def _error(path: str, message: str) -> ErrorItem:
    return {"path": path, "code": "invalid_value", "message": message}


def key_from_label(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", fold_text(label)).strip("_")
    if not slug:
        slug = "type"
    elif slug[0].isdigit():
        slug = "t_" + slug
    return CUSTOM_PREFIX + slug[:60].rstrip("_")


class LinkTypeService:
    def __init__(self, session: Session, registry: ModuleRegistry) -> None:
        self.session = session
        self.registry = registry

    def list(self) -> LinkTypeList:
        catalog = LinkTypeCatalog(
            self.session, self.registry, enabled_modules(self.session, self.registry)
        )
        return LinkTypeList(items=[link_type_out(info) for info in catalog.offered()])

    def create(self, data: LinkTypeCreate) -> LinkTypeOut:
        key = data.key or self._free_key(key_from_label(data.label))
        if self.session.get(CustomLinkType, key) is not None:
            raise ConflictError(f"The link type {key!r} already exists.")
        row = CustomLinkType(key=key)
        self._assign(
            row,
            data,
            set(_EDITABLE)
            & (
                data.model_fields_set
                | {
                    "label",
                    "symmetric",
                    "source_kinds",
                    "target_kinds",
                    "temporal",
                    "unique",
                    "graph",
                }
            ),
        )
        self.session.add(row)
        self.session.flush()
        return self._row_out(row)

    def update(self, key: str, data: LinkTypeUpdate) -> LinkTypeOut:
        row = self._load(key)
        if data.revision != row.revision:
            raise RevisionConflictError(
                f"The link type was changed meanwhile (revision {row.revision}, the edit is "
                f"based on {data.revision}).",
                context={"current": self._row_out(row).model_dump(mode="json")},
            )
        sent = data.model_fields_set & set(_EDITABLE)
        for member in ("label", "symmetric", "archived"):
            if member in sent and getattr(data, member) is None:
                raise InvalidInputError(
                    f"{member} can't be null.", errors=[_error(member, "can't be null")]
                )
        before = custom_definition(row)
        if sent:
            row.updated_at = utc_now()  # first: one UPDATE even if a query autoflushes
        self._assign(row, data, sent)
        conflicts = self.conflicts(before, custom_definition(row))
        if conflicts:
            raise ConflictError(
                "Existing links don't allow this change: "
                + ", ".join(f"{rule} ({count})" for rule, count in conflicts.items()),
                context={"conflicts": conflicts},
            )
        self.session.flush()
        return self._row_out(row)

    def delete(self, key: str) -> LinkTypeDeleted:
        row = self._load(key)
        used = (
            self.session.scalar(select(func.count()).select_from(Link).where(Link.link_type == key))
            or 0
        )
        if used:
            raise ConflictError(
                f"{used} links use this type (trashed ones included): archive it instead.",
                context={"links": used},
            )
        self.session.delete(row)
        self.session.flush()
        return LinkTypeDeleted(key=key)

    # --- helpers --------------------------------------------------------------------------------

    def _load(self, key: str) -> CustomLinkType:
        row = self.session.get(CustomLinkType, key)
        if row is not None:
            return row
        if key in self.registry.all_link_type_keys():
            raise ForbiddenError("Built-in link types can't be changed.")
        raise NotFoundError(f"No link type {key!r}.")

    def _free_key(self, base: str) -> str:
        taken = set(
            self.session.scalars(
                select(CustomLinkType.key).where(CustomLinkType.key.like(base + "%"))
            )
        )
        if base not in taken:
            return base
        suffix = 2
        while f"{base}_{suffix}" in taken:
            suffix += 1
        return f"{base}_{suffix}"

    def _kinds(self, value: Any, path: str) -> Any:
        if value == ANY_KIND:
            return ANY_KIND
        known = self.registry.all_kind_keys()
        unknown = [f"{path}.{i}" for i, kind in enumerate(value) if kind not in known]
        if unknown:
            raise InvalidInputError(
                "Unknown kinds.", errors=[_error(p, "unknown kind") for p in unknown]
            )
        return list(dict.fromkeys(value))

    def _assign(
        self, row: CustomLinkType, data: LinkTypeCreate | LinkTypeUpdate, sent: set[str]
    ) -> None:
        if "data_schema" in sent and data.data_schema is not None:
            try:
                Draft202012Validator.check_schema(data.data_schema)
            except SchemaError as exc:
                raise InvalidInputError(
                    "The data schema is invalid.", errors=[_error("data_schema", exc.message)]
                ) from exc
        for member in sent:
            value = getattr(data, member)
            if member in {"source_kinds", "target_kinds"}:
                value = self._kinds(value, member)
            elif member == "graph":
                value = {
                    **value.model_dump(),
                    "color": value.color.lower() if value.color else None,
                }
            column = "unique_policy" if member == "unique" else member
            setattr(row, column, value)

    def conflicts(self, before: LinkTypeDef, after: LinkTypeDef) -> dict[str, int]:
        """How many existing (not trashed) links break each rule of ``after``."""
        source, target = aliased(Entity), aliased(Entity)
        rows = self.session.execute(
            select(
                Link.source_id,
                Link.target_id,
                source.kind,
                target.kind,
                Link.timeline_id,
                Link.data,
            )
            .join(source, source.id == Link.source_id)
            .join(target, target.id == Link.target_id)
            .where(Link.link_type == after.key, Link.deleted_at.is_(None))
        ).all()
        conflicts: dict[str, int] = {}

        def note(rule: str, count: int) -> None:
            if count:
                conflicts[rule] = count

        if before.symmetric != after.symmetric:
            note(
                "symmetric",
                self.session.scalar(
                    select(func.count()).select_from(Link).where(Link.link_type == after.key)
                )
                or 0,
            )

        def fits(s: str, t: str) -> bool:
            ok = allows(after.source_kinds, s) and allows(after.target_kinds, t)
            return ok or (
                after.symmetric and allows(after.source_kinds, t) and allows(after.target_kinds, s)
            )

        note("kinds", sum(not fits(r[2], r[3]) for r in rows))
        if after.temporal == "never":
            note("temporal", sum(r[4] is not None for r in rows))
        elif after.temporal == "required":
            note("temporal", sum(r[4] is None for r in rows))
        if after.unique != "none":
            counted = [r for r in rows if after.unique == "per_pair" or r[4] is None]
            pairs = Counter((r[0], r[1]) for r in counted)
            note("unique", sum(count - 1 for count in pairs.values() if count > 1))
        timeless = [r for r in rows if r[4] is None]
        for rule, limit, position in (
            ("max_targets_per_source", after.max_targets_per_source, 0),
            ("max_sources_per_target", after.max_sources_per_target, 1),
        ):
            if limit is None:
                continue
            per_entity: Counter[str] = Counter()
            for r in timeless:
                if after.symmetric:
                    per_entity.update({r[0], r[1]})
                else:
                    per_entity[r[position]] += 1
            note(rule, sum(1 for count in per_entity.values() if count > limit))
        if after.data_schema is not None and after.data_schema != before.data_schema:
            note("data_schema", sum(bool(data_errors(after.data_schema, r[5])) for r in rows))
        return conflicts

    def _row_out(self, row: CustomLinkType) -> LinkTypeOut:
        return link_type_out(LinkTypeInfo(custom_definition(row), CORE, True, row.revision))
