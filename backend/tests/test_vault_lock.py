import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from lore.core.vaults import VaultLockedError, VaultManager
from lore.core.vaults.lock import VaultLock


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def write_lock(path: Path, pid: int, hostname: str | None = None) -> None:
    path.write_text(
        json.dumps({"pid": pid, "hostname": hostname or socket.gethostname()}), encoding="utf-8"
    )


def owner_pid(path: Path) -> int:
    pid: int = json.loads(path.read_text(encoding="utf-8"))["pid"]
    return pid


def test_lock_file_contents(tmp_path: Path) -> None:
    lock = VaultLock.acquire(tmp_path / ".lock")
    data = json.loads((tmp_path / ".lock").read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert data["hostname"] == socket.gethostname()
    assert data["acquired_at"]
    lock.release()
    lock.release()  # idempotent
    assert not (tmp_path / ".lock").exists()


def test_two_managers_contend_for_a_vault(tmp_path: Path) -> None:
    first = VaultManager(tmp_path)
    second = VaultManager(tmp_path)
    info = first.create("Aetheria")
    first.open(info.id)
    try:
        for operation in (second.open, second.trash):
            with pytest.raises(VaultLockedError) as caught:
                operation(info.id)
            assert caught.value.code == "vault_locked"
            assert caught.value.status == 409
        with pytest.raises(VaultLockedError):
            second.rename(info.id, "Mine")
        assert first.get(info.id).name == "Aetheria"
    finally:
        first.close()
    second.open(info.id)  # free after the first manager closed
    second.close()


def test_a_live_process_on_this_host_keeps_its_lock(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path)
    info = manager.create("Aetheria")
    parent = os.getppid()  # alive, and not this process
    write_lock(info.path / ".lock", parent)
    with pytest.raises(VaultLockedError, match=f"pid {parent}") as caught:
        manager.open(info.id)
    assert caught.value.context is not None
    assert caught.value.context["owner"]["pid"] == parent
    assert owner_pid(info.path / ".lock") == parent


def test_a_dead_process_lock_is_taken_over(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    manager = VaultManager(tmp_path)
    info = manager.create("Aetheria")
    write_lock(info.path / ".lock", dead_pid())
    manager.open(info.id)
    assert owner_pid(info.path / ".lock") == os.getpid()
    assert "taking over stale vault lock" in caplog.text
    manager.close()
    assert not (info.path / ".lock").exists()


def test_own_pid_lock_from_an_earlier_run_is_taken_over(tmp_path: Path) -> None:
    """PID 1 in a restarted container: the lock names this PID, but this process never took it."""
    manager = VaultManager(tmp_path)
    info = manager.create("Aetheria")
    write_lock(info.path / ".lock", os.getpid())
    manager.open(info.id)
    manager.close()


def test_other_hosts_locks_are_never_taken_over(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path)
    info = manager.create("Aetheria")
    write_lock(info.path / ".lock", dead_pid(), hostname="elsewhere")
    with pytest.raises(VaultLockedError, match="elsewhere"):
        manager.open(info.id)


@pytest.mark.parametrize(
    "content",
    ["", "{", "[]", '{"pid": "1", "hostname": "h"}', '{"pid": 0, "hostname": "h"}',
     '{"pid": true, "hostname": "h"}', '{"pid": 5, "hostname": 7}', '{"hostname": "h"}'],
)  # fmt: skip
def test_unreadable_locks_count_as_locked(tmp_path: Path, content: str) -> None:
    manager = VaultManager(tmp_path)
    info = manager.create("Aetheria")
    (info.path / ".lock").write_text(content, encoding="utf-8")
    with pytest.raises(VaultLockedError, match="can't be read"):
        manager.open(info.id)
    assert (info.path / ".lock").read_text(encoding="utf-8") == content


def test_release_leaves_a_lock_that_is_no_longer_ours(tmp_path: Path) -> None:
    lock = VaultLock.acquire(tmp_path / ".lock")
    write_lock(tmp_path / ".lock", os.getppid())
    lock.release()
    assert owner_pid(tmp_path / ".lock") == os.getppid()


def test_persistent_takeover_race_reports_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process re-creates a stale lock as fast as it is removed: give up, don't loop."""
    write_lock(tmp_path / ".lock", dead_pid())
    unlink = Path.unlink

    def recreate(path: Path, missing_ok: bool = False) -> None:
        unlink(path, missing_ok=missing_ok)
        write_lock(path, dead_pid())

    monkeypatch.setattr(Path, "unlink", recreate)
    with pytest.raises(VaultLockedError):
        VaultLock.acquire(tmp_path / ".lock")


def test_trash_removes_the_lock_from_the_trashed_folder(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path)
    info = manager.create("Aetheria")
    manager.open(info.id)
    target = manager.trash(info.id)
    assert not (target / ".lock").exists()
    manager.close()
