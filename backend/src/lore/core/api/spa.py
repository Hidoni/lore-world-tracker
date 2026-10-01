"""Serving the built SPA at ``/`` with a fallback to ``index.html`` for client-side routes."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException

API_PREFIX = "api"


def spa_router(static_dir: Path) -> APIRouter:
    root = static_dir.resolve()
    index = root / "index.html"
    router = APIRouter()

    @router.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def serve(path: str) -> FileResponse:
        if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        if not index.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(index)

    return router
