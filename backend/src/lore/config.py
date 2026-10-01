"""Application settings, read once at startup from ``LORE_*`` environment variables.

The variables and their defaults are specified in ``docs/architecture/deployment.md`` §1.
"""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

type CommaList = Annotated[list[str], NoDecode]


def detect_spec_dir(start: Path | None = None) -> Path | None:
    """Return the nearest ``<ancestor>/spec`` containing ``chronology/``, if any.

    Works from a source checkout (``backend/src/lore`` → ``<repo>/spec``). Installed images set
    ``LORE_SPEC_DIR`` explicitly.
    """
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        candidate = parent / "spec"
        if (candidate / "chronology").is_dir():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LORE_", extra="ignore", frozen=True)

    data_dir: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=0, le=65535)
    read_only: bool = False
    exposed_vaults: CommaList = []
    allowed_hosts: CommaList = ["localhost", "127.0.0.1", "[::1]"]
    cors_origins: CommaList = []
    auto_migrate: bool = True
    static_dir: Path | None = None
    spec_dir: Path | None = Field(default_factory=detect_spec_dir)
    max_upload_mb: int = Field(default=50, gt=0)
    publish_dir: Path | None = None
    log_level: Literal["critical", "error", "warning", "info", "debug"] = "info"
    log_format: Literal["text", "json"] = "text"
    debug: bool = False

    @field_validator("exposed_vaults", "allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("static_dir", "spec_dir", "publish_dir", mode="before")
    @classmethod
    def _empty_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level", "log_format", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _wildcard_host_requires_read_only(self) -> Self:
        if "*" in self.allowed_hosts and not self.read_only:
            msg = "LORE_ALLOWED_HOSTS='*' is only allowed with LORE_READ_ONLY=true"
            raise ValueError(msg)
        return self
