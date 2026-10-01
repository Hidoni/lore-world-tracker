from fastapi.testclient import TestClient

from lore import __version__
from tests.conftest import AppFactory, local_client


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_meta_defaults(client: TestClient) -> None:
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    assert response.json() == {
        "app_version": __version__,
        "api_version": "v1",
        "read_only": False,
        "exposed_vaults": [],
        "features": [],
    }


def test_meta_reflects_reader_settings(make_app: AppFactory) -> None:
    app = make_app(read_only=True, exposed_vaults=["aetheria"])
    with local_client(app) as client:
        body = client.get("/api/v1/meta").json()
    assert body["read_only"] is True
    assert body["exposed_vaults"] == ["aetheria"]


def test_openapi_contract(client: TestClient) -> None:
    document = client.get("/api/v1/openapi.json").json()
    assert document["openapi"].startswith("3.1")
    assert document["paths"]["/api/v1/health"]["get"]["operationId"] == "system_health"
    assert document["paths"]["/api/v1/meta"]["get"]["operationId"] == "system_meta"
    default = document["paths"]["/api/v1/meta"]["get"]["responses"]["default"]
    assert set(default["content"]) == {"application/problem+json"}
    assert "HTTPValidationError" not in document["components"]["schemas"]
