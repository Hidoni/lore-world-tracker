"""``lore mcp-bridge``: a vault's MCP endpoint for clients that only speak stdio (Claude Desktop's
local servers, ``mcp.md`` §2).

It reads newline-delimited JSON-RPC messages from stdin, posts each to the running server's
endpoint with the bearer token, and writes the answers to stdout, one per line. The endpoint is
stateless with JSON responses, so a message is one POST; notifications (``202``) have no answer.
The client's ``clientInfo.name`` from ``initialize`` goes along as the ``User-Agent``, so history
labels name the client, and the negotiated protocol version as ``MCP-Protocol-Version``. When the
server can't be reached or refuses (``401``, ``404``…), a request gets a JSON-RPC error that says
why, and a line on stderr.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlsplit

from lore import __version__
from lore.core.api.bearer import SECRETS_FOLDER, TOKEN_FILE

ACCEPT = "application/json, text/event-stream"
SERVER_ERROR = -32000  # JSON-RPC: implementation-defined server error
TIMEOUT = 300.0
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class BridgeError(Exception):
    """The bridge can't start (no token)."""


def endpoint_url(url: str, vault_id: str) -> str:
    return f"{url.rstrip('/')}/api/v1/vaults/{vault_id}/m/mcp"


def token_of(data_dir: Path, value: str | None) -> str:
    """The token to send: ``LORE_MCP_TOKEN``, else the one the server keeps in ``data_dir``."""
    if value:
        return value
    path = data_dir / SECRETS_FOLDER / TOKEN_FILE
    try:
        token = path.read_text(encoding="ascii").strip()
    except OSError as error:
        msg = (
            f"No token: set LORE_MCP_TOKEN, or start the server once so it creates {path} "
            f"({error.strerror})."
        )
        raise BridgeError(msg) from error
    if not token:
        raise BridgeError(f"No token: {path} is empty.")
    return token


@dataclass
class Bridge:
    url: str
    token: str
    errors: IO[str]
    client: str | None = None
    protocol_version: str | None = None
    _opener: urllib.request.OpenerDirector = field(init=False)

    def __post_init__(self) -> None:
        host = urlsplit(self.url).hostname or ""
        handlers = [urllib.request.ProxyHandler({})] if host in LOOPBACK else []
        self._opener = urllib.request.build_opener(*handlers)

    def run(self, lines: Iterable[bytes], out: IO[bytes]) -> None:
        for line in lines:
            if not line.strip():
                continue
            for answer in self.forward(line):
                out.write(json.dumps(answer, separators=(",", ":")).encode() + b"\n")
                out.flush()

    def forward(self, line: bytes) -> list[Any]:
        """The answers to one message from the client."""
        try:
            message = json.loads(line)
        except ValueError:
            return [_error(None, -32700, "Parse error")]
        self._note_client(message)
        try:
            status, body = self._post(line)
        except urllib.error.HTTPError as error:
            with error:
                detail = _detail(error.read()) or error.reason
            self._log(f"{self.url} answered {error.code}: {detail}")
            return [
                _error(i, SERVER_ERROR, f"Lore answered {error.code}: {detail}")
                for i in _ids(message)
            ]
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            self._log(f"can't reach {self.url}: {reason}")
            return [
                _error(i, SERVER_ERROR, f"Can't reach Lore at {self.url}: {reason}")
                for i in _ids(message)
            ]
        if status == 202 or not body.strip():  # noqa: PLR2004 (accepted: a notification)
            return []
        answers = _decode(body)
        for answer in answers:
            self._note_version(answer)
        return answers

    def _post(self, body: bytes) -> tuple[int, bytes]:
        headers = {
            "Content-Type": "application/json",
            "Accept": ACCEPT,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": f"{self.client or 'lore-mcp-bridge'} (lore-mcp-bridge/{__version__})",
        }
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        with self._opener.open(request, timeout=TIMEOUT) as response:
            return response.status, response.read()

    def _note_client(self, message: Any) -> None:
        if isinstance(message, dict) and message.get("method") == "initialize":
            info = (message.get("params") or {}).get("clientInfo") or {}
            name = info.get("name") if isinstance(info, dict) else None
            if isinstance(name, str) and name.strip():
                self.client = "-".join(name.split())[:100]

    def _note_version(self, answer: Any) -> None:
        if isinstance(answer, dict) and isinstance(answer.get("result"), dict):
            version = answer["result"].get("protocolVersion")
            if isinstance(version, str):
                self.protocol_version = version

    def _log(self, text: str) -> None:
        self.errors.write(f"lore mcp-bridge: {text}\n")
        self.errors.flush()


def _ids(message: Any) -> list[Any]:
    """The ids of the requests in a message (notifications have none)."""
    messages = message if isinstance(message, list) else [message]
    return [m["id"] for m in messages if isinstance(m, dict) and "id" in m and "method" in m]


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _detail(body: bytes) -> str | None:
    try:
        problem = json.loads(body)
    except ValueError:
        return None
    detail = problem.get("detail") if isinstance(problem, dict) else None
    return detail if isinstance(detail, str) else None


def _decode(body: bytes) -> list[Any]:
    """The JSON-RPC messages of a response: JSON, or the ``data:`` lines of an event stream."""
    text = body.decode("utf-8")
    try:
        return [json.loads(text)]
    except ValueError:
        pass
    answers = []
    for line in text.splitlines():
        if line.startswith("data:") and (data := line.removeprefix("data:").strip()):
            answers.append(json.loads(data))
    return answers
