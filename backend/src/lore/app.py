"""FastAPI application factory."""

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from lore import __version__
from lore.config import Settings
from lore.core.api import system
from lore.core.api.errors import (
    PROBLEM_RESPONSES,
    install_error_handlers,
    use_problem_media_type,
)
from lore.core.api.spa import spa_router

API_BASE_PATH = "/api/v1"


def operation_id(route: APIRoute) -> str:
    """Explicit OpenAPI operation ids: ``<first tag>_<route name>``, e.g. ``system_health``."""
    if route.tags:
        return f"{route.tags[0]}_{route.name}"
    return route.name


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="Lore World Tracker",
        version=__version__,
        openapi_url=f"{API_BASE_PATH}/openapi.json",
        docs_url=f"{API_BASE_PATH}/docs",
        redoc_url=None,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    install_error_handlers(app)

    api = APIRouter(prefix=API_BASE_PATH, responses=PROBLEM_RESPONSES)
    api.include_router(system.router)
    app.include_router(api)

    if settings.static_dir is not None:
        app.include_router(spa_router(settings.static_dir))

    generate_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = use_problem_media_type(generate_openapi())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


def create_app_from_env() -> FastAPI:
    """Uvicorn factory for ``--reload``, where each worker process reads the environment."""
    return create_app(Settings())
