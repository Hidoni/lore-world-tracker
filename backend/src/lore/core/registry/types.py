"""Definitions that core and modules register: kinds, fields, field types, link types and
consistency rules (``data-model.md`` §3.3, §4.1, §6.2; ``consistency.md`` §2).

These are code-level declarations (frozen dataclasses). The registry endpoint serializes them for
the generic UI; callables (rule checks) never leave the backend.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from lore.core.db.base import Visibility

type FieldTypeKey = str
type Temporal = Literal["never", "optional", "required"]
type UniquePolicy = Literal["none", "per_pair", "per_pair_per_period"]
type Severity = Literal["off", "warning", "error"]
type RuleCategory = Literal["structural", "narrative", "advanced_time", "module"]

ANY_KIND: Literal["*"] = "*"
"""``source_kinds``/``target_kinds`` value: any kind."""


@dataclass(frozen=True)
class FieldOption:
    """One choice of an ``enum``/``multi_enum`` field."""

    key: str
    label: str
    color: str | None = None


@dataclass(frozen=True)
class FieldDef:
    """A field of a kind (``data-model.md`` §4.1). Keys: unprefixed for the kind's own module,
    ``<module>.<key>`` when contributed by another module."""

    key: str
    label: str
    type: FieldTypeKey
    options: tuple[FieldOption, ...] = ()
    multiple: bool = False
    required: bool = False
    temporal: bool = False
    default_visibility: Visibility = "public"
    section: str | None = None
    sort: int = 0
    help: str = ""
    searchable: bool = True
    archived: bool = False


@dataclass(frozen=True)
class FieldContribution:
    """Fields a module adds to another module's (or core's) kind."""

    kind: str
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class FieldTypeDef:
    """A field value type (``data-model.md`` §4.2). Core provides the built-in types; a module may
    provide more (``media``)."""

    key: FieldTypeKey
    label: str
    description: str = ""


@dataclass(frozen=True)
class KindCapabilities:
    has_body: bool = True
    can_be_multiversal: bool = True
    has_existence: bool = True
    can_have_worldline: bool = False
    is_time_bound: bool = False  # events
    is_system: bool = False  # dimension / timeline / calendar


@dataclass(frozen=True)
class KindDef:
    """An entity kind (``data-model.md`` §3.3). ``allowed_parents`` lists kind keys (or
    ``"misc"``, the misc module's catch-all parent)."""

    key: str
    label: str
    plural: str
    icon: str
    color: str
    description: str = ""
    allowed_parents: tuple[str, ...] = ()
    fields: tuple[FieldDef, ...] = ()
    capabilities: KindCapabilities = field(default_factory=KindCapabilities)


@dataclass(frozen=True)
class GraphStyle:
    color: str | None = None
    dashed: bool = False
    weight: int = 1


@dataclass(frozen=True)
class LinkTypeDef:
    """A link type registered in code (``data-model.md`` §6.2). User-defined types live in the
    ``link_type_defs`` table (``lore.core.links.models.CustomLinkType``)."""

    key: str
    label: str
    inverse_label: str | None = None
    description: str = ""
    source_kinds: tuple[str, ...] | Literal["*"] = ANY_KIND
    target_kinds: tuple[str, ...] | Literal["*"] = ANY_KIND
    symmetric: bool = False
    temporal: Temporal = "optional"
    unique: UniquePolicy = "none"
    max_targets_per_source: int | None = None
    max_sources_per_target: int | None = None
    data_schema: dict[str, Any] | None = None  # JSON Schema for links.data
    graph: GraphStyle = field(default_factory=GraphStyle)
    archived: bool = False


@dataclass(frozen=True)
class Trigger:
    """What makes a rule re-check a subject: a record type, link type or field key."""

    kind: Literal["record", "link_type", "field"]
    key: str


@dataclass(frozen=True)
class QuickFixDef:
    id: str
    title: str


def _no_findings(*_args: Any) -> Iterable[Any]:
    return ()


@dataclass(frozen=True)
class RuleDef:
    """A consistency rule (``consistency.md`` §2). The engine that runs ``check``/``scan`` comes in
    M3; until then the callables receive ``(RuleContext, subjects)`` / ``(RuleContext)``."""

    id: str
    owner: str  # "core" or the module id; must match the id prefix
    title: str
    description: str
    category: RuleCategory
    default_severity: Severity
    configurable: bool = True  # False = hard rule
    triggers: tuple[Trigger, ...] = ()
    check: Callable[..., Iterable[Any]] = _no_findings
    scan: Callable[..., Iterable[Any]] = _no_findings
    quick_fixes: tuple[QuickFixDef, ...] = ()
