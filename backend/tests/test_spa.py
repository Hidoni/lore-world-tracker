from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AppFactory, local_client


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Lore</title>")
    (root / "assets" / "app.js").write_text("console.log('lore')")
    (tmp_path / "secret.txt").write_text("outside")
    return root


@pytest.fixture
def client(make_app: AppFactory, static_dir: Path) -> TestClient:
    return local_client(make_app(static_dir=static_dir))


def test_serves_index_at_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Lore</title>" in response.text


def test_serves_static_files(client: TestClient) -> None:
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('lore')"


def test_client_routes_fall_back_to_index(client: TestClient) -> None:
    response = client.get("/vaults/abc/entities/def")
    assert response.status_code == 200
    assert "<title>Lore</title>" in response.text


def test_api_routes_still_win(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/api", "/api/v1/nope", "/api/whatever"])
def test_unknown_api_paths_are_not_found_problems(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_does_not_escape_static_dir(client: TestClient) -> None:
    response = client.get("/%2e%2e/secret.txt")
    assert "outside" not in response.text


def test_without_static_dir_root_is_not_found(make_app: AppFactory) -> None:
    response = local_client(make_app()).get("/")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_missing_index_is_not_found(make_app: AppFactory, tmp_path: Path) -> None:
    response = local_client(make_app(static_dir=tmp_path)).get("/anything")
    assert response.status_code == 404
