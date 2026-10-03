"""Vaults: self-contained folders, each with its own SQLite database (D9, ADR-0002)."""

from lore.core.vaults.errors import VaultLockedError, VaultNotFoundError
from lore.core.vaults.format import VaultManifest, VaultName
from lore.core.vaults.manager import OpenVault, VaultInfo, VaultManager

__all__ = [
    "OpenVault",
    "VaultInfo",
    "VaultLockedError",
    "VaultManager",
    "VaultManifest",
    "VaultName",
    "VaultNotFoundError",
]
