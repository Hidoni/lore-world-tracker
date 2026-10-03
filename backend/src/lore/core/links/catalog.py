"""The link types a vault offers: code-registered ones of core and the enabled modules plus the
user-defined ones (``link_type_defs``), as one catalog (``data-model.md`` §6.2).

A type is **offered** when its source and target kinds are available (``modules.md`` §1). Links
of types that aren't offered are hidden, like their entities.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lore.core.links.models import CustomLinkType
from lore.core.links.schemas import LinkTypeOut
from lore.core.modules.registry import CORE, ModuleRegistry
from lore.core.registry.types import ANY_KIND, GraphStyle, LinkTypeDef


@dataclass(frozen=True)
class LinkTypeInfo:
    definition: LinkTypeDef
    owner: str  # "core" (incl. user-defined types) or the module id
    user_defined: bool
    revision: int | None = None  # user-defined types

    @property
    def key(self) -> str:
        return self.definition.key


def custom_definition(row: CustomLinkType) -> LinkTypeDef:
    """A ``link_type_defs`` row as a ``LinkTypeDef``."""

    def kinds(value: Any) -> tuple[str, ...] | str:
        return ANY_KIND if value == ANY_KIND else tuple(value)

    graph = {"color": None, "dashed": False, "weight": 1, **row.graph}
    return LinkTypeDef(
        key=row.key,
        label=row.label,
        inverse_label=row.inverse_label,
        description=row.description,
        source_kinds=kinds(row.source_kinds),  # type: ignore[arg-type]
        target_kinds=kinds(row.target_kinds),  # type: ignore[arg-type]
        symmetric=row.symmetric,
        temporal=row.temporal,  # type: ignore[arg-type]
        unique=row.unique_policy,  # type: ignore[arg-type]
        max_targets_per_source=row.max_targets_per_source,
        max_sources_per_target=row.max_sources_per_target,
        data_schema=row.data_schema,
        graph=GraphStyle(**graph),
        archived=row.archived,
    )


def allows(side: tuple[str, ...] | str, kind: str) -> bool:
    return side == ANY_KIND or kind in side


def _offered(side: tuple[str, ...] | str, available: set[str]) -> bool:
    return side == ANY_KIND or any(kind in available for kind in side)


def link_type_out(info: LinkTypeInfo) -> LinkTypeOut:
    return LinkTypeOut.model_validate(
        {
            **asdict(info.definition),
            "module": info.owner,
            "user_defined": info.user_defined,
            "revision": info.revision,
        }
    )


class LinkTypeCatalog:
    def __init__(self, session: Session, registry: ModuleRegistry, enabled: Iterable[str]) -> None:
        enabled = frozenset(enabled)
        available = {kind.key for kind in registry.kinds_for(enabled)}
        self._offered: dict[str, LinkTypeInfo] = {
            t.definition.key: LinkTypeInfo(t.definition, t.owner, False)
            for t in registry.link_types_for(enabled)
        }
        rows = list(session.scalars(select(CustomLinkType).order_by(CustomLinkType.key)))
        for row in rows:
            definition = custom_definition(row)
            if _offered(definition.source_kinds, available) and _offered(
                definition.target_kinds, available
            ):
                self._offered[row.key] = LinkTypeInfo(definition, CORE, True, row.revision)
        self._known = registry.all_link_type_keys() | {row.key for row in rows}

    def offered(self) -> list[LinkTypeInfo]:
        return list(self._offered.values())

    def get(self, key: str) -> LinkTypeInfo | None:
        return self._offered.get(key)

    def is_known(self, key: str) -> bool:
        return key in self._known
