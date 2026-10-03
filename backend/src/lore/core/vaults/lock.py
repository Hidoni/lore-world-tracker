"""Vault lock files: one author process per vault (``persistence-and-migrations.md`` §1).

``<vault folder>/.lock`` holds the owner's PID and hostname. A lock whose owner is gone is taken
over with a warning; "gone" can only be decided on the same host: the PID is dead, or it is this
process's own PID although this process doesn't hold the lock (a previous run that got the same
PID, as PID 1 in a restarted container does).
"""

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lore.core.vaults.errors import VaultLockedError

logger = logging.getLogger(__name__)

# Lock files held by this process (also guards two managers of one process against each other).
_held: set[Path] = set()
_held_guard = threading.Lock()


@dataclass(frozen=True)
class LockOwner:
    pid: int
    hostname: str
    acquired_at: str | None = None

    @classmethod
    def current(cls) -> LockOwner:
        return cls(os.getpid(), socket.gethostname(), datetime.now(UTC).isoformat())

    def describe(self) -> dict[str, Any]:
        return {"pid": self.pid, "hostname": self.hostname, "acquired_at": self.acquired_at}


def _read_owner(path: Path) -> LockOwner | None:
    """The lock's owner, or ``None`` if the file can't be read or parsed (treated as locked: it
    may be another process's lock that is still being written)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid, hostname = data["pid"], data["hostname"]
    except OSError, ValueError, KeyError, TypeError:
        return None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if not isinstance(hostname, str):
        return None
    acquired_at = data.get("acquired_at")
    return LockOwner(pid, hostname, acquired_at if isinstance(acquired_at, str) else None)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, owned by another user
        return True
    return True


def _is_stale(owner: LockOwner) -> bool:
    if owner.hostname != socket.gethostname():
        return False
    return owner.pid == os.getpid() or not _pid_alive(owner.pid)


class VaultLock:
    """A held lock file. Release it with :meth:`release`."""

    def __init__(self, path: Path, owner: LockOwner) -> None:
        self.path = path
        self.owner = owner

    @classmethod
    def acquire(cls, path: Path) -> VaultLock:
        """Create the lock file, taking over a stale one. Raises ``VaultLockedError``."""
        path = path.resolve()
        with _held_guard:
            if path in _held:
                raise VaultLockedError(
                    "The vault is already open in this process.",
                    context={"owner": LockOwner.current().describe()},
                )
            for _attempt in range(2):
                owner = LockOwner.current()
                try:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                except FileExistsError:
                    existing = _read_owner(path)
                    if existing is not None and _is_stale(existing):
                        logger.warning(
                            "taking over stale vault lock %s (pid %d on %s)",
                            path,
                            existing.pid,
                            existing.hostname,
                        )
                        path.unlink(missing_ok=True)
                        continue
                    raise VaultLockedError(
                        _locked_detail(path, existing),
                        context={"owner": existing.describe() if existing else None},
                    ) from None
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(owner.describe(), handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                _held.add(path)
                return cls(path, owner)
            raise VaultLockedError(_locked_detail(path, _read_owner(path)))

    def moved_to(self, path: Path) -> None:
        """Record that the lock file moved along with its folder (trashing a held vault)."""
        with _held_guard:
            _held.discard(self.path)
            self.path = path.resolve()
            _held.add(self.path)

    def release(self) -> None:
        """Delete the lock file if it is still ours. Safe to call twice."""
        with _held_guard:
            if self.path not in _held:
                return
            _held.discard(self.path)
            current = _read_owner(self.path)
            if current is not None and (current.pid, current.hostname) == (
                self.owner.pid,
                self.owner.hostname,
            ):
                self.path.unlink(missing_ok=True)


def _locked_detail(path: Path, owner: LockOwner | None) -> str:
    if owner is None:
        return (
            f"The vault is locked: {path} exists but can't be read."
            " Delete it if no process uses the vault."
        )
    return f"The vault is open in another process (pid {owner.pid} on {owner.hostname})."
