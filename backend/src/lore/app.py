"""FastAPI application factory."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from lore import __version__
from lore.config import Settings
from lore.core.api import system
from lore.core.api.deps import require_module
from lore.core.api.errors import (
    PROBLEM_RESPONSES,
    install_error_handlers,
    use_problem_media_type,
)
from lore.core.api.middleware import (
    CLIENT_HEADER,
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    HostCheckMiddleware,
    MutationGuardMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    allowed_hosts,
)
from lore.core.api.spa import spa_router
from lore.core.db import ensure_sqlite_capabilities
from lore.core.entities import router as entities_router
from lore.core.history import router as history_router
from lore.core.links import router as links_router
from lore.core.logging import configure_logging
from lore.core.models import load_metadata
from lore.core.modules import ModuleRegistry, ModuleSpec
from lore.core.modules import router as modules_router
from lore.core.vaults import VaultManager
from lore.core.vaults import router as vaults_router
from lore.modules import ALL_MODULES

API_BASE_PATH = "/api/v1"


def operation_id(route: APIRoute) -> str:
    """Explicit OpenAPI operation ids: ``<first tag>_<route name>``, e.g. ``system_health``."""
    if route.tags:
        return f"{route.tags[0]}_{route.name}"
    return route.name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Refuse to start on an unsupported SQLite build; close vaults (engines, locks) on exit."""
    ensure_sqlite_capabilities()
    try:
        yield
    finally:
        app.state.vaults.close()


def create_app(settings: Settings, modules: Sequence[ModuleSpec] | None = None) -> FastAPI:
    """The app. ``modules`` defaults to ``lore.modules.ALL_MODULES`` (tests pass their own); the
    registry is validated here, so an invalid module set fails at startup."""
    app = FastAPI(
        title="Lore World Tracker",
        version=__version__,
        openapi_url=f"{API_BASE_PATH}/openapi.json",
        docs_url=f"{API_BASE_PATH}/docs",
        redoc_url=None,
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = ModuleRegistry(
        ALL_MODULES if modules is None else modules, core_metadata=load_metadata()
    )
    app.state.vaults = VaultManager(
        settings.data_dir,
        read_only=settings.read_only,
        exposed_vaults=settings.exposed_vaults,
        auto_migrate=settings.auto_migrate,
        module_registry=app.state.registry,
    )
    install_error_handlers(app)

    api = APIRouter(prefix=API_BASE_PATH, responses=PROBLEM_RESPONSES)
    api.include_router(system.router)
    api.include_router(vaults_router.router)
    api.include_router(modules_router.router)
    api.include_router(entities_router.router)
    api.include_router(entities_router.tree_router)
    api.include_router(entities_router.trash_router)
    api.include_router(links_router.router)
    api.include_router(links_router.types_router)
    api.include_router(links_router.entity_router)
    api.include_router(history_router.router)
    api.include_router(history_router.entity_router)
    for module in app.state.registry.modules:
        for module_router in module.routers:
            # Always mounted; require_module answers 404 module_disabled per vault (§2.2).
            api.include_router(
                module_router,
                prefix=f"/vaults/{{vault_id}}/m/{module.id}",
                dependencies=[Depends(require_module(module.id))],
            )
    app.include_router(api)

    if settings.static_dir is not None:
        app.include_router(spa_router(settings.static_dir))

    generate_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = use_problem_media_type(generate_openapi())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    install_middleware(app, settings)
    return app


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add the middleware stack (``lore.core.api.middleware``). The last one added runs first."""
    hosts = allowed_hosts(settings)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(MutationGuardMiddleware, hosts=hosts, cors_origins=settings.cors_origins)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=[CLIENT_HEADER, REQUEST_ID_HEADER, "Content-Type"],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(HostCheckMiddleware, hosts=hosts)
    app.add_middleware(RequestContextMiddleware, debug=settings.debug)
    app.add_middleware(SecurityHeadersMiddleware)


def create_app_from_env() -> FastAPI:
    """Uvicorn factory for ``--reload``, where each worker process reads the environment."""
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format)
    return create_app(settings)
