"""Published snapshot routes (``docs/architecture/api.md`` §2, Vaults & settings;
``visibility-and-sharing.md`` §4).

Author-only: readers (including ``?as_reader=true``) get ``404`` for the status, and a read-only
server refuses the ``POST`` like any write."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from lore.core.api.deps import PolicyDep, SettingsDep, VaultIdPath, VaultManagerDep
from lore.core.errors import ConflictError
from lore.core.vaults.publish import last_published, publish_vault

router = APIRouter(prefix="/vaults/{vault_id}", tags=["publish"])


class PublishStatus(BaseModel):
    """Whether the server can publish (``LORE_PUBLISH_DIR`` is set) and the vault's latest
    snapshot there (``published_at`` null: none yet)."""

    available: bool
    published_at: datetime | None


class PublishNotConfiguredError(ConflictError):
    code = "publish_not_configured"
    title = "Publishing not configured"


def _status(manager: VaultManagerDep, settings: SettingsDep, vault_id: str) -> PublishStatus:
    info = manager.get(vault_id)
    if settings.publish_dir is None:
        return PublishStatus(available=False, published_at=None)
    snapshot = last_published(settings.publish_dir, info)
    return PublishStatus(
        available=True, published_at=None if snapshot is None else snapshot.published_at
    )


@router.get("/publish", name="publish_status")
def publish_status(
    vault_id: VaultIdPath, manager: VaultManagerDep, settings: SettingsDep, policy: PolicyDep
) -> PublishStatus:
    """Whether the vault can be published and when it last was."""
    policy.require_author("Publishing isn't available to readers.")
    return _status(manager, settings, vault_id)


@router.post("/publish", name="publish")
def publish(
    vault_id: VaultIdPath, manager: VaultManagerDep, settings: SettingsDep, policy: PolicyDep
) -> PublishStatus:
    """Publish a sanitized snapshot of the vault into ``LORE_PUBLISH_DIR`` (replacing the
    previous one), for a read-only server. ``409 publish_not_configured`` without a publish
    directory; ``409 publish_failed`` when the leak gate finds private data (nothing is written)."""
    policy.require_author("Publishing isn't available to readers.")
    if settings.publish_dir is None:
        raise PublishNotConfiguredError(
            "Set LORE_PUBLISH_DIR to the data directory of the read-only server."
        )
    publish_vault(manager, vault_id, settings.publish_dir)
    return _status(manager, settings, vault_id)
