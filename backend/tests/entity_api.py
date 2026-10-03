"""Helpers for entity API tests: a client per vault and problem assertions."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.app import create_app
from lore.config import Settings
from lore.core.modules import ModuleSpec
from tests import entity_modules
from tests.conftest import local_client
from tests.entity_modules import ENTITY_MODULES

HEADERS = {"X-Lore-Client": "test"}


def make_client(
    tmp_path: Path, modules: tuple[ModuleSpec, ...] = ENTITY_MODULES, **settings: Any
) -> TestClient:
    app = create_app(Settings(data_dir=tmp_path, **settings), modules=modules)
    return local_client(app, headers=HEADERS)


class Api:
    """Requests against one vault."""

    def __init__(self, client: TestClient, vault_id: str | None = None) -> None:
        self.client = client
        self.vault = vault_id or client.post("/api/v1/vaults", json={"name": "W"}).json()["id"]
        self.base = f"/api/v1/vaults/{self.vault}"

    def create(self, kind: str, name: str = "Thing", **body: Any) -> Any:
        return self.client.post(f"{self.base}/entities", json={"kind": kind, "name": name, **body})

    def make(self, kind: str, name: str = "Thing", **body: Any) -> dict[str, Any]:
        response = self.create(kind, name, **body)
        assert response.status_code == 201, response.json()
        entity: dict[str, Any] = response.json()["entity"]
        return entity

    def get(self, entity_id: str) -> Any:
        return self.client.get(f"{self.base}/entities/{entity_id}")

    def patch(self, entity: dict[str, Any], **body: Any) -> Any:
        body.setdefault("revision", entity["revision"])
        return self.client.patch(f"{self.base}/entities/{entity['id']}", json=body)

    def delete(self, entity_id: str, *, purge: bool = False) -> Any:
        params = {"purge": "true"} if purge else {}
        return self.client.delete(f"{self.base}/entities/{entity_id}", params=params)

    def restore(self, entity_id: str) -> Any:
        return self.client.post(f"{self.base}/entities/{entity_id}/restore")

    def modules(self, module_id: str, **body: Any) -> Any:
        return self.client.patch(f"{self.base}/modules/{module_id}", json=body)


def problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.json()
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


def invalid(response: Any) -> list[str]:
    """Assert a ``422 validation_error``; return the error paths."""
    return [error["path"] for error in problem(response, 422, "validation_error")["errors"]]


def new_app(tmp_path: Path) -> FastAPI:
    """An app with the entity test modules (their hook records cleared)."""
    entity_modules.EXT_STORE.clear()
    entity_modules.PURGED.clear()
    return create_app(Settings(data_dir=tmp_path), modules=ENTITY_MODULES)
