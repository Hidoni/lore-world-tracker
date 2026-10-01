from typing import Annotated

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from lore.core.api.errors import use_problem_media_type
from lore.core.errors import ConflictError, ErrorItem, ForbiddenError, LoreError, NotFoundError
from tests.conftest import AppFactory, local_client

PROBLEM = "application/problem+json"


class TeapotError(LoreError):
    code = "teapot"
    status = 418
    title = "I'm a teapot"


@pytest.fixture
def app(make_app: AppFactory) -> FastAPI:
    app = make_app()

    @app.get("/api/v1/_test/teapot")
    def teapot() -> None:
        errors: list[ErrorItem] = [{"path": "body.kind", "code": "brewed", "message": "Steeped."}]
        raise TeapotError("No coffee here.", errors=errors, context={"pot": "blue"})

    @app.get("/api/v1/_test/missing")
    def missing() -> None:
        raise NotFoundError

    @app.get("/api/v1/_test/typed")
    def typed(limit: Annotated[int, Query(le=500)]) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/api/v1/_test/boom")
    def boom() -> None:
        raise RuntimeError("secret internals")

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return local_client(app, raise_server_exceptions=False)


def test_custom_lore_error(client: TestClient) -> None:
    response = client.get("/api/v1/_test/teapot")
    assert response.status_code == 418
    assert response.headers["content-type"] == PROBLEM
    assert response.json() == {
        "type": "urn:lore:problem:teapot",
        "title": "I'm a teapot",
        "status": 418,
        "detail": "No coffee here.",
        "code": "teapot",
        "errors": [{"path": "body.kind", "code": "brewed", "message": "Steeped."}],
        "context": {"pot": "blue"},
    }


def test_lore_error_defaults_detail_to_title(client: TestClient) -> None:
    response = client.get("/api/v1/_test/missing")
    assert response.status_code == 404
    assert response.json() == {
        "type": "urn:lore:problem:not_found",
        "title": "Not found",
        "status": 404,
        "detail": "Not found",
        "code": "not_found",
    }


def test_unknown_route_is_not_found_problem(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["type"] == "urn:lore:problem:not_found"


def test_wrong_method_is_problem(client: TestClient) -> None:
    response = client.delete("/api/v1/health", headers={"X-Lore-Client": "test"})
    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["code"] == "method_not_allowed"
    assert "GET" in response.headers["allow"]


def test_request_validation_is_problem(client: TestClient) -> None:
    response = client.get("/api/v1/_test/typed", params={"limit": "lots"})
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"] == [
        {"path": "query.limit", "code": "int_parsing", "message": body["errors"][0]["message"]}
    ]


def test_missing_parameter_is_problem(client: TestClient) -> None:
    body = client.get("/api/v1/_test/typed").json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["path"] == "query.limit"
    assert body["errors"][0]["code"] == "missing"


def test_unexpected_exception_hides_details(client: TestClient) -> None:
    response = client.get("/api/v1/_test/boom")
    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["code"] == "internal_error"
    assert "context" not in body
    assert "secret" not in response.text
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_debug_mode_includes_traceback(make_app: AppFactory) -> None:
    app = make_app(debug=True)

    @app.get("/api/v1/_test/boom")
    def boom() -> None:
        raise RuntimeError("visible internals")

    body = local_client(app).get("/api/v1/_test/boom").json()
    assert body["code"] == "internal_error"
    assert body["context"]["exception"] == "RuntimeError"
    assert "visible internals" in "".join(body["context"]["traceback"])


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [(ConflictError(), 409, "conflict"), (ForbiddenError(), 403, "forbidden")],
)
def test_error_hierarchy(error: LoreError, status: int, code: str) -> None:
    assert isinstance(error, LoreError)
    assert (error.status, error.code) == (status, code)


def test_openapi_drops_fastapi_validation_schema(app: FastAPI) -> None:
    document = app.openapi()
    operation = document["paths"]["/api/v1/_test/typed"]["get"]
    assert "422" not in operation["responses"]
    assert "HTTPValidationError" not in document["components"]["schemas"]
    assert "ValidationError" not in document["components"]["schemas"]


def test_openapi_fixup_keeps_unrelated_responses() -> None:
    document = {
        "paths": {"/x": {"get": {"responses": {"422": {"description": "custom"}}}}},
        "components": {"schemas": {}},
    }
    assert use_problem_media_type(document)["paths"]["/x"]["get"]["responses"] == {
        "422": {"description": "custom"}
    }
