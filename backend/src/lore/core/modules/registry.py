"""``ModuleRegistry``: the validated set of modules plus core's definitions
(``docs/architecture/modules.md`` §2.2, §4).

The registry is static (built at startup from ``lore.modules.ALL_MODULES``); which modules are
enabled is per vault (``lore.core.modules.service``). The ``*_for(enabled)`` views give what a
vault with those modules enabled sees.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from sqlalchemy import MetaData

from lore.core.entities.extensions import (
    CORE_KIND_EXTENSIONS,
    CORE_PURGE_HOOKS,
    KindExtension,
    PurgeHook,
)
from lore.core.modules.spec import ModuleSpec
from lore.core.registry.core import CORE_FIELD_TYPES, CORE_KINDS, CORE_LINK_TYPES
from lore.core.registry.types import (
    ANY_KIND,
    FieldDef,
    FieldTypeDef,
    KindDef,
    LinkTypeDef,
    RuleDef,
)

CORE = "core"
MISC_KIND = "misc"  # the misc module's catch-all parent; always allowed in allowed_parents
RESERVED_IDS = frozenset({CORE, "custom"})

_MODULE_ID = re.compile(r"[a-z][a-z0-9_]*")
_KIND_KEY = re.compile(r"[a-z][a-z0-9_]*")
_OWN_FIELD_KEY = re.compile(r"[a-z][a-z0-9_]*")
_SUFFIX = r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*"


class RegistryError(ValueError):
    """The modules don't form a valid registry. ``problems`` lists every issue found."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("invalid module registry:\n- " + "\n- ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class RegisteredKind:
    """A kind as a vault sees it: its owner and every field (own + enabled contributions)."""

    definition: KindDef
    owner: str  # "core" or a module id
    fields: tuple[FieldDef, ...]

    @property
    def key(self) -> str:
        return self.definition.key


@dataclass(frozen=True)
class RegisteredLinkType:
    definition: LinkTypeDef
    owner: str


class ModuleRegistry:
    def __init__(
        self,
        modules: Sequence[ModuleSpec],
        *,
        core_metadata: MetaData | None = None,
        validate: bool = True,
    ) -> None:
        self.modules: tuple[ModuleSpec, ...] = tuple(modules)
        self._by_id = {module.id: module for module in self.modules}
        self.core_metadata = core_metadata
        if validate:
            self.validate()

    # --- lookups --------------------------------------------------------------------------------

    def get(self, module_id: str) -> ModuleSpec | None:
        return self._by_id.get(module_id)

    def ids(self) -> list[str]:
        return [module.id for module in self.modules]

    def dependencies(self, module_id: str) -> list[str]:
        """Transitive dependencies of a module, dependencies first."""
        ordered: list[str] = []

        def visit(current: str) -> None:
            for dependency in self._by_id[current].depends_on:
                if dependency not in ordered:
                    visit(dependency)
                    ordered.append(dependency)

        visit(module_id)
        return ordered

    def dependents(self, module_id: str) -> list[str]:
        """Modules that depend on ``module_id``, directly or transitively (registry order)."""
        return [m.id for m in self.modules if module_id in self.dependencies(m.id)]

    def effective(self, requested: dict[str, bool]) -> frozenset[str]:
        """The enabled modules: requested on (default: ``default_enabled``) with every
        dependency enabled too."""
        wanted = {m.id for m in self.modules if requested.get(m.id, m.default_enabled)}
        return frozenset(
            module_id
            for module_id in wanted
            if all(dependency in wanted for dependency in self.dependencies(module_id))
        )

    # --- per-vault views ------------------------------------------------------------------------

    def _owners(self, enabled: Iterable[str]) -> list[tuple[str, ModuleSpec | None]]:
        enabled = set(enabled)
        return [(CORE, None)] + [(m.id, m) for m in self.modules if m.id in enabled]

    def kinds_for(self, enabled: Iterable[str]) -> list[RegisteredKind]:
        owners = self._owners(enabled)
        kinds: list[RegisteredKind] = []
        for owner, module in owners:
            definitions = CORE_KINDS if module is None else module.kinds
            kinds.extend(RegisteredKind(kind, owner, kind.fields) for kind in definitions)
        by_key = {kind.key: index for index, kind in enumerate(kinds)}
        for _owner, module in owners:
            for contribution in module.field_contributions if module else ():
                index = by_key.get(contribution.kind)
                if index is not None:  # the target kind's module may be disabled
                    kind = kinds[index]
                    kinds[index] = replace(kind, fields=kind.fields + contribution.fields)
        return kinds

    def field_types_for(self, enabled: Iterable[str]) -> list[FieldTypeDef]:
        types = list(CORE_FIELD_TYPES)
        for _owner, module in self._owners(enabled):
            types.extend(module.field_types if module else ())
        return types

    def link_types_for(self, enabled: Iterable[str]) -> list[RegisteredLinkType]:
        """Code-registered link types of core and the enabled modules. A link type whose source
        or target kinds are all unavailable is hidden (``modules.md`` §1)."""
        owners = self._owners(enabled)
        available = {kind.key for kind in self.kinds_for(enabled)}
        result: list[RegisteredLinkType] = []
        for owner, module in owners:
            for link_type in CORE_LINK_TYPES if module is None else module.link_types:
                if _offered(link_type.source_kinds, available) and _offered(
                    link_type.target_kinds, available
                ):
                    result.append(RegisteredLinkType(link_type, owner))
        return result

    def rules_for(self, enabled: Iterable[str]) -> list[RuleDef]:
        rules: list[RuleDef] = []
        for _owner, module in self._owners(enabled):
            rules.extend(module.consistency_rules if module else ())
        return rules

    def kind_extensions_for(self, enabled: Iterable[str]) -> dict[str, KindExtension]:
        """The ``ext`` handler of each kind, from core and the enabled modules."""
        return {
            extension.kind: extension
            for _owner, module in self._owners(enabled)
            for extension in (CORE_KIND_EXTENSIONS if module is None else module.kind_extensions)
        }

    def purge_hooks(self) -> list[PurgeHook]:
        """Purge hooks of core and **every** module (disabled modules keep their data)."""
        return [*CORE_PURGE_HOOKS, *(hook for m in self.modules for hook in m.purge_hooks)]

    def all_link_type_keys(self) -> set[str]:
        """Keys of every code-registered link type (core and all modules, enabled or not)."""
        return {t.key for t in CORE_LINK_TYPES} | {
            t.key for module in self.modules for t in module.link_types
        }

    def all_kind_keys(self) -> set[str]:
        return {kind.key for kind in CORE_KINDS} | {
            kind.key for module in self.modules for kind in module.kinds
        }

    # --- validation -----------------------------------------------------------------------------

    def validate(self) -> None:
        """Raise ``RegistryError`` listing every problem (``modules.md`` §2.2)."""
        problems: list[str] = []
        problems += self._validate_modules()
        if not problems:  # the checks below assume sound ids and dependencies
            problems += self._validate_definitions()
            problems += self._validate_tables()
        if problems:
            raise RegistryError(problems)

    def _validate_modules(self) -> list[str]:
        problems: list[str] = []
        seen: set[str] = set()
        for module in self.modules:
            if not _MODULE_ID.fullmatch(module.id):
                problems.append(f"module id {module.id!r} must match ^[a-z][a-z0-9_]*$")
            if module.id in RESERVED_IDS:
                problems.append(f"module id {module.id!r} is reserved")
            if module.id in seen:
                problems.append(f"duplicate module id {module.id!r}")
            seen.add(module.id)
            for dependency in module.depends_on:
                if dependency not in self._by_id:
                    problems.append(f"{module.id}: unknown dependency {dependency!r}")
        if not problems:
            problems += self._find_cycles()
        return problems

    def _find_cycles(self) -> list[str]:
        state: dict[str, str] = {}  # visiting | done
        problems: list[str] = []

        def visit(module_id: str, path: list[str]) -> None:
            if state.get(module_id) == "done":
                return
            if state.get(module_id) == "visiting":
                cycle = [*path[path.index(module_id) :], module_id]
                problems.append("dependency cycle: " + " -> ".join(cycle))
                return
            state[module_id] = "visiting"
            for dependency in self._by_id[module_id].depends_on:
                visit(dependency, [*path, module_id])
            state[module_id] = "done"

        for module in self.modules:
            visit(module.id, [])
        return problems

    def _owners_all(self) -> list[tuple[str, ModuleSpec | None]]:
        return [(CORE, None)] + [(m.id, m) for m in self.modules]

    def _validate_definitions(self) -> list[str]:
        field_types, problems = self._validate_field_types()
        fields_by_kind: dict[str, set[str]] = {}
        problems += self._validate_kinds(field_types, fields_by_kind)
        problems += self._validate_contributions(field_types, fields_by_kind)
        problems += self._validate_link_types()
        problems += self._validate_rules()
        problems += self._validate_kind_extensions()
        return problems

    def _validate_field_types(self) -> tuple[dict[str, str], list[str]]:
        problems: list[str] = []
        owners: dict[str, str] = {t.key: CORE for t in CORE_FIELD_TYPES}
        for module in self.modules:
            for field_type in module.field_types:
                if field_type.key in owners:
                    problems.append(
                        f"{module.id}: field type {field_type.key!r} is already provided by "
                        f"{owners[field_type.key]}"
                    )
                owners[field_type.key] = module.id
        return owners, problems

    def _validate_kinds(
        self, field_types: dict[str, str], fields_by_kind: dict[str, set[str]]
    ) -> list[str]:
        problems: list[str] = []
        known = self.all_kind_keys()
        owners: dict[str, str] = {}
        for owner, module in self._owners_all():
            for kind in CORE_KINDS if module is None else module.kinds:
                where = f"{owner}: kind {kind.key!r}"
                if not _KIND_KEY.fullmatch(kind.key):
                    problems.append(f"{where}: keys must match ^[a-z][a-z0-9_]*$")
                if kind.key in owners:
                    problems.append(f"{where} is already registered by {owners[kind.key]}")
                owners[kind.key] = owner
                problems += [
                    f"{where}: unknown allowed parent kind {parent!r}"
                    for parent in kind.allowed_parents
                    if parent != MISC_KIND and parent not in known
                ]
                keys = fields_by_kind.setdefault(kind.key, set())
                for field in kind.fields:
                    if not _OWN_FIELD_KEY.fullmatch(field.key):
                        problems.append(
                            f"{where}: own field {field.key!r} must be unprefixed "
                            "(^[a-z][a-z0-9_]*$)"
                        )
                    problems += _check_field(where, field, keys, field_types)
        return problems

    def _validate_contributions(
        self, field_types: dict[str, str], fields_by_kind: dict[str, set[str]]
    ) -> list[str]:
        problems: list[str] = []
        known = self.all_kind_keys()
        for module in self.modules:
            for contribution in module.field_contributions:
                where = f"{module.id}: field contribution to {contribution.kind!r}"
                if contribution.kind not in known:
                    problems.append(f"{where}: unknown kind")
                    continue
                keys = fields_by_kind.setdefault(contribution.kind, set())
                for field in contribution.fields:
                    if not re.fullmatch(re.escape(module.id) + r"\.[a-z][a-z0-9_]*", field.key):
                        problems.append(
                            f"{where}: field {field.key!r} must be named {module.id}.<key>"
                        )
                    problems += _check_field(where, field, keys, field_types)
        return problems

    def _validate_link_types(self) -> list[str]:
        problems: list[str] = []
        known = self.all_kind_keys()
        owners: dict[str, str] = {}
        for owner, module in self._owners_all():
            for link_type in CORE_LINK_TYPES if module is None else module.link_types:
                where = f"{owner}: link type {link_type.key!r}"
                problems += _check_prefix(where, "keys", link_type.key, owner)
                if link_type.key in owners:
                    problems.append(f"{where} is already registered by {owners[link_type.key]}")
                owners[link_type.key] = owner
                for side in (link_type.source_kinds, link_type.target_kinds):
                    if side != ANY_KIND:
                        problems += [
                            f"{where}: unknown kind {kind!r}" for kind in side if kind not in known
                        ]
        return problems

    def _validate_rules(self) -> list[str]:
        problems: list[str] = []
        owners: dict[str, str] = {}
        for module in self.modules:
            for rule in module.consistency_rules:
                where = f"{module.id}: rule {rule.id!r}"
                problems += _check_prefix(where, "ids", rule.id, module.id)
                if rule.owner != module.id:
                    problems.append(f"{where}: owner is {rule.owner!r}, expected {module.id!r}")
                if rule.id in owners:
                    problems.append(f"{where} is already registered by {owners[rule.id]}")
                owners[rule.id] = module.id
        return problems

    def _validate_kind_extensions(self) -> list[str]:
        problems: list[str] = []
        known = self.all_kind_keys()
        owners: dict[str, str] = {e.kind: CORE for e in CORE_KIND_EXTENSIONS}
        for module in self.modules:
            for extension in module.kind_extensions:
                where = f"{module.id}: kind extension for {extension.kind!r}"
                if extension.kind not in known:
                    problems.append(f"{where}: unknown kind")
                if extension.kind in owners:
                    problems.append(f"{where}: the kind already has one ({owners[extension.kind]})")
                owners[extension.kind] = module.id
        return problems

    def _validate_tables(self) -> list[str]:
        problems: list[str] = []
        core_tables = set(self.core_metadata.tables) if self.core_metadata is not None else set()
        table_owner: dict[str, str] = {}
        for module in self.modules:
            for model in module.models:
                table = getattr(model, "__table__", None)
                if table is None:
                    problems.append(f"{module.id}: {model.__name__} is not a mapped table model")
                    continue
                name = table.name
                if not name.startswith(module.id + "_"):
                    problems.append(
                        f"{module.id}: table {name!r} must be prefixed {module.id + '_'!r}"
                    )
                if name in core_tables:
                    problems.append(f"{module.id}: table {name!r} is a core table")
                if name in table_owner:
                    problems.append(f"{module.id}: table {name!r} is also defined by "
                                    f"{table_owner[name]}")  # fmt: skip
                table_owner[name] = module.id
        for name in core_tables:
            for module in self.modules:
                if name.startswith(module.id + "_"):
                    problems.append(f"core table {name!r} uses module {module.id!r}'s prefix")
        return problems


def _check_field(
    where: str, field: FieldDef, keys: set[str], field_types: dict[str, str]
) -> list[str]:
    problems: list[str] = []
    if field.key in keys:
        problems.append(f"{where}: duplicate field {field.key!r}")
    keys.add(field.key)
    if field.type not in field_types:
        problems.append(f"{where}: field {field.key!r} has unknown type {field.type!r}")
    if field.type in {"enum", "multi_enum"} and not field.options:
        problems.append(f"{where}: field {field.key!r} needs options")
    return problems


def _check_prefix(where: str, what: str, key: str, owner: str) -> list[str]:
    if re.fullmatch(re.escape(owner) + r"\." + _SUFFIX, key):
        return []
    return [f"{where}: {what} must start with {owner + '.'!r}"]


def _offered(side: tuple[str, ...] | str, available: set[str]) -> bool:
    return side == ANY_KIND or any(kind in available for kind in side)
