from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from lore.config import Settings
from lore.core.api.middleware import (
    CONTENT_SECURITY_POLICY,
    MAX_JSON_BODY_BYTES,
    allowed_hosts,
    normalize_host,
)
from tests.conftest import AppFactory, local_client

CLIENT = {"X-Lore-Client": "test"}


class Echo(BaseModel):
    value: str


def add_test_routes(app: FastAPI) -> FastAPI:
    @app.post("/api/v1/_test/echo")
    def echo(body: Echo) -> Echo:
        return body

    @app.post("/api/v1/_test/raw")
    async def raw(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    return app


@pytest.fixture
def app(make_app: AppFactory) -> FastAPI:
    return add_test_routes(make_app())


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return local_client(app)


# --- Host allowlist --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:8000", "127.0.0.1:5173", "[::1]:8000", "LOCALHOST"]
)
def test_allowed_hosts_pass(client: TestClient, host: str) -> None:
    response = client.get("/api/v1/health", headers={"Host": host})
    assert response.status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "localhost.evil.example"])
def test_wrong_host_rejected(client: TestClient, host: str) -> None:
    response = client.get("/api/v1/health", headers={"Host": host})
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "invalid_host"


def test_wrong_host_rejected_for_spa_too(make_app: AppFactory) -> None:
    client = TestClient(make_app())  # Host: testserver
    response = client.get("/")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_host"


def test_wildcard_host_refused_in_author_mode() -> None:
    with pytest.raises(ValueError, match="LORE_READ_ONLY"):
        Settings(allowed_hosts=["*"])


def test_wildcard_host_allowed_in_read_only_mode(make_app: AppFactory) -> None:
    client = TestClient(
        make_app(read_only=True, allowed_hosts=["*"]), base_url="http://lore.example"
    )
    assert client.get("/api/v1/health").status_code == 200


def test_configured_bind_host_is_allowed(make_app: AppFactory) -> None:
    client = TestClient(make_app(host="lore.lan"), base_url="http://lore.lan:8000")
    assert client.get("/api/v1/health").status_code == 200


def test_allowed_hosts_normalization() -> None:
    hosts = allowed_hosts(Settings(allowed_hosts=["Example.COM", "::1"], host="0.0.0.0"))
    assert hosts == {"example.com", "[::1]"}
    assert normalize_host("[::1]:8000") == "[::1]"
    assert normalize_host("[::1") == "[::1"
    assert normalize_host("127.0.0.1:80") == "127.0.0.1"


# --- Mutation guard --------------------------------------------------------------------------


def test_post_without_client_header_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/_test/echo", json={"value": "x"})
    assert response.status_code == 403
    assert response.json()["code"] == "missing_client_header"


def test_post_with_unknown_client_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/_test/echo", json={"value": "x"}, headers={"X-Lore-Client": "evil"}
    )
    assert response.json()["code"] == "missing_client_header"


@pytest.mark.parametrize("client_name", ["web", "cli", "test"])
def test_post_with_client_header_accepted(client: TestClient, client_name: str) -> None:
    response = client.post(
        "/api/v1/_test/echo", json={"value": "x"}, headers={"X-Lore-Client": client_name}
    )
    assert response.status_code == 200
    assert response.json() == {"value": "x"}


@pytest.mark.parametrize(
    "origin", ["http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:8000"]
)
def test_post_with_allowed_origin_accepted(client: TestClient, origin: str) -> None:
    response = client.post(
        "/api/v1/_test/echo", json={"value": "x"}, headers={**CLIENT, "Origin": origin}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "file://localhost", "http://localhost.evil.example"]
)
def test_bad_origin_rejected(client: TestClient, origin: str) -> None:
    response = client.post(
        "/api/v1/_test/echo", json={"value": "x"}, headers={**CLIENT, "Origin": origin}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "bad_origin"


def test_safe_methods_need_no_client_header(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 200
    # HEAD/OPTIONS are never blocked by the guard (whatever the route itself answers).
    assert client.head("/api/v1/health").status_code != 403
    assert client.options("/api/v1/health").json()["code"] != "missing_client_header"


# --- CORS ------------------------------------------------------------------------------------


def test_no_cors_by_default(client: TestClient) -> None:
    response = client.options(
        "/api/v1/_test/echo",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_when_configured(make_app: AppFactory) -> None:
    dev_origin = "http://devbox:5173"
    client = local_client(add_test_routes(make_app(cors_origins=[dev_origin])))
    preflight = client.options(
        "/api/v1/_test/echo",
        headers={
            "Origin": dev_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Lore-Client, Content-Type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == dev_origin
    response = client.post(
        "/api/v1/_test/echo", json={"value": "x"}, headers={**CLIENT, "Origin": dev_origin}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == dev_origin


# --- Security headers ------------------------------------------------------------------------

BASE_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
}


def test_security_headers_on_api_responses(client: TestClient) -> None:
    for response in (
        client.get("/api/v1/health"),
        client.get("/api/v1/nope"),
        client.post("/api/v1/_test/echo", json={}),
    ):
        for name, value in BASE_HEADERS.items():
            assert response.headers[name] == value
        assert "content-security-policy" not in response.headers


def test_security_headers_and_csp_on_spa_responses(make_app: AppFactory, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>")
    client = local_client(make_app(static_dir=tmp_path))
    response = client.get("/some/client/route")
    assert response.status_code == 200
    for name, value in BASE_HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_security_headers_on_rejected_host(make_app: AppFactory) -> None:
    response = TestClient(make_app()).get("/api/v1/health")  # Host: testserver
    assert response.status_code == 400
    assert response.headers["x-frame-options"] == "DENY"


# --- Body size limit -------------------------------------------------------------------------


def test_oversized_body_rejected_by_content_length(client: TestClient) -> None:
    body = b"x" * (MAX_JSON_BODY_BYTES + 1)
    response = client.post(
        "/api/v1/_test/raw", content=body, headers={**CLIENT, "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_oversized_streamed_body_rejected(client: TestClient) -> None:
    chunk = b"x" * (1024 * 1024)

    def chunks() -> Iterator[bytes]:
        for _ in range(11):
            yield chunk

    response = client.post(
        "/api/v1/_test/echo",
        content=chunks(),
        headers={**CLIENT, "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_body_at_limit_accepted(client: TestClient) -> None:
    body = b"x" * MAX_JSON_BODY_BYTES
    response = client.post(
        "/api/v1/_test/raw", content=body, headers={**CLIENT, "Content-Type": "application/json"}
    )
    assert response.status_code == 200
    assert response.json() == {"size": MAX_JSON_BODY_BYTES}


def test_multipart_is_not_limited_here(client: TestClient) -> None:
    response = client.post(
        "/api/v1/_test/raw",
        files={"file": ("big.bin", b"x" * (MAX_JSON_BODY_BYTES + 1))},
        headers=CLIENT,
    )
    assert response.status_code == 200


# --- Request ids -----------------------------------------------------------------------------


def test_request_id_echoed(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-Id": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_request_id_generated(client: TestClient) -> None:
    first = client.get("/api/v1/health").headers["x-request-id"]
    second = client.get("/api/v1/health").headers["x-request-id"]
    assert first != second
    assert len(first) == 32


@pytest.mark.parametrize("bad", ["", "a" * 129, "has space", "new\\nline"])
def test_unsafe_request_id_replaced(client: TestClient, bad: str) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-Id": bad})
    assert response.headers["x-request-id"] != bad
    assert len(response.headers["x-request-id"]) == 32


def test_request_id_on_rejections(client: TestClient) -> None:
    response = client.post(
        "/api/v1/_test/echo", json={"value": "x"}, headers={"X-Request-Id": "rej-1"}
    )
    assert response.status_code == 403
    assert response.headers["x-request-id"] == "rej-1"
