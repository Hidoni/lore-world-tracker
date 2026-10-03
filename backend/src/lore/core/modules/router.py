"""Module and registry routes (``docs/architecture/api.md`` §2, Vaults & settings)."""

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict

from lore.core.api.deps import ModuleRegistryDep, SessionDep, VaultDep
from lore.core.errors import ReadOnlyError
from lore.core.links.catalog import LinkTypeCatalog, link_type_out
from lore.core.links.schemas import LinkTypeOut
from lore.core.modules.registry import ModuleRegistry, RegisteredKind
from lore.core.modules.service import enabled_modules, set_module_enabled
from lore.core.modules.spec import VaultContext

router = APIRouter(prefix="/vaults/{vault_id}")

ModuleIdPath = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*$", description="Module id.")]


class ModuleState(BaseModel):
    id: str
    name: str
    description: str
    depends_on: list[str]
    default_enabled: bool
    enabled: bool


class FieldOptionOut(BaseModel):
    key: str
    label: str
    color: str | None


class FieldOut(BaseModel):
    key: str
    label: str
    type: str
    options: list[FieldOptionOut]
    multiple: bool
    required: bool
    temporal: bool
    default_visibility: Literal["public", "spoiler", "private"]
    section: str | None
    sort: int
    help: str
    searchable: bool
    archived: bool


class KindCapabilitiesOut(BaseModel):
    has_body: bool
    can_be_multiversal: bool
    has_existence: bool
    can_have_worldline: bool
    is_time_bound: bool
    is_system: bool


class KindOut(BaseModel):
    key: str
    module: str  # "core" or the owning module id
    label: str
    plural: str
    icon: str
    color: str
    description: str
    allowed_parents: list[str]
    capabilities: KindCapabilitiesOut
    fields: list[FieldOut]


class FieldTypeOut(BaseModel):
    key: str
    label: str
    description: str


class TriggerOut(BaseModel):
    kind: Literal["record", "link_type", "field"]
    key: str


class QuickFixOut(BaseModel):
    id: str
    title: str


class RuleOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    owner: str
    title: str
    description: str
    category: Literal["structural", "narrative", "advanced_time", "module"]
    default_severity: Literal["off", "warning", "error"]
    configurable: bool
    triggers: list[TriggerOut]
    quick_fixes: list[QuickFixOut]


class Registry(BaseModel):
    """Everything the generic UI is generated from, for this vault's enabled modules."""

    kinds: list[KindOut]
    field_types: list[FieldTypeOut]
    link_types: list[LinkTypeOut]
    modules: list[ModuleState]
    consistency_rules: list[RuleOut]


class ModuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    cascade: bool = False


class ModuleUpdateResponse(BaseModel):
    enabled: list[str]  # switched on by this request (incl. auto-enabled dependencies)
    disabled: list[str]  # switched off (incl. dependents, with cascade)
    modules: list[ModuleState]


def _module_states(registry: ModuleRegistry, enabled: frozenset[str]) -> list[ModuleState]:
    return [
        ModuleState(
            id=module.id,
            name=module.name,
            description=module.description,
            depends_on=list(module.depends_on),
            default_enabled=module.default_enabled,
            enabled=module.id in enabled,
        )
        for module in registry.modules
    ]


def _kind_out(kind: RegisteredKind) -> KindOut:
    definition = asdict(kind.definition)
    definition["fields"] = [asdict(field) for field in kind.fields]
    return KindOut.model_validate({**definition, "module": kind.owner})


@router.get("/registry", name="get", tags=["registry"])
def get_registry(session: SessionDep, registry: ModuleRegistryDep) -> Registry:
    enabled = enabled_modules(session, registry)
    kinds = registry.kinds_for(enabled)
    return Registry(
        kinds=[_kind_out(kind) for kind in kinds],
        field_types=[
            FieldTypeOut.model_validate(asdict(t)) for t in registry.field_types_for(enabled)
        ],
        link_types=[
            link_type_out(info) for info in LinkTypeCatalog(session, registry, enabled).offered()
        ],
        modules=_module_states(registry, enabled),
        consistency_rules=[RuleOut.model_validate(asdict(r)) for r in registry.rules_for(enabled)],
    )


@router.patch("/modules/{module_id}", name="update", tags=["modules"])
def update_module(
    module_id: ModuleIdPath,
    body: ModuleUpdate,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> ModuleUpdateResponse:
    """Enable (also enables dependencies) or disable (``409 module_has_dependents`` while
    dependents are enabled, unless ``cascade``) a module for this vault. Data is never deleted."""
    if vault.read_only:
        raise ReadOnlyError("Modules can't be changed on a read-only server.")
    change = set_module_enabled(
        VaultContext(vault, session, registry),
        module_id,
        enabled=body.enabled,
        cascade=body.cascade,
    )
    return ModuleUpdateResponse(
        enabled=change.enabled,
        disabled=change.disabled,
        modules=_module_states(registry, enabled_modules(session, registry)),
    )
