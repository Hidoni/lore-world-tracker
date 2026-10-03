"""Vault errors (``docs/architecture/api.md`` §3)."""

from lore.core.errors import ConflictError, NotFoundError


class VaultNotFoundError(NotFoundError):
    code = "vault_not_found"
    title = "Vault not found"


class VaultLockedError(ConflictError):
    """Another author process holds the vault's lock file."""

    code = "vault_locked"
    title = "Vault locked"
