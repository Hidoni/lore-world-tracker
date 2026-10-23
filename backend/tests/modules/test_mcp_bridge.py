"""``lore mcp-bridge`` (``docs/modules/mcp.md``, Bridge): the SDK's stdio client talks to a
running server through the bridge, and the bridge reports what goes wrong."""

import io
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from lore.app import create_app
from lore.config import Settings
from lore.modules.mcp.bridge import Bridge, BridgeError, endpoint_url, token_of
from tests.modules.test_mcp import MODULES

HEADERS = {"Content-Type": "application/json", "X-Lore-Client": "web"}


@dataclass(frozen=True)
class Live:
    url: str
    data_dir: Path
    vault: str

    def call(self, method: str, path: str, body: Any = None) -> Any:
        request = urllib.request.Request(
            f"{self.url}/api/v1{path}",
            data=None if body is None else json.dumps(body).encode(),
            headers=HEADERS,
            method=method,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=30) as response:
            return json.loads(response.read())


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    """A server on a free port, with a vault whose module allows writes."""
    port = _free_port()
    app = create_app(Settings(data_dir=tmp_path), modules=MODULES)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_config=None, access_log=False, lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "the server didn't start"
        time.sleep(0.05)
    try:
        live = Live(f"http://127.0.0.1:{port}", tmp_path, "")
        vault = live.call("POST", "/vaults", {"name": "W"})["id"]
        live = Live(live.url, tmp_path, vault)
        settings = {"access": "author", "writes": "on"}
        live.call("PATCH", f"/vaults/{vault}/modules/mcp", {"enabled": True, "settings": settings})
        live.call("POST", f"/vaults/{vault}/entities", {"kind": "misc", "name": "Queen Ilsa"})
        assert app.state.bearer_token.value()  # made on first use: the settings page shows it
        yield live
    finally:
        server.should_exit = True
        thread.join(30)


def test_the_sdk_stdio_client_through_the_bridge(live: Live) -> None:
    environment = {**os.environ, "LORE_DATA_DIR": str(live.data_dir)}
    environment.pop("LORE_MCP_TOKEN", None)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lore", "mcp-bridge", "--vault", live.vault, "--url", live.url],
        env=environment,
    )

    async def session() -> dict[str, Any]:
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as client,
        ):
            initialized = await client.initialize()
            tools = await client.list_tools()
            found = await client.call_tool("search", {"query": "queen"})
            made = await client.call_tool(
                "create_entity", {"kind": "misc", "name": "Mira", "body": "A **healer**."}
            )
            return {
                "server": initialized.server_info.name,
                "tools": {tool.name for tool in tools.tools},
                "found": found.structured_content,
                "made": made.structured_content,
            }

    result = anyio.run(session)
    assert result["server"] == "lore-world-tracker"
    assert {"search", "create_entity", "undo_last"} <= result["tools"]
    assert result["found"]["items"][0]["name"] == "Queen Ilsa"
    assert result["made"]["name"] == "Mira"
    changes = live.call("GET", f"/vaults/{live.vault}/changes?origin=mcp")["items"]
    # The bridge passes the client's name along: the SDK's client calls itself "mcp".
    assert changes[0]["summary"].startswith("Created misc “Mira” (MCP create_entity, ")
    assert "lore-mcp-bridge" not in changes[0]["summary"]


def test_the_bridge_reports_refusals(live: Live) -> None:
    errors = io.StringIO()
    bridge = Bridge(endpoint_url(live.url, live.vault), "wrong", errors)
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    [answer] = bridge.forward(json.dumps(request).encode())
    assert answer["id"] == 7
    assert "401" in answer["error"]["message"]
    assert "401" in errors.getvalue()
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert bridge.forward(json.dumps(notification).encode()) == []  # no answer to give
    assert bridge.forward(b"{not json")[0]["error"]["code"] == -32700


def test_the_bridge_reports_an_unreachable_server(tmp_path: Path) -> None:
    errors = io.StringIO()
    bridge = Bridge(endpoint_url(f"http://127.0.0.1:{_free_port()}", "v"), "t", errors)
    request = {"jsonrpc": "2.0", "id": "a", "method": "ping"}
    [answer] = bridge.forward(json.dumps(request).encode())
    assert answer["id"] == "a"
    assert "Can't reach Lore" in answer["error"]["message"]
    assert "can't reach" in errors.getvalue()


def test_the_token(tmp_path: Path) -> None:
    assert token_of(tmp_path, "from-env") == "from-env"
    with pytest.raises(BridgeError, match="LORE_MCP_TOKEN"):
        token_of(tmp_path, None)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "mcp-token").write_text("abc\n", encoding="ascii")
    assert token_of(tmp_path, None) == "abc"
    (tmp_path / "secrets" / "mcp-token").write_text("", encoding="ascii")
    with pytest.raises(BridgeError, match="empty"):
        token_of(tmp_path, None)
