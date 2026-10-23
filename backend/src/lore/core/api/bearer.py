"""The server's bearer token (``docs/architecture/mcp.md`` §4): what clients outside the browser
(the MCP endpoint) authenticate with instead of ``X-Lore-Client``.

A random 256-bit secret per server, kept outside vaults (they get shared and backed up,
``security.md`` §5): ``LORE_MCP_TOKEN``, or ``<data dir>/secrets/mcp-token``, created on first
use with mode ``0600``. Modules declare the routes that take it (``ModuleSpec.bearer_routes``).
"""

import hmac
import logging
import os
import secrets
import threading
from pathlib import Path

from lore.core.errors import ConflictError

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32
SECRETS_FOLDER = "secrets"
TOKEN_FILE = "mcp-token"


class TokenFromEnvironmentError(ConflictError):
    code = "token_from_environment"
    title = "Token set by the environment"


class ServerToken:
    """The token of ``path`` (or the fixed ``value`` from the environment), read once and
    cached."""

    def __init__(self, path: Path, value: str | None = None) -> None:
        self.path = path
        self.fixed = value
        self._value: str | None = value
        self._lock = threading.Lock()

    @classmethod
    def of_data_dir(cls, data_dir: Path, value: str | None = None) -> ServerToken:
        return cls(data_dir / SECRETS_FOLDER / TOKEN_FILE, value)

    @property
    def from_environment(self) -> bool:
        return self.fixed is not None

    def value(self) -> str | None:
        """The token, created if the server has none yet; ``None`` when it can't be read or
        created (a read-only data directory without ``LORE_MCP_TOKEN``): nothing authenticates
        then."""
        if self._value is not None:
            return self._value
        with self._lock:
            if self._value is None:
                try:
                    self._value = self._read() or self._create()
                except OSError:
                    logger.warning("No bearer token: %s can't be read or created", self.path)
                    return None
            return self._value

    def regenerate(self) -> str:
        """A new token in place of the old one (which stops working at once)."""
        if self.fixed is not None:
            raise TokenFromEnvironmentError("LORE_MCP_TOKEN sets the token: change it there.")
        with self._lock:
            self.path.unlink(missing_ok=True)
            self._value = self._create()
            return self._value

    def matches(self, presented: str) -> bool:
        expected = self.value()
        return expected is not None and hmac.compare_digest(presented.encode(), expected.encode())

    def matches_header(self, authorization: str | None) -> bool:
        """Whether an ``Authorization`` header carries the token (``Bearer <token>``)."""
        scheme, _, presented = (authorization or "").partition(" ")
        return scheme.lower() == "bearer" and self.matches(presented.strip())

    def _read(self) -> str | None:
        try:
            text = self.path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return None
        return text or None

    def _create(self) -> str:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        staging = self.path.with_name(f".{self.path.name}.{secrets.token_hex(4)}")
        descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as file:
            file.write(token + "\n")
        try:
            # Another process may have created one meanwhile: the first one wins.
            os.link(staging, self.path)
        except FileExistsError:
            return self._read() or token
        finally:
            staging.unlink()
        return token
