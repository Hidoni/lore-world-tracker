from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from lore import __version__
from lore.core.api.deps import SessionDep
from lore.core.errors import ConflictError
from lore.core.vaults import VaultManager
from tests.conftest import AppFactory, local_client

HEADERS = {"X-Lore-Client": "test"}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def app(make_app: AppFactory, data_dir: Path) -> FastAPI:
    return make_app(data_dir=data_dir)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with local_client(app, headers=HEADERS) as test_client:
        yield test_client


def create(client: TestClient, name: str = "Aetheria") -> dict[str, Any]:
    response = client.post("/api/v1/vaults", json={"name": name})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_vault_lifecycle(client: TestClient, data_dir: Path) -> None:
    assert client.get("/api/v1/vaults").json() == {"items": [], "problems": []}
    assert not (data_dir / "vaults").exists()
    vault = create(client)
    assert (data_dir / "vaults" / vault["folder"] / "vault.json").is_file()
    assert set(vault) == {
        "id", "name", "folder", "created_at", "created_by_app_version", "modified_at", "published"
    }  # fmt: skip
    assert vault["name"] == "Aetheria"
    assert vault["folder"] == f"aetheria-{vault['id'][:8]}"
    assert vault["created_by_app_version"] == __version__
    assert vault["published"] is False
    assert client.get("/api/v1/vaults").json()["items"] == [vault]
    assert client.get(f"/api/v1/vaults/{vault['id']}").json() == vault

    renamed = client.patch(f"/api/v1/vaults/{vault['id']}", json={"name": "Aetheria II"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Aetheria II"
    assert renamed.json()["folder"] == vault["folder"]

    deleted = client.delete(f"/api/v1/vaults/{vault['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    [trashed] = (data_dir / "trash").iterdir()
    assert trashed.name.startswith(vault["folder"])
    missing = client.get(f"/api/v1/vaults/{vault['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "vault_not_found"


def test_problems_are_listed(client: TestClient, data_dir: Path) -> None:
    vault = create(client)
    (data_dir / "vaults" / "broken").mkdir()
    body = client.get("/api/v1/vaults").json()
    assert [item["id"] for item in body["items"]] == [vault["id"]]
    [problem] = body["problems"]
    assert problem["folder"] == "broken"
    assert problem["code"] == "manifest_invalid"
    assert problem["vault_id"] is None


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "  "}, {"name": "a\u0000b"}, {"name": "x" * 201},
     {"name": "ok", "folder": "../../evil"}, {"name": 5}],
)  # fmt: skip
def test_invalid_bodies(client: TestClient, body: dict[str, Any]) -> None:
    response = client.post("/api/v1/vaults", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "vault_id",
    ["..%2F..%2Fetc", "..", "0190A1B2-C3D4-7E5F-8A9B-0C1D2E3F4A5B", "x" * 36, "%2e%2e"],
)
def test_malicious_ids_are_rejected(client: TestClient, vault_id: str) -> None:
    for method in ("GET", "PATCH", "DELETE"):
        response = client.request(method, f"/api/v1/vaults/{vault_id}", json={"name": "x"})
        assert response.status_code in {404, 422}, (method, response.text)


def test_unknown_id_is_not_found(client: TestClient) -> None:
    unknown = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    for method in ("GET", "PATCH", "DELETE"):
        response = client.request(method, f"/api/v1/vaults/{unknown}", json={"name": "x"})
        assert response.status_code == 404
        assert response.json()["code"] == "vault_not_found"


def test_locked_vault_conflicts(client: TestClient, data_dir: Path) -> None:
    vault = create(client)
    other = VaultManager(data_dir)
    other.open(vault["id"])
    try:
        response = client.delete(f"/api/v1/vaults/{vault['id']}")
        assert response.status_code == 409
        assert response.json()["code"] == "vault_locked"
        assert response.json()["context"]["owner"]["pid"]
    finally:
        other.close()


def test_read_only_server_refuses_vault_writes(make_app: AppFactory, data_dir: Path) -> None:
    VaultManager(data_dir).create("Aetheria")
    with local_client(make_app(data_dir=data_dir, read_only=True), headers=HEADERS) as client:
        [vault] = client.get("/api/v1/vaults").json()["items"]
        responses = [
            client.post("/api/v1/vaults", json={"name": "x"}),
            client.patch(f"/api/v1/vaults/{vault['id']}", json={"name": "x"}),
            client.delete(f"/api/v1/vaults/{vault['id']}"),
        ]
    for response in responses:
        assert response.status_code == 403
        assert response.json()["code"] == "read_only"
    assert not (data_dir / "trash").exists()


def test_shutdown_releases_locks(app: FastAPI, data_dir: Path) -> None:
    with local_client(app, headers=HEADERS) as client:
        vault = create(client)
        client.patch(f"/api/v1/vaults/{vault['id']}", json={"name": "Held"})
        assert (data_dir / "vaults" / vault["folder"] / ".lock").exists()
    assert not (data_dir / "vaults" / vault["folder"] / ".lock").exists()


def test_openapi_operations(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    operations = {
        (path, method): operation["operationId"]
        for path, methods in paths.items()
        for method, operation in methods.items()
        if path.startswith("/api/v1/vaults")
    }
    assert operations == {
        ("/api/v1/vaults", "get"): "vaults_list",
        ("/api/v1/vaults", "post"): "vaults_create",
        ("/api/v1/vaults/{vault_id}", "get"): "vaults_get",
        ("/api/v1/vaults/{vault_id}", "patch"): "vaults_update",
        ("/api/v1/vaults/{vault_id}", "delete"): "vaults_delete",
    }


# --- request-scoped sessions -----------------------------------------------------------------


@pytest.fixture
def session_app(app: FastAPI) -> FastAPI:
    """The app plus test-only vault-scoped routes that use ``SessionDep``."""
    router = APIRouter(prefix="/api/v1/vaults/{vault_id}/test")

    @router.post("/notes")
    def add_note(session: SessionDep, fail: bool = False) -> dict[str, int]:
        session.execute(text("CREATE TABLE IF NOT EXISTS notes (body TEXT)"))
        session.execute(text("INSERT INTO notes VALUES ('x')"))
        if fail:
            raise ConflictError("rolled back")
        return {"ok": 1}

    @router.get("/notes")
    def count_notes(session: SessionDep) -> dict[str, int]:
        exists: int = session.execute(
            text("SELECT count(*) FROM sqlite_master WHERE name = 'notes'")
        ).scalar_one()
        count = session.execute(text("SELECT count(*) FROM notes")).scalar_one() if exists else 0
        return {"count": count}

    @router.get("/pragmas")
    def pragmas(session: SessionDep) -> dict[str, Any]:
        return {
            "foreign_keys": session.execute(text("PRAGMA foreign_keys")).scalar_one(),
            "in_transaction": session.in_transaction(),
        }

    app.include_router(router)
    return app


def test_session_commits_on_success_and_rolls_back_on_error(session_app: FastAPI) -> None:
    with local_client(session_app, headers=HEADERS) as client:
        vault = create(client)
        base = f"/api/v1/vaults/{vault['id']}/test"
        assert client.post(f"{base}/notes").status_code == 200
        failed = client.post(f"{base}/notes", params={"fail": True})
        assert failed.status_code == 409
        assert failed.json()["detail"] == "rolled back"
        assert client.get(f"{base}/notes").json() == {"count": 1}
        assert client.get(f"{base}/pragmas").json() == {"foreign_keys": 1, "in_transaction": True}


def test_vault_scoped_routes_resolve_the_vault(session_app: FastAPI) -> None:
    with local_client(session_app, headers=HEADERS) as client:
        unknown = client.get("/api/v1/vaults/0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b/test/notes")
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "vault_not_found"
        malformed = client.get("/api/v1/vaults/NOT-A-VAULT/test/notes")
        assert malformed.status_code == 422
