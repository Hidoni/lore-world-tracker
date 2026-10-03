import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from lore import __version__
from lore.core.db import create_vault_engine
from lore.core.errors import ReadOnlyError
from lore.core.vaults import VaultManager, VaultNotFoundError
from lore.core.vaults import format as vault_format
from lore.core.vaults.format import (
    ManifestError,
    folder_candidates,
    read_manifest,
    slugify,
    upgrade_manifest,
)


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[VaultManager]:
    vaults = VaultManager(tmp_path / "data")
    yield vaults
    vaults.close()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def set_mtime(info_path: Path, seconds: int) -> None:
    for name in ("vault.json", "lore.db"):
        os.utime(info_path / name, (seconds, seconds))


# --- folder names ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Aetheria", "aetheria"),
        ("  The Shattered   Realms! ", "the-shattered-realms"),
        ("Ærø Île-de-Brume", "r-ile-de-brume"),
        ("世界", "vault"),
        ("../../etc/passwd", "etc-passwd"),
        ("a" * 60, "a" * 40),
        ("x" * 39 + " y", "x" * 39),
    ],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_folder_candidates_extend_the_id_prefix() -> None:
    vault_id = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    assert folder_candidates("Aetheria", vault_id) == [
        "aetheria-0190a1b2",
        "aetheria-0190a1b2-c3d4",
        "aetheria-0190a1b2-c3d4-7e5f",
        "aetheria-0190a1b2-c3d4-7e5f-8a9b",
        f"aetheria-{vault_id}",
    ]


# --- create / list / rename / trash ---------------------------------------------------------


def test_create_writes_the_vault_folder(manager: VaultManager) -> None:
    assert not manager.data_dir.exists()  # nothing is created before the first vault
    info = manager.create("  Aetheria ")
    assert info.name == "Aetheria"
    assert info.folder == f"aetheria-{info.id[:8]}"
    assert info.path == manager.vaults_dir / info.folder
    manifest = read_json(info.path / "vault.json")
    assert manifest == {
        "format_version": 1,
        "vault_id": info.id,
        "name": "Aetheria",
        "created_at": manifest["created_at"],
        "created_by_app_version": __version__,
        "published": False,
    }
    assert manifest["created_at"].endswith("Z")
    connection = sqlite3.connect(info.path / "lore.db")
    assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    connection.close()
    assert sorted(path.name for path in manager.vaults_dir.iterdir()) == [info.folder]
    assert manager.list_vaults() == [info]
    assert manager.get(info.id) == info


def test_same_name_vaults_get_distinct_folders(manager: VaultManager) -> None:
    first = manager.create("Aetheria")
    second = manager.create("Aetheria")
    # UUIDv7 ids made in the same minute share their first 8 characters
    assert first.id[:8] == second.id[:8]
    assert first.folder == f"aetheria-{first.id[:8]}"
    assert second.folder == f"aetheria-{second.id[:13]}"


@pytest.mark.parametrize("name", ["", "   ", "a\nb", "tab\there", "x" * 201])
def test_create_rejects_bad_names(manager: VaultManager, name: str) -> None:
    with pytest.raises(ValidationError):
        manager.create(name)


def test_failed_create_leaves_nothing(
    manager: VaultManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("lore.core.vaults.manager._create_database", broken)
    with pytest.raises(OSError, match="disk full"):
        manager.create("Aetheria")
    assert list(manager.vaults_dir.iterdir()) == []


def test_list_order_is_most_recently_modified_then_name(manager: VaultManager) -> None:
    zeta = manager.create("zeta")
    alpha = manager.create("Alpha")
    beta = manager.create("beta")
    old = manager.create("old")
    for info in (zeta, alpha, beta):
        set_mtime(info.path, 1_700_000_000)
    set_mtime(old.path, 1_600_000_000)
    assert [info.name for info in manager.list_vaults()] == ["Alpha", "beta", "zeta", "old"]
    # writing to a vault (here: uncheckpointed WAL content) moves it to the top
    connection = sqlite3.connect(old.path / "lore.db")
    connection.execute("PRAGMA wal_autocheckpoint = 0")
    connection.execute("CREATE TABLE t (x)")
    connection.commit()
    assert (old.path / "lore.db-wal").stat().st_size > 0
    assert manager.list_vaults()[0].name == "old"
    connection.close()


def test_an_empty_wal_does_not_count_as_a_change(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    set_mtime(info.path, 1_000_000_000)
    (info.path / "lore.db-wal").touch()
    assert manager.get(info.id).modified_at.timestamp() == 1_000_000_000


def test_rename_changes_only_the_display_name(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    write_json(info.path / "vault.json", {**read_json(info.path / "vault.json"), "extra": 1})
    renamed = manager.rename(info.id, " New Aetheria ")
    assert renamed.name == "New Aetheria"
    assert renamed.folder == info.folder
    manifest = read_json(info.path / "vault.json")
    assert manifest["name"] == "New Aetheria"
    assert manifest["extra"] == 1  # unknown keys survive rewrites
    assert manager.get(info.id).name == "New Aetheria"
    assert not (info.path / ".vault.json.tmp").exists()


def test_rename_updates_an_open_vault(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    opened = manager.open(info.id)
    manager.rename(info.id, "Renamed")
    assert opened.info.name == "Renamed"
    assert manager.get(info.id).name == "Renamed"


def test_trash_moves_the_folder(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    opened = manager.open(info.id)
    with opened.engine.begin() as connection:
        connection.execute(text("CREATE TABLE t (x)"))
    target = manager.trash(info.id)
    assert not info.path.exists()
    assert target.parent == manager.trash_dir
    assert target.name.startswith(f"{info.folder}-")
    assert sorted(path.name for path in target.iterdir()) == ["lore.db", "vault.json"]
    assert manager.list_vaults() == []
    with pytest.raises(VaultNotFoundError):
        manager.get(info.id)


def test_trash_twice_in_one_second_keeps_both(
    manager: VaultManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FrozenClock:
            return cls(2026, 10, 3, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr("lore.core.vaults.manager.datetime", FrozenClock)
    first = manager.create("Aetheria")
    first_target = manager.trash(first.id)
    second = manager.create("Aetheria")
    second.path.rename(first.path)  # same folder name as the first one had
    second_target = manager.trash(second.id)
    assert first_target.name == f"{first.folder}-20261003T120000Z"
    assert second_target.name == f"{first.folder}-20261003T120000Z-2"
    assert first_target.is_dir()


@pytest.mark.parametrize(
    "vault_id",
    [
        "../etc",
        "..",
        "",
        "0190A1B2-C3D4-7E5F-8A9B-0C1D2E3F4A5B",
        "0190a1b2c3d47e5f8a9b0c1d2e3f4a5b",
    ],
)
def test_unknown_or_malformed_ids_are_not_found(manager: VaultManager, vault_id: str) -> None:
    for operation in (manager.get, manager.open, manager.trash):
        with pytest.raises(VaultNotFoundError):
            operation(vault_id)
    with pytest.raises(VaultNotFoundError):
        manager.rename(vault_id, "x")


# --- opening --------------------------------------------------------------------------------


def test_open_is_cached_and_closed(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    opened = manager.open(info.id)
    assert manager.open(info.id) is opened
    assert (info.path / ".lock").is_file()
    with opened.sessions() as session:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    manager.close()
    assert not (info.path / ".lock").exists()
    assert manager.open(info.id) is not opened


def test_open_writes_back_an_upgraded_manifest(
    manager: VaultManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = manager.create("Aetheria")
    legacy = {**read_json(info.path / "vault.json"), "format_version": 0, "title": "Aetheria"}
    del legacy["name"]
    write_json(info.path / "vault.json", legacy)

    def v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
        upgraded = {**data, "format_version": 1, "name": data["title"]}
        del upgraded["title"]
        return upgraded

    monkeypatch.setitem(vault_format.UPGRADERS, 0, v0_to_v1)
    [listed] = manager.list_vaults()
    assert listed.needs_format_upgrade
    assert read_json(info.path / "vault.json")["format_version"] == 0  # listing never writes
    opened = manager.open(info.id)
    assert not opened.info.needs_format_upgrade
    assert read_json(info.path / "vault.json")["format_version"] == 1
    assert read_json(info.path / "vault.json")["name"] == "Aetheria"


# --- registry problems ----------------------------------------------------------------------


def test_unusable_folders_are_listed_as_problems(manager: VaultManager) -> None:
    good = manager.create("Aetheria")
    vaults = manager.vaults_dir
    (vaults / "Bad Name").mkdir()
    (vaults / "no-manifest").mkdir()
    (vaults / "broken").mkdir()
    (vaults / "broken" / "vault.json").write_text("{not json", encoding="utf-8")
    (vaults / "future").mkdir()
    write_json(vaults / "future" / "vault.json", {"format_version": 99})
    (vaults / ".creating-x").mkdir()  # an interrupted create: ignored
    (vaults / "stray-file").write_text("", encoding="utf-8")
    registry = manager.registry()
    assert list(registry.vaults) == [good.id]
    assert [(problem.folder, problem.code) for problem in registry.problems] == [
        ("Bad Name", "folder_name_invalid"),
        ("broken", "manifest_invalid"),
        ("future", "format_newer_than_app"),
        ("no-manifest", "manifest_invalid"),
    ]
    assert "newer than this app" in registry.problems[2].detail


def test_copied_vault_folders_are_duplicates(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    copy = manager.vaults_dir / "aaa-copy"  # sorts before the original
    copy.mkdir()
    for name in ("vault.json", "lore.db"):
        (copy / name).write_bytes((info.path / name).read_bytes())
    registry = manager.registry()
    assert registry.vaults[info.id].folder == info.folder
    [problem] = registry.problems
    assert (problem.folder, problem.code, problem.vault_id, problem.name) == (
        "aaa-copy",
        "duplicate_id",
        info.id,
        "Aetheria",
    )
    assert info.folder in problem.detail
    assert manager.get(info.id).folder == info.folder


def test_duplicates_without_an_original_name_use_folder_order(manager: VaultManager) -> None:
    info = manager.create("Aetheria")
    for folder in ("copy-b", "copy-a"):
        (manager.vaults_dir / folder).mkdir()
        (manager.vaults_dir / folder / "vault.json").write_bytes(
            (info.path / "vault.json").read_bytes()
        )
    info.path.rename(manager.vaults_dir / "copy-c")
    registry = manager.registry()
    assert registry.vaults[info.id].folder == "copy-a"
    assert [problem.folder for problem in registry.problems] == ["copy-b", "copy-c"]


# --- vault.json -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [{}, {"format_version": "1"}, {"format_version": True}, {"format_version": 0}],
)
def test_bad_format_versions(data: dict[str, Any]) -> None:
    with pytest.raises(ManifestError):
        upgrade_manifest(data)


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {"format_version": 1, "vault_id": "../x", "name": "A", "created_at": "2026-01-01T00:00:00Z",
         "created_by_app_version": "0"},
        {"format_version": 1, "vault_id": "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b", "name": "",
         "created_at": "2026-01-01T00:00:00Z", "created_by_app_version": "0"},
    ],
)  # fmt: skip
def test_invalid_manifests(tmp_path: Path, manifest: Any) -> None:
    write_json(tmp_path / "vault.json", manifest)
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


# --- read-only ------------------------------------------------------------------------------


def test_read_only_manager_never_writes(tmp_path: Path) -> None:
    author = VaultManager(tmp_path)
    info = author.create("Aetheria")
    with author.open(info.id).engine.begin() as connection:
        connection.execute(text("CREATE TABLE t (x)"))
    author.close()
    reader = VaultManager(tmp_path, read_only=True)
    try:
        with pytest.raises(ReadOnlyError):
            reader.create("x")
        with pytest.raises(ReadOnlyError):
            reader.rename(info.id, "x")
        with pytest.raises(ReadOnlyError):
            reader.trash(info.id)
        opened = reader.open(info.id)
        assert not (info.path / ".lock").exists()
        with opened.engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM t")).scalar() == 0
        with pytest.raises(OperationalError, match="readonly"), opened.engine.begin() as conn:
            conn.execute(text("INSERT INTO t VALUES (1)"))
    finally:
        reader.close()
    assert not reader.vaults_dir.joinpath(".lock").exists()


def test_read_only_ignores_locks_and_opens_published_vaults_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    author = VaultManager(tmp_path)
    info = author.create("Aetheria")
    author.open(info.id)  # holds the lock
    write_json(info.path / "vault.json", {**read_json(info.path / "vault.json"), "published": True})
    calls: list[dict[str, Any]] = []

    def spy(path: Path, **options: Any) -> Any:
        calls.append(options)
        return create_vault_engine(path, **options)

    monkeypatch.setattr("lore.core.vaults.manager.create_vault_engine", spy)
    reader = VaultManager(tmp_path, read_only=True)
    try:
        opened = reader.open(info.id)
        with opened.engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
        assert calls == [{"read_only": True, "immutable": True}]
    finally:
        reader.close()
        author.close()


def test_exposed_vaults_limit_a_read_only_registry(tmp_path: Path) -> None:
    author = VaultManager(tmp_path)
    first = author.create("First")
    second = author.create("Second")
    author.create("Third")
    (author.vaults_dir / "broken").mkdir()
    author.close()
    reader = VaultManager(tmp_path, read_only=True, exposed_vaults=[first.id, second.folder])
    assert {info.id for info in reader.list_vaults()} == {first.id, second.id}
    assert reader.registry().problems == []
    exposed_broken = VaultManager(tmp_path, read_only=True, exposed_vaults=["broken"])
    assert exposed_broken.list_vaults() == []
    assert [problem.folder for problem in exposed_broken.registry().problems] == ["broken"]
    # the author sees every vault whatever LORE_EXPOSED_VAULTS says
    assert len(VaultManager(tmp_path, exposed_vaults=[first.id]).list_vaults()) == 3
