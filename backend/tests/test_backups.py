"""Backups, restore, scheduled backups with retention and vault settings
(``persistence-and-migrations.md`` §5)."""

import hashlib
import io
import json
import sqlite3
import stat
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lore import cli
from lore.app import create_app
from lore.config import Settings
from lore.core.db.migrate import Migrator
from lore.core.vaults import VaultManager
from lore.core.vaults import backups as backups_module
from lore.core.vaults import manager as manager_module
from lore.core.vaults.backups import InvalidBackupError, RestoreLimits, prune_scheduled
from lore.core.vaults.manager import restored_name
from lore.core.vaults.scheduler import MaintenanceScheduler
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, make_client, problem
from tests.entity_modules import ENTITY_MODULES

MEDIA = {"media/ab/abcdef": b"\x89PNG fake image", "media/thumbs/abcdef_64.webp": b"thumb"}


@pytest.fixture
def client(tmp_path: Path) -> Any:
    with make_client(tmp_path) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)


def _vault_path(client: TestClient, vault_id: str) -> Path:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    return manager.get(vault_id).path


def _add_media(folder: Path) -> None:
    for name, data in MEDIA.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _backup(api: Api, **body: Any) -> dict[str, Any]:
    response = api.client.post(f"{api.base}/backups", json=body)
    assert response.status_code == 201, response.json()
    result: dict[str, Any] = response.json()
    return result


def _download(api: Api, backup_id: str) -> bytes:
    response = api.client.get(f"{api.base}/backups/{backup_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return response.content


def _restore(client: TestClient, data: bytes) -> Any:
    return client.post(
        "/api/v1/vaults/restore", files={"file": ("backup.zip", data, "application/zip")}
    )


def _dump(database: Path) -> dict[str, list[Any]]:
    """Every table's rows (``vault_meta`` without the identity keys a restore may change)."""
    connection = sqlite3.connect(database)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'search_fts_%' "
                "AND name NOT LIKE 'search_trigram_%' ORDER BY name"
            )
        ]
        dump = {
            table: sorted(map(repr, connection.execute(f'SELECT * FROM "{table}"')))
            for table in tables
        }
        dump["vault_meta"] = sorted(
            map(
                repr,
                connection.execute(
                    "SELECT * FROM vault_meta WHERE key NOT IN ('vault_id', 'name')"
                ),
            )
        )
        return dump
    finally:
        connection.close()


def _world(api: Api) -> None:
    api.make("misc", "Aetheria", aliases=[{"alias": "The Realm"}])
    api.make("gadget", "Lantern", fields={"text": "brass"}, visibility="private")


# --- round trip ----------------------------------------------------------------------------------


def test_backup_restore_round_trip(client: TestClient, api: Api) -> None:
    _world(api)
    source = _vault_path(client, api.vault)
    _add_media(source)
    backup = _backup(api)
    assert backup["kind"] == "manual"
    assert backup["includes_media"] is True
    assert backup["schema_revision"] == Migrator().head()
    listed = client.get(f"{api.base}/backups").json()["items"]
    assert [item["id"] for item in listed] == [backup["id"]]
    data = _download(api, backup["id"])

    response = _restore(client, data)
    assert response.status_code == 201, response.json()
    restored = response.json()
    today = datetime.now(UTC).date().isoformat()
    assert restored["name"] == f"W (restored {today})"
    assert restored["id"] != api.vault  # the original is still present
    assert restored["schema_status"]["state"] == "current"
    target = _vault_path(client, restored["id"])
    assert target != source
    for name, content in MEDIA.items():
        assert (target / name).read_bytes() == content
    assert _dump(target / "lore.db") == _dump(source / "lore.db")

    copy = Api(client, restored["id"])
    names = [e["name"] for e in client.get(f"{copy.base}/entities").json()["items"]]
    assert names == ["Aetheria", "Lantern"]
    hits = client.get(f"{copy.base}/search", params={"q": "realm"}).json()["items"]
    assert [hit["name"] for hit in hits] == ["Aetheria"]
    meta = sqlite3.connect(target / "lore.db")
    try:
        identity = dict(meta.execute("SELECT key, value FROM vault_meta").fetchall())
    finally:
        meta.close()
    assert json.loads(identity["vault_id"]) == restored["id"]


def test_restore_keeps_the_id_when_the_vault_is_gone(client: TestClient, api: Api) -> None:
    _world(api)
    data = _download(api, _backup(api, include_media=False)["id"])
    assert client.delete(api.base).status_code == 204
    restored = _restore(client, data).json()
    assert restored["id"] == api.vault
    assert restored["folder"] != ""


def test_backups_without_media(client: TestClient, api: Api) -> None:
    _add_media(_vault_path(client, api.vault))
    backup = _backup(api, include_media=False)
    assert backup["includes_media"] is False
    with zipfile.ZipFile(io.BytesIO(_download(api, backup["id"]))) as archive:
        assert sorted(archive.namelist()) == ["lore.db", "manifest.json"]
    restored = _restore(client, _download(api, backup["id"])).json()
    assert not (_vault_path(client, restored["id"]) / "media").exists()


def test_backup_ids_and_listing(client: TestClient, api: Api) -> None:
    first = _backup(api, include_media=False)
    second = _backup(api, include_media=False)
    assert first["id"].startswith("manual-")
    assert second["id"] != first["id"]
    items = client.get(f"{api.base}/backups").json()["items"]
    assert [item["id"] for item in items] == [second["id"], first["id"]]
    folder = _vault_path(client, api.vault) / "backups" / "manual"
    (folder / "broken.zip").write_bytes(b"not a zip")
    (folder / "Bad Name.zip").write_bytes(b"ignored")
    assert len(client.get(f"{api.base}/backups").json()["items"]) == 2
    problem(client.get(f"{api.base}/backups/nope/download"), 404, "backup_not_found")


# --- invalid and malicious zips ------------------------------------------------------------------


def _zip(entries: dict[str, bytes], manifest: dict[str, Any] | None = None, **info: Any) -> bytes:
    """A zip with these entries and a manifest listing their checksums (``manifest`` overrides
    members; ``info`` is applied to every ``ZipInfo``)."""
    files = {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}
    document = {
        "format_version": 1,
        "app_version": "0.0.0",
        "schema_revision": None,
        "vault": {
            "format_version": 1,
            "vault_id": "01a10000-0000-7000-8000-000000000000",
            "name": "Old",
            "created_at": "2026-10-01T00:00:00Z",
            "created_by_app_version": "0.0.0",
        },
        "created_at": "2026-10-01T00:00:00Z",
        "includes_media": False,
        "files": files,
        **(manifest or {}),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(document))
        for name, data in entries.items():
            entry = zipfile.ZipInfo(name)
            for key, value in info.items():
                setattr(entry, key, value)
            archive.writestr(entry, data)
    return buffer.getvalue()


def _real_entries(api: Api) -> dict[str, bytes]:
    data = _download(api, _backup(api, include_media=False)["id"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {"lore.db": archive.read("lore.db")}


def _assert_rejected(client: TestClient, data: bytes, fragment: str) -> None:
    vaults_dir = client.app.state.vaults.vaults_dir  # type: ignore[attr-defined]
    before = sorted(path.name for path in vaults_dir.iterdir())
    body = problem(_restore(client, data), 422, "invalid_backup")
    assert fragment in body["detail"]
    assert sorted(path.name for path in vaults_dir.iterdir()) == before  # nothing left behind


def test_invalid_zips_are_rejected(client: TestClient, api: Api) -> None:
    db = _real_entries(api)
    _assert_rejected(client, b"not a zip", "isn't a valid zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("lore.db", b"x")
    _assert_rejected(client, buffer.getvalue(), "no manifest.json")
    _assert_rejected(client, _zip(db, {"format_version": 9}), "Backup format 9")
    _assert_rejected(client, _zip(db, {"files": "nope"}), "manifest is invalid")
    _assert_rejected(client, _zip({"media/a": b"a"}), "no lore.db")
    _assert_rejected(client, _zip(db, {"vault": {"format_version": 1}}), "vault.json is invalid")
    _assert_rejected(client, _zip(db, {"vault": {"format_version": 7}}), "vault.json is invalid")


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("../evil", "Unsafe path"),
        ("/etc/evil", "Unsafe path"),
        ("media/../../evil", "Unsafe path"),
        ("media\\evil", "Unsafe path"),
        ("C:/evil", "Unsafe path"),
        ("run.sh", "Unexpected file"),
    ],
)
def test_unsafe_entries_are_rejected(
    client: TestClient, api: Api, name: str, fragment: str
) -> None:
    _assert_rejected(client, _zip({**_real_entries(api), name: b"x"}), fragment)


def test_tampered_backups_are_rejected(client: TestClient, api: Api) -> None:
    db = _real_entries(api)
    tampered = _zip(db, {"files": {"lore.db": "0" * 64}})
    _assert_rejected(client, tampered, "Checksum mismatch")
    listed = {"lore.db": hashlib.sha256(db["lore.db"]).hexdigest(), "media/x": "0" * 64}
    _assert_rejected(client, _zip(db, {"files": listed}), "missing")
    link = _zip({**db, "media/link": b"/etc/passwd"}, external_attr=(stat.S_IFLNK | 0o777) << 16)
    _assert_rejected(client, link, "Symbolic link")
    unlisted = _zip(db, {"files": {"lore.db": hashlib.sha256(db["lore.db"]).hexdigest()}})
    buffer = io.BytesIO(unlisted)
    with zipfile.ZipFile(buffer, "a") as archive:
        archive.writestr("media/extra", b"x")
    _assert_rejected(client, buffer.getvalue(), "Unexpected file")


def test_duplicate_entries_are_rejected(client: TestClient, api: Api) -> None:
    db = _real_entries(api)
    buffer = io.BytesIO(_zip(db))
    with pytest.warns(UserWarning, match="Duplicate name"), zipfile.ZipFile(buffer, "a") as archive:
        archive.writestr("lore.db", db["lore.db"])
    _assert_rejected(client, buffer.getvalue(), "Duplicate entry")


def test_restore_limits(tmp_path: Path, client: TestClient, api: Api) -> None:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    data = _zip({**_real_entries(api), "media/a": b"a" * 1000})
    with pytest.raises(InvalidBackupError, match="more than 2 files"):
        manager.restore(io.BytesIO(data), RestoreLimits(max_files=2))
    with pytest.raises(InvalidBackupError, match="expands to more than"):
        manager.restore(io.BytesIO(data), RestoreLimits(max_bytes=500))
    assert not any(p.name.startswith(".creating") for p in manager.vaults_dir.iterdir())


def _database_at(path: Path, revision: str | None, vault_id: str) -> bytes:
    """A vault database migrated to ``revision`` (or stamped with an unknown one when None)."""
    sqlite3.connect(path).close()
    vault = {"vault_id": vault_id, "name": "Old", "created_at": "2026-10-01T00:00:00+00:00"}
    Migrator().upgrade(path, revision or "head", attributes={"vault": vault})
    if revision is None:
        connection = sqlite3.connect(path)
        connection.execute("UPDATE alembic_version SET version_num = 'from_the_future'")
        connection.commit()
        connection.close()
    return path.read_bytes()


def test_restore_upgrades_older_databases(tmp_path: Path, client: TestClient) -> None:
    base = Migrator().script().get_bases()[0]
    vault_id = "01a10000-0000-7000-8000-000000000000"
    data = _zip({"lore.db": _database_at(tmp_path / "old.db", base, vault_id)})
    restored = _restore(client, data).json()
    assert restored["id"] == vault_id
    assert restored["schema_status"]["state"] == "current"
    assert client.get(f"/api/v1/vaults/{vault_id}/entities").status_code == 200


def test_restore_refuses_newer_databases(tmp_path: Path, client: TestClient) -> None:
    vault_id = "01a10000-0000-7000-8000-000000000000"
    data = _zip({"lore.db": _database_at(tmp_path / "new.db", None, vault_id)})
    problem(_restore(client, data), 409, "vault_newer_than_app")
    vaults_dir = client.app.state.vaults.vaults_dir  # type: ignore[attr-defined]
    assert not vaults_dir.exists() or list(vaults_dir.iterdir()) == []


def test_restored_names_fit() -> None:
    day = datetime(2026, 10, 1, tzinfo=UTC)
    assert restored_name("Aetheria", day) == "Aetheria (restored 2026-10-01)"
    long = restored_name("x" * 200, day)
    assert len(long) == 200
    assert long.endswith(" (restored 2026-10-01)")


# --- scheduled and pre-operation backups ---------------------------------------------------------


def test_scheduled_backups_and_retention(client: TestClient, api: Api) -> None:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    folder = _vault_path(client, api.vault)
    manual = _backup(api, include_media=False)
    response = client.patch(f"{api.base}/settings", json={"backups": {"every_hours": 2, "keep": 2}})
    assert response.json()["backups"] == {"every_hours": 2, "keep": 2, "include_media": True}

    start = datetime.now(UTC)
    assert len(manager.run_scheduled_backups(start)) == 1  # none yet
    assert manager.run_scheduled_backups(start + timedelta(hours=1)) == []  # too early
    later = datetime.now(UTC)
    for hours in (2, 4, 6):
        made = manager.run_scheduled_backups(later + timedelta(hours=hours))
        assert len(made) == 1
        assert made[0].kind == "scheduled"
        assert made[0].includes_media is True
    items = client.get(f"{api.base}/backups").json()["items"]
    assert sorted(item["kind"] for item in items) == ["manual", "scheduled", "scheduled"]
    assert manual["id"] in {item["id"] for item in items}
    assert len(list((folder / "backups" / "auto").glob("scheduled-*.zip"))) == 2
    assert prune_scheduled(folder, 1)[0].name.startswith("scheduled-")

    client.patch(f"{api.base}/settings", json={"backups": {"every_hours": 0}})
    assert manager.run_scheduled_backups(later + timedelta(days=30)) == []


def test_requests_do_not_wait_for_scheduled_maintenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheduler's pass runs beside the requests (#238): while a scheduled backup is being
    written (half a minute for a large vault), the vault is read and written, and a new app's
    first request doesn't wait for a pass either."""
    writing, release = threading.Event(), threading.Event()
    create_backup = backups_module.create_backup

    def slow_backup(*args: Any, **kwargs: Any) -> Path:
        writing.set()
        assert release.wait(30)
        return create_backup(*args, **kwargs)

    monkeypatch.setattr(manager_module, "create_backup", slow_backup)
    app = create_app(Settings(data_dir=tmp_path), modules=ENTITY_MODULES)
    app.state.scheduler.interval = 0.05
    with local_client(app, headers=HEADERS) as client:
        api = Api(client)  # the first requests: no pass has finished
        client.patch(f"{api.base}/settings", json={"backups": {"every_hours": 1}})
        try:
            assert writing.wait(30), "the scheduler never started a backup"
            started = time.perf_counter()
            assert api.create("dimension", "Aetheria").status_code == 201
            assert client.get(f"{api.base}/entities").status_code == 200
            assert client.get(f"{api.base}/backups").json()["items"] == []  # still being written
            assert time.perf_counter() - started < 10
        finally:
            release.set()


def test_scheduled_backups_only_cover_open_vaults(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        Api(client)
    manager = VaultManager(tmp_path)
    assert manager.run_scheduled_backups() == []
    assert VaultManager(tmp_path, read_only=True).run_scheduled_backups() == []


def test_scheduled_backup_failures_are_logged(
    client: TestClient, api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    manager.open(api.vault)  # the scheduler only covers open vaults
    folder = _vault_path(client, api.vault) / "backups" / "auto"
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.write_text("a file where the folder should be")
    assert manager.run_scheduled_backups() == []
    assert "scheduled backup of vault" in caplog.text


def test_the_scheduler_runs_in_author_mode_only(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        scheduler = client.app.state.scheduler  # type: ignore[attr-defined]
        assert isinstance(scheduler, MaintenanceScheduler)
        assert scheduler.running
    assert not scheduler.running
    with make_client(tmp_path, read_only=True) as client:
        assert client.app.state.scheduler is None
    with pytest.raises(ValueError, match="read-only"):
        MaintenanceScheduler(VaultManager(tmp_path, read_only=True))


def test_the_scheduler_thread_backs_up(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = Api(client)
        api.make("misc", "Thing")
        manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
        scheduler = MaintenanceScheduler(manager, interval=0.01)
        scheduler.start()
        scheduler.start()  # idempotent
        try:
            deadline = time.monotonic() + 10
            while not manager.backups(api.vault) and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            scheduler.stop()
        assert [b.kind for b in manager.backups(api.vault)] == ["scheduled"]


def test_backup_before(client: TestClient, api: Api) -> None:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    _add_media(_vault_path(client, api.vault))
    info = manager.backup_before(api.vault, "module-removal")
    assert info.id.startswith("pre-module-removal-")
    assert (info.kind, info.reason, info.includes_media) == ("pre", "module-removal", False)
    assert info.path.parent.name == "auto"
    with pytest.raises(ValueError, match="invalid backup reason"):
        manager.backup_before(api.vault, "Bad Reason")
    with pytest.raises(ValueError, match="reason is required"):
        manager.backup(api.vault, kind="pre")


# --- read-only and readers -----------------------------------------------------------------------


def test_backups_are_author_only(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = Api(client)
        backup = _backup(api, include_media=False)
        data = _download(api, backup["id"])
        for path in ("backups", f"backups/{backup['id']}/download"):
            response = client.get(f"{api.base}/{path}", params={"as_reader": "true"})
            assert response.status_code == 404
    with make_client(tmp_path, read_only=True) as client:
        reader = Api(client, api.vault)
        for path in ("backups", f"backups/{backup['id']}/download"):
            assert client.get(f"{reader.base}/{path}").status_code == 404
        problem(client.post(f"{reader.base}/backups", json={}), 403, "read_only")
        problem(_restore(client, data), 403, "read_only")
        problem(client.patch(f"{reader.base}/settings", json={}), 403, "read_only")
        assert client.get(f"{reader.base}/settings").status_code == 200
    manager = VaultManager(tmp_path, read_only=True)
    with pytest.raises(Exception, match="read-only"):
        manager.backup(api.vault)
    with pytest.raises(Exception, match="read-only"):
        manager.restore(io.BytesIO(data))


# --- settings ------------------------------------------------------------------------------------


def test_vault_settings(client: TestClient, api: Api) -> None:
    path = f"{api.base}/settings"
    assert client.get(path).json() == {
        "defaults": {"visibility": "public"},
        "backups": {"every_hours": 24, "keep": 7, "include_media": True},
    }
    updated = client.patch(path, json={"defaults": {"visibility": "private"}}).json()
    assert updated["defaults"] == {"visibility": "private"}
    assert updated["backups"]["every_hours"] == 24
    assert api.make("misc", "Secret")["visibility"] == "private"
    updated = client.patch(path, json={"backups": {"keep": 3, "include_media": False}}).json()
    assert updated == {
        "defaults": {"visibility": "private"},
        "backups": {"every_hours": 24, "keep": 3, "include_media": False},
    }
    invalid: tuple[dict[str, Any], ...] = (
        {"backups": {"keep": 0}},
        {"backups": {"every_hours": -1}},
        {"defaults": {"visibility": "hidden"}},
        {"display": {}},
    )
    for body in invalid:
        assert client.patch(path, json=body).status_code == 422
    # Module states share the settings document and survive settings updates.
    assert client.get(f"{api.base}/registry").json()["modules"]


def test_invalid_stored_settings_fall_back_to_defaults(client: TestClient, api: Api) -> None:
    manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
    opened = manager.open(api.vault)
    with opened.write_sessions.begin() as session:
        from lore.core.vaults.meta import get_meta, set_meta  # noqa: PLC0415

        set_meta(session, "settings", {**get_meta(session, "settings"), "backups": {"keep": -5}})
    assert client.get(f"{api.base}/settings").json()["backups"]["keep"] == 7


# --- CLI -----------------------------------------------------------------------------------------


def test_cli_backup_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    created = runner.invoke(cli.app, ["vault", "create", "Aetheria"])
    assert created.exit_code == 0, created.output
    folder = created.output.split()[1]
    result = runner.invoke(cli.app, ["vault", "backup", folder, "--no-media"])
    assert result.exit_code == 0, result.output
    zip_path = Path(result.output.splitlines()[1].removeprefix("backup: "))
    assert zip_path.is_file()
    restored = runner.invoke(cli.app, ["vault", "restore", str(zip_path)])
    assert restored.exit_code == 0, restored.output
    assert "Aetheria (restored" in restored.output

    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"nope")
    failed = runner.invoke(cli.app, ["vault", "restore", str(broken)])
    assert failed.exit_code == 1
    assert "isn't a valid zip" in failed.output
    missing = runner.invoke(cli.app, ["vault", "backup", "nope"])
    assert missing.exit_code == 1
