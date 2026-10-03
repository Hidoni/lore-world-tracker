"""The static module system (ADR-0005, ``docs/architecture/modules.md``)."""

from lore.core.modules.registry import ModuleRegistry, RegisteredKind, RegistryError
from lore.core.modules.service import (
    ModuleChange,
    ModuleDisabledError,
    ModuleHasDependentsError,
    enabled_modules,
    set_module_enabled,
)
from lore.core.modules.spec import ModuleSpec, VaultContext

__all__ = [
    "ModuleChange",
    "ModuleDisabledError",
    "ModuleHasDependentsError",
    "ModuleRegistry",
    "ModuleSpec",
    "RegisteredKind",
    "RegistryError",
    "VaultContext",
    "enabled_modules",
    "set_module_enabled",
]
