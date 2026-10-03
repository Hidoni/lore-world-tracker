"""Vault errors (``docs/architecture/api.md`` §3)."""

from lore.core.errors import ConflictError, LoreError, NotFoundError


class VaultNotFoundError(NotFoundError):
    code = "vault_not_found"
    title = "Vault not found"


class VaultLockedError(ConflictError):
    """Another author process holds the vault's lock file."""

    code = "vault_locked"
    title = "Vault locked"


class VaultNeedsMigrationError(ConflictError):
    """The vault's schema is behind the app and auto-migration is off (or the server is
    read-only). ``POST /vaults/{v}/migrate`` upgrades it."""

    code = "vault_needs_migration"
    title = "Vault needs migration"


class VaultNewerThanAppError(ConflictError):
    """The vault was written by a newer app version (its schema revision is unknown here)."""

    code = "vault_newer_than_app"
    title = "Vault newer than app"


class VaultMigrationFailedError(LoreError):
    """Migrating the vault failed. The database was left untouched, a pre-migration backup
    exists (``context.backup``), and the vault stays unusable until the app restarts."""

    code = "vault_migration_failed"
    status = 500
    title = "Vault migration failed"
