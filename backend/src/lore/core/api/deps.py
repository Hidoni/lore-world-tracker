"""Request-scoped dependencies shared by routers."""

from typing import Annotated

from fastapi import Depends, Request

from lore.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]
