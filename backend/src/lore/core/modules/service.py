"""Per-vault module enablement (``docs/architecture/modules.md`` §4).

State lives in ``vault_meta.settings.modules.<id> = {enabled, settings}``. A module without an
entry uses its ``default_enabled``, so a module added in a later release follows its default in
existing vaults. A module is only effectively enabled when its dependencies are.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from lore.core.errors import ConflictError, NotFoundError
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.vaults.meta import get_meta, set_meta


class ModuleNotFoundError(NotFoundError):
    code = "module_not_found"
    title = "Module not found"


class ModuleDisabledError(NotFoundError):
    """A route or record belongs to a module that is disabled for this vault."""

    code = "module_disabled"
    title = "Module disabled"


class ModuleHasDependentsError(ConflictError):
    """Disabling a module whose enabled dependents would break; retry with ``cascade``."""

    code = "module_has_dependents"
    title = "Module has enabled dependents"


@dataclass(frozen=True)
class ModuleChange:
    enabled: list[str]  # modules switched on by this request (the module and its dependencies)
    disabled: list[str]  # modules switched off (the module and, with cascade, its dependents)


def _settings(session: Session) -> dict[str, Any]:
    settings = get_meta(session, "settings")
    return dict(settings) if isinstance(settings, dict) else {}


def requested_states(session: Session) -> dict[str, bool]:
    modules = _settings(session).get("modules", {})
    return {
        module_id: bool(entry.get("enabled"))
        for module_id, entry in modules.items()
        if isinstance(entry, dict) and "enabled" in entry
    }


def enabled_modules(session: Session, registry: ModuleRegistry) -> frozenset[str]:
    return registry.effective(requested_states(session))


def set_module_enabled(
    context: VaultContext, module_id: str, *, enabled: bool, cascade: bool = False
) -> ModuleChange:
    registry, session = context.registry, context.session
    if registry.get(module_id) is None:
        raise ModuleNotFoundError(f"No module {module_id!r}.")
    before = enabled_modules(session, registry)
    if enabled:
        targets = [*registry.dependencies(module_id), module_id]
    else:
        dependents = [m for m in registry.dependents(module_id) if m in before]
        if dependents and not cascade:
            raise ModuleHasDependentsError(
                f"Disable {', '.join(dependents)} first, or pass cascade: true.",
                context={"dependents": dependents},
            )
        targets = [module_id, *dependents]

    settings = _settings(session)
    modules = {key: dict(value) for key, value in settings.get("modules", {}).items()}
    for target in targets:
        modules[target] = {**modules.get(target, {"settings": {}}), "enabled": enabled}
    set_meta(session, "settings", {**settings, "modules": modules})
    session.flush()

    after = enabled_modules(session, registry)
    change = ModuleChange(
        enabled=[m for m in registry.ids() if m in after and m not in before],
        disabled=[m for m in registry.ids() if m in before and m not in after],
    )
    for switched_on in change.enabled:
        hook = registry.get(switched_on).on_enable  # type: ignore[union-attr]
        if hook is not None:
            hook(context)
    for switched_off in change.disabled:
        hook = registry.get(switched_off).on_disable  # type: ignore[union-attr]
        if hook is not None:
            hook(context)
    return change
