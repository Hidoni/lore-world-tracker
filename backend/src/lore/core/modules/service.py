"""Per-vault module enablement (``docs/architecture/modules.md`` §4).

State lives in ``vault_meta.settings.modules.<id> = {enabled, settings}``. Every module's state
is **recorded** (from its ``default_enabled``) when a vault is created, and a module the vault
hasn't seen yet (added by a later release) is recorded the first time the author opens the
vault: changing a module's default later never changes existing vaults (decided 2026-10-03).
Only read-only servers, which never write, fall back to ``default_enabled`` for a missing entry.
A module is only effectively enabled when its dependencies are.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from lore.core.errors import ConflictError, ErrorItem, InvalidInputError, NotFoundError
from lore.core.history.recorder import RecordedChange
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


def run_derived_hooks(context: VaultContext, changes: Sequence[RecordedChange]) -> None:
    """The enabled modules' derived hooks, in registry order (``ModuleSpec.derived_hooks``)."""
    enabled = enabled_modules(context.session, context.registry)
    for module in context.registry.modules:
        if module.id in enabled:
            for hook in module.derived_hooks:
                hook(context, changes)


def run_maintenance_tasks(context: VaultContext, now: datetime) -> None:
    """The daily tasks of the enabled modules (``ModuleSpec.maintenance_tasks``)."""
    enabled = enabled_modules(context.session, context.registry)
    for module in context.registry.modules:
        if module.id in enabled:
            for task in module.maintenance_tasks:
                task(context, now)


def record_module_states(session: Session, registry: ModuleRegistry) -> list[str]:
    """Write ``{enabled: default_enabled}`` for every module without an entry. Returns their ids."""
    settings = _settings(session)
    modules = {key: dict(value) for key, value in settings.get("modules", {}).items()}
    missing = [module for module in registry.modules if module.id not in modules]
    if not missing:
        return []
    for module in missing:
        modules[module.id] = {"enabled": module.default_enabled, "settings": {}}
    set_meta(session, "settings", {**settings, "modules": modules})
    return [module.id for module in missing]


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
    # Imported here: the search indexer reads the module states through this module.
    from lore.core.search.indexer import SearchIndexer  # noqa: PLC0415

    SearchIndexer(context).reindex_for_modules([*change.enabled, *change.disabled])
    if change.enabled or change.disabled:
        # Rules (and the kinds they look at) come and go with modules (consistency.md §3.3).
        from lore.core.consistency.engine import scan  # noqa: PLC0415 (import cycle)

        scan(context)
    return change


# --- settings (ModuleSpec.settings_model) -----------------------------------------------------


def module_settings[T: BaseModel](session: Session, module_id: str, model: type[T]) -> T:
    """A module's settings in this vault: the stored ones over the model's defaults. Stored
    values the model no longer accepts (from an older release) fall back to the defaults."""
    entry = _settings(session).get("modules", {}).get(module_id)
    stored = entry.get("settings") if isinstance(entry, dict) else None
    try:
        return model.model_validate(stored if isinstance(stored, dict) else {})
    except ValidationError:
        return model()


def settings_of(session: Session, registry: ModuleRegistry, module_id: str) -> BaseModel | None:
    """``module_settings`` of a registered module, ``None`` for one without settings."""
    module = registry.get(module_id)
    if module is None:
        raise ModuleNotFoundError(f"No module {module_id!r}.")
    if module.settings_model is None:
        return None
    return module_settings(session, module_id, module.settings_model)


def set_module_settings(
    session: Session, registry: ModuleRegistry, module_id: str, changes: dict[str, Any]
) -> BaseModel:
    """Merge ``changes`` into a module's settings (``422`` when the result isn't valid, or the
    module has none)."""
    current = settings_of(session, registry, module_id)
    module = registry.get(module_id)
    if current is None or module is None or module.settings_model is None:
        raise InvalidInputError(
            f"The {module_id!r} module has no settings.",
            errors=[{"path": "settings", "code": "invalid_value", "message": "No settings."}],
        )
    try:
        updated = module.settings_model.model_validate(
            {**current.model_dump(mode="json"), **changes}
        )
    except ValidationError as error:
        items: list[ErrorItem] = [
            {
                "path": ".".join(["settings", *(str(part) for part in item["loc"])]),
                "code": "invalid_value",
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        raise InvalidInputError(f"Invalid settings for {module_id!r}.", errors=items) from None
    settings = _settings(session)
    modules = {key: dict(value) for key, value in settings.get("modules", {}).items()}
    entry = modules.get(module_id, {"enabled": module.default_enabled})
    modules[module_id] = {**entry, "settings": updated.model_dump(mode="json")}
    set_meta(session, "settings", {**settings, "modules": modules})
    session.flush()
    return updated
