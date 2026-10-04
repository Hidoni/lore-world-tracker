"""Vault settings (``vault_meta.settings``, ``data-model.md`` §2): the parts with an API so far.

``settings`` also holds module states (``lore.core.modules.service``) and, later, consistency
severities and display preferences; updates here only touch their own sections. Settings aren't
world data: history doesn't record them.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from lore.core.db.base import Visibility
from lore.core.vaults.meta import get_meta, set_meta


class BackupSchedule(BaseModel):
    """Scheduled backups (``persistence-and-migrations.md`` §5): every ``every_hours`` hours
    while the app runs (0 = off), keeping the newest ``keep``."""

    model_config = ConfigDict(extra="forbid")

    every_hours: int = Field(default=24, ge=0, le=8760)
    keep: int = Field(default=7, ge=1, le=1000)
    include_media: bool = True


class VaultDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility = Field(default="public", description="Of new content.")


class VaultSettings(BaseModel):
    defaults: VaultDefaults = Field(default_factory=VaultDefaults)
    backups: BackupSchedule = Field(default_factory=BackupSchedule)


class BackupScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    every_hours: int | None = Field(default=None, ge=0, le=8760)
    keep: int | None = Field(default=None, ge=1, le=1000)
    include_media: bool | None = None


class VaultDefaultsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility | None = None


class VaultSettingsUpdate(BaseModel):
    """Members sent are merged into the stored settings."""

    model_config = ConfigDict(extra="forbid")

    defaults: VaultDefaultsUpdate | None = None
    backups: BackupScheduleUpdate | None = None


def _stored(session: Session) -> dict[str, Any]:
    value = get_meta(session, "settings")
    # A copy: assigning the stored object back wouldn't be detected as a change.
    return dict(value) if isinstance(value, dict) else {}


def _section[M: BaseModel](model: type[M], value: Any) -> M:
    """A stored section, falling back to the defaults when it is missing or invalid."""
    if isinstance(value, dict):
        try:
            return model.model_validate(value)
        except ValidationError:
            pass
    return model()


def read_settings(session: Session) -> VaultSettings:
    stored = _stored(session)
    return VaultSettings(
        defaults=_section(VaultDefaults, stored.get("defaults")),
        backups=_section(BackupSchedule, stored.get("backups")),
    )


def update_settings(session: Session, update: VaultSettingsUpdate) -> VaultSettings:
    stored = _stored(session)
    current = read_settings(session)
    if update.defaults is not None:
        changes = update.defaults.model_dump(exclude_none=True)
        stored["defaults"] = current.defaults.model_copy(update=changes).model_dump()
    if update.backups is not None:
        changes = update.backups.model_dump(exclude_none=True)
        stored["backups"] = current.backups.model_copy(update=changes).model_dump()
    set_meta(session, "settings", stored)
    return read_settings(session)
