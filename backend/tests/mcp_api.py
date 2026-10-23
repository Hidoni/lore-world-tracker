"""Helpers for MCP endpoint tests: JSON-RPC requests to a vault's endpoint, with the token."""

import json
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

ACCEPT = "application/json, text/event-stream"
PROTOCOL_VERSION = "2025-06-18"


def endpoint(vault_id: str) -> str:
    return f"/api/v1/vaults/{vault_id}/m/mcp"


def token_of(client: TestClient) -> str:
    token = client.app.state.bearer_token.value()  # type: ignore[attr-defined]
    assert isinstance(token, str)
    return token


@dataclass
class ToolResult:
    is_error: bool
    text: str

    @property
    def data(self) -> Any:
        return json.loads(self.text)


@dataclass
class Mcp:
    """One vault's MCP endpoint, called like an MCP client calls it (no ``X-Lore-Client``)."""

    client: TestClient
    vault_id: str
    token: str | None = None

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = token_of(self.client)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": ACCEPT,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }

    def post(self, body: Any, **headers: str) -> Any:
        return self.client.post(
            endpoint(self.vault_id), json=body, headers={**self.headers, **headers}
        )

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """The JSON-RPC response of one request (``result`` or ``error``)."""
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        assert response.status_code == 200, response.text
        answer: dict[str, Any] = response.json()
        return answer

    def result(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        answer = self.rpc(method, params)
        assert "result" in answer, answer
        result: dict[str, Any] = answer["result"]
        return result

    def tool(self, name: str, /, **arguments: Any) -> ToolResult:
        result = self.result("tools/call", {"name": name, "arguments": arguments})
        return ToolResult(bool(result.get("isError")), result["content"][0]["text"])

    def ok(self, name: str, /, **arguments: Any) -> Any:
        """A tool's result; the test fails when the tool answers with an error."""
        answer = self.tool(name, **arguments)
        assert not answer.is_error, answer.text
        return answer.data

    def failed(self, name: str, code: str, /, **arguments: Any) -> dict[str, Any]:
        """A tool error (a problem) with ``code``."""
        answer = self.tool(name, **arguments)
        assert answer.is_error, answer.text
        problem: dict[str, Any] = answer.data
        assert problem["code"] == code, problem
        return problem

    def read(self, uri: str) -> dict[str, Any]:
        return self.rpc("resources/read", {"uri": uri})
