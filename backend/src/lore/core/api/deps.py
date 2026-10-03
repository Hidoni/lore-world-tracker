"""Request-scoped dependencies shared by routers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy.orm import Session

from lore.config import Settings
from lore.core.vaults import OpenVault, VaultManager
from lore.core.vaults.format import VAULT_ID_PATTERN


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


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_session(request: Request, vault: VaultDep) -> Iterator[Session]:
    """One transaction per request: committed when the path operation returns, rolled back if it
    raises. ``scope="function"`` commits before the response is sent, so a failed commit is
    reported to the client. Requests that may write (anything but GET/HEAD/OPTIONS) begin with
    ``BEGIN IMMEDIATE``, so overlapping writes queue instead of failing with "database is
    locked"."""
    factory = vault.sessions if request.method in _READ_METHODS else vault.write_sessions
    with factory() as session, session.begin():
        yield session


SessionDep = Annotated[Session, Depends(get_session, scope="function")]
