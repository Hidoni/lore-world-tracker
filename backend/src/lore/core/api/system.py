"""System routes: liveness and server metadata (``docs/architecture/api.md`` §2, System)."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from lore import __version__
from lore.core.api.deps import SettingsDep

API_VERSION = "v1"

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class MetaResponse(BaseModel):
    app_version: str
    api_version: str
    read_only: bool
    exposed_vaults: list[str]
    features: list[str]


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/meta")
def meta(settings: SettingsDep) -> MetaResponse:
    return MetaResponse(
        app_version=__version__,
        api_version=API_VERSION,
        read_only=settings.read_only,
        exposed_vaults=list(settings.exposed_vaults),
        features=[],
    )
