"""Request-scoped dependencies shared by routers."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

from lore.config import Settings
from lore.core.api.middleware import CLIENT_HEADER
from lore.core.errors import ReadOnlyError
from lore.core.history.recorder import context as history_context
from lore.core.logging import request_id_var
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.service import ModuleDisabledError, enabled_modules
from lore.core.vaults import OpenVault, VaultManager
from lore.core.vaults.format import VAULT_ID_PATTERN
from lore.core.visibility import AUTHOR, READER, VisibilityPolicy


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_vault_manager(request: Request) -> VaultManager:
    manager: VaultManager = request.app.state.vaults
    return manager


VaultManagerDep = Annotated[VaultManager, Depends(get_vault_manager)]

VaultIdPath = Annotated[str, Path(pattern=VAULT_ID_PATTERN, description="Vault id (UUID).")]


def get_vault(vault_id: VaultIdPath, manager: VaultManagerDep) -> OpenVault:
    """The opened vault of a ``/vaults/{vault_id}/…`` route (``404 vault_not_found``,
    ``409 vault_locked``)."""
    return manager.open(vault_id)


VaultDep = Annotated[OpenVault, Depends(get_vault)]


def get_writable_vault(vault: VaultDep) -> OpenVault:
    """``get_vault`` for routes that write: ``403 read_only`` on a read-only server."""
    if vault.read_only:
        raise ReadOnlyError("The server is read-only.")
    return vault


WritableVaultDep = Annotated[OpenVault, Depends(get_writable_vault)]


def get_policy(
    settings: SettingsDep,
    as_reader: Annotated[
        bool, Query(description="Apply reader filtering (preview what readers see).")
    ] = False,
) -> VisibilityPolicy:
    """The request's ``VisibilityPolicy`` (``visibility-and-sharing.md`` §3): readers on a
    read-only server or with ``?as_reader=true``, otherwise the author."""
    return READER if settings.read_only or as_reader else AUTHOR


PolicyDep = Annotated[VisibilityPolicy, Depends(get_policy)]


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The changeset origin of a request, from its X-Lore-Client header (data-model.md §7).
_ORIGINS = {"web": "ui", "cli": "cli"}


def get_session(request: Request, vault: VaultDep) -> Iterator[Session]:
    """One transaction per request: committed when the path operation returns, rolled back if it
    raises. ``scope="function"`` commits before the response is sent, so a failed commit is
    reported to the client. Requests that may write (anything but GET/HEAD/OPTIONS) begin with
    ``BEGIN IMMEDIATE``, so overlapping writes queue instead of failing with "database is
    locked"."""
    writing = request.method not in _READ_METHODS
    factory = vault.write_sessions if writing else vault.sessions
    with factory() as session, session.begin():
        history = history_context(session)
        history.origin = _ORIGINS.get(request.headers.get(CLIENT_HEADER, ""), "api")
        history.request_id = request_id_var.get()
        yield session


SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def get_module_registry(request: Request) -> ModuleRegistry:
    registry: ModuleRegistry = request.app.state.registry
    return registry


ModuleRegistryDep = Annotated[ModuleRegistry, Depends(get_module_registry)]


def require_module(module_id: str) -> Callable[..., None]:
    """A dependency for a module's routes: ``404 module_disabled`` unless the module is enabled
    for the request's vault. The app adds it to every module router it mounts."""

    def check(session: SessionDep, registry: ModuleRegistryDep) -> None:
        if module_id not in enabled_modules(session, registry):
            raise ModuleDisabledError(f"The {module_id!r} module is disabled for this vault.")

    return check
