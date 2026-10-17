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
from lore.core.vaults.static_site import export_site, site_exported_at, static_site

router = APIRouter(prefix="/vaults/{vault_id}", tags=["publish"])


class PublishStatus(BaseModel):
    """Whether the server can publish (``LORE_PUBLISH_DIR`` is set) and the vault's latest
    snapshot there (``published_at`` null: none yet); whether it can also export the snapshot as
    a static site (``LORE_STATIC_DIR``: the SPA build) and where the latest one is."""

    available: bool
    published_at: datetime | None
    static_available: bool = False
    static_exported_at: datetime | None = None
    static_path: str | None = None


class PublishNotConfiguredError(ConflictError):
    code = "publish_not_configured"
    title = "Publishing not configured"


def _status(manager: VaultManagerDep, settings: SettingsDep, vault_id: str) -> PublishStatus:
    info = manager.get(vault_id)
    if settings.publish_dir is None:
        return PublishStatus(available=False, published_at=None)
    snapshot = last_published(settings.publish_dir, info)
    site = static_site(settings.publish_dir, info)
    exported = site_exported_at(site)
    return PublishStatus(
        available=True,
        published_at=None if snapshot is None else snapshot.published_at,
        static_available=settings.static_dir is not None,
        static_exported_at=exported,
        static_path=None if exported is None else str(site),
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


class StaticExportNotConfiguredError(ConflictError):
    code = "static_export_not_configured"
    title = "Static export not configured"


@router.post("/publish/static", name="publish_static")
def publish_static(
    vault_id: VaultIdPath, manager: VaultManagerDep, settings: SettingsDep, policy: PolicyDep
) -> PublishStatus:
    """Export the vault's latest published snapshot as a static site (``visibility-and-sharing.md``
    §8) into ``LORE_PUBLISH_DIR/static/<vault folder>/``, replacing the previous one: any static
    host serves that folder. ``409 static_export_not_configured`` without a publish directory or
    the SPA build (``LORE_STATIC_DIR``), ``409 static_export_failed`` without a snapshot."""
    policy.require_author("Publishing isn't available to readers.")
    if settings.publish_dir is None or settings.static_dir is None:
        raise StaticExportNotConfiguredError(
            "Set LORE_PUBLISH_DIR and LORE_STATIC_DIR (the app's build) to export a static site."
        )
    export_site(settings.publish_dir, manager.get(vault_id), settings.static_dir)
    return _status(manager, settings, vault_id)
