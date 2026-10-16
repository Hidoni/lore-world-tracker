"""Published snapshots (``visibility-and-sharing.md`` §4): the canary vault published holds no
canary anywhere (byte scan of every file); the API, the CLI, the author-mode refusal and the leak
gate. The leak suite also runs against a published snapshot (``test_leaks.py``, mode
``published``)."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lore import cli
from lore.core.vaults import publish
from lore.core.vaults.publish import DROPPED_TABLES, PublishError, publish_vault
from tests.entity_api import HEADERS, Api, make_client
from tests.entity_modules import with_real_modules
from tests.visibility.canary import Canary, build_canary_vault, leak_client, publish_canary


@pytest.fixture(scope="module")
def canary(tmp_path_factory: pytest.TempPathFactory) -> Canary:
    return build_canary_vault(tmp_path_factory.mktemp("canary"))


@pytest.fixture(scope="module")
def published(canary: Canary, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return publish_canary(canary, tmp_path_factory.mktemp("published"))


def _files(root: Path) -> Iterator[Path]:
    return (path for path in sorted(root.rglob("*")) if path.is_file())


def test_the_published_canary_holds_no_canary(canary: Canary, published: Path) -> None:
    needles = [needle.encode() for needle in canary.needles]
    found = [
        (str(path.relative_to(published)), needle.decode())
        for path in _files(published)
        for needle in needles
        if needle in path.read_bytes()
    ]
    assert found == []
    # Not by deleting everything: the public records are there.
    data = b"".join(path.read_bytes() for path in _files(published))
    public = {**canary.public, **canary.records}
    assert [name for name, id_ in public.items() if id_.encode() not in data] == []


def test_the_snapshot_is_a_compact_read_only_vault(canary: Canary, published: Path) -> None:
    [folder] = (published / "vaults").iterdir()
    assert sorted(p.name for p in folder.iterdir()) == ["lore.db", "media", "vault.json"]
    manifest = json.loads((folder / "vault.json").read_text())
    assert manifest["published"] is True
    assert manifest["source_vault_id"] == canary.vault
    assert manifest["published_at"]
    with closing(sqlite3.connect(folder / "lore.db")) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        for table in DROPPED_TABLES:
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table
    assert publish.leak_problems(folder) == []


def test_a_snapshot_opens_only_read_only(canary: Canary, published: Path) -> None:
    base = f"/api/v1/vaults/{canary.vault}"
    with leak_client(published) as author:
        refused = author.get(f"{base}/entities")
        assert refused.status_code == 409
        assert refused.json()["code"] == "vault_published"
    with leak_client(published, read_only=True) as reader:
        assert reader.get(f"{base}/entities/{canary.public['Lantern']}").status_code == 200


# --- the API -------------------------------------------------------------------------------------


def _world(api: Api) -> tuple[str, str]:
    shown = api.make("misc", "Shown")["id"]
    hidden = api.make("misc", "Hidden secret", visibility="private")["id"]
    return shown, hidden


def test_publishing_from_the_settings(tmp_path: Path) -> None:
    out = tmp_path / "share"
    with make_client(tmp_path / "data", with_real_modules(), publish_dir=out) as client:
        api = Api(client)
        shown, hidden = _world(api)
        status = client.get(f"{api.base}/publish").json()
        assert status == {"available": True, "published_at": None}
        assert client.get(f"{api.base}/publish", params={"as_reader": True}).status_code == 404
        made = client.post(f"{api.base}/publish", headers=HEADERS)
        assert made.status_code == 200, made.json()
        first = made.json()["published_at"]
        assert first is not None
        assert client.get(f"{api.base}/publish").json()["published_at"] == first
        # Publishing again replaces the snapshot.
        api.make("misc", "Later")
        again = client.post(f"{api.base}/publish", headers=HEADERS).json()["published_at"]
        assert again >= first
        assert [p.name for p in out.iterdir()] == ["vaults"]
    with make_client(out, with_real_modules(), read_only=True) as reader:
        names = {e["name"] for e in reader.get(f"{api.base}/entities").json()["items"]}
        assert {"Shown", "Later"} <= names
        assert "Hidden secret" not in names
        assert reader.get(f"{api.base}/entities/{hidden}").status_code == 404
        assert reader.get(f"{api.base}/entities/{shown}").status_code == 200


def test_publishing_needs_a_publish_directory(tmp_path: Path) -> None:
    with make_client(tmp_path, with_real_modules()) as client:
        api = Api(client)
        assert client.get(f"{api.base}/publish").json() == {
            "available": False,
            "published_at": None,
        }
        refused = client.post(f"{api.base}/publish", headers=HEADERS)
        assert (refused.status_code, refused.json()["code"]) == (409, "publish_not_configured")


def test_the_leak_gate_refuses_a_snapshot_with_private_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "share"
    with make_client(tmp_path / "data", with_real_modules(), publish_dir=out) as client:
        api = Api(client)
        _world(api)
        monkeypatch.setattr(publish, "_sanitize", lambda _context: None)  # a broken sanitizer
        refused = client.post(f"{api.base}/publish", headers=HEADERS)
        assert (refused.status_code, refused.json()["code"]) == (409, "publish_failed")
        assert refused.json()["context"]["problems"]
        assert not (out / "vaults").exists()
        assert [p.name for p in out.iterdir()] == []  # the staging folder is gone too


def test_publishing_never_overwrites_other_data(tmp_path: Path) -> None:
    with make_client(tmp_path / "data", with_real_modules()) as client:
        api = Api(client)
        manager: Any = client.app.state.vaults  # type: ignore[attr-defined]
        with pytest.raises(PublishError):
            publish_vault(manager, api.vault, tmp_path / "data")
        info = manager.get(api.vault)
        stranger = tmp_path / "share" / "vaults" / info.folder
        stranger.mkdir(parents=True)
        (stranger / "notes.txt").write_text("mine")
        with pytest.raises(PublishError):
            publish_vault(manager, api.vault, tmp_path / "share")
        assert (stranger / "notes.txt").read_text() == "mine"


# --- the CLI -------------------------------------------------------------------------------------


def test_cli_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_DATA_DIR", str(tmp_path / "data"))
    with make_client(tmp_path / "data", with_real_modules()) as client:
        api = Api(client)
        _world(api)
    runner = CliRunner()
    missing = runner.invoke(cli.app, ["vault", "publish", api.vault])
    assert missing.exit_code == 1
    assert "LORE_PUBLISH_DIR" in missing.output
    out = tmp_path / "share"
    result = runner.invoke(cli.app, ["vault", "publish", api.vault, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "published:" in result.output
    [folder] = (out / "vaults").iterdir()
    assert b"Hidden secret" not in (folder / "lore.db").read_bytes()
    monkeypatch.setenv("LORE_PUBLISH_DIR", str(out))
    assert runner.invoke(cli.app, ["vault", "publish", api.vault]).exit_code == 0
