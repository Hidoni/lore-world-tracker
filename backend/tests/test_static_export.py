"""Static export (``visibility-and-sharing.md`` §8, ADR 0016): a published snapshot as files for a
static host. The canary vault's export holds no canary anywhere (byte scan of every file), its
recorded responses equal what the read-only server answers readers, and anything but a
published snapshot is refused."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lore import cli
from lore.core.modules import StaticRead
from lore.static_export import MANIFEST_NAME, StaticExportError, StaticExportInfo, export_static
from lore.static_export.modules import _File, _key
from tests.visibility.canary import (
    LEAK_MODULES,
    Canary,
    build_canary_vault,
    leak_client,
    publish_canary,
)

INDEX = """<!doctype html>
<html lang="en">
  <head>
    <base href="/" />
    <title>Lore World Tracker</title>
  </head>
  <body><div id="root"></div><script type="module" src="./assets/index.js"></script></body>
</html>
"""


@pytest.fixture(scope="module")
def canary(tmp_path_factory: pytest.TempPathFactory) -> Canary:
    return build_canary_vault(tmp_path_factory.mktemp("canary"))


@pytest.fixture(scope="module")
def published(canary: Canary, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return publish_canary(canary, tmp_path_factory.mktemp("published"))


@pytest.fixture(scope="module")
def spa(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("spa")
    (root / "index.html").write_text(INDEX)
    (root / "assets").mkdir()
    (root / "assets" / "index.js").write_text("console.log('app')\n")
    return root


@pytest.fixture(scope="module")
def exported(
    canary: Canary, published: Path, spa: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    out = tmp_path_factory.mktemp("export") / "site"
    export_static(published, canary.vault, out, spa, modules=LEAK_MODULES)
    return out


def _files(root: Path) -> Iterator[Path]:
    return (path for path in sorted(root.rglob("*")) if path.is_file())


def test_the_export_holds_no_canary(canary: Canary, exported: Path) -> None:
    needles = [needle.encode() for needle in canary.needles]
    found = [
        (str(path.relative_to(exported)), needle.decode())
        for path in _files(exported)
        for needle in needles
        if needle in path.read_bytes()
    ]
    assert found == []


def test_the_export_is_the_spa_marked_static_with_its_data(canary: Canary, exported: Path) -> None:
    index = (exported / "index.html").read_text()
    assert '<base href="./" />' in index
    assert f'<meta name="lore-static" content="data/" data-vault="{canary.vault}" />' in index
    assert (exported / "assets" / "index.js").is_file()
    manifest = json.loads((exported / MANIFEST_NAME).read_text())
    assert manifest["format"] == 1
    assert manifest["vault_id"] == canary.vault
    assert manifest["published_at"]
    base = exported / "data" / "vaults" / canary.vault
    for name in ("settings", "registry", "link-types", "tags", "calendars/presets"):
        assert (base / f"{name}.json").is_file(), name
    meta = json.loads((exported / "data" / "meta.json").read_text())
    assert meta["read_only"] is True
    [vault] = json.loads((exported / "data" / "vaults.json").read_text())["items"]
    assert vault["id"] == canary.vault


def test_recorded_responses_are_what_readers_get(
    canary: Canary, published: Path, exported: Path
) -> None:
    base = f"/api/v1/vaults/{canary.vault}"
    with leak_client(published, read_only=True) as reader:
        for route in ("registry", "settings", "link-types", "calendars/presets"):
            recorded = json.loads(
                (exported / "data" / f"vaults/{canary.vault}/{route}.json").read_text()
            )
            assert recorded == reader.get(f"{base}/{route}").json(), route
        recorded = json.loads((exported / "data" / f"vaults/{canary.vault}.json").read_text())
        assert recorded == reader.get(base).json()


def test_only_a_published_snapshot_is_exported(
    canary: Canary, published: Path, spa: Path, tmp_path: Path
) -> None:
    with pytest.raises(StaticExportError, match="not a published snapshot"):
        export_static(canary.data_dir, canary.vault, tmp_path / "a", spa, modules=LEAK_MODULES)
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "notes.txt").write_text("mine")
    with pytest.raises(StaticExportError, match="not empty"):
        export_static(published, canary.vault, taken, spa, modules=LEAK_MODULES)
    assert (taken / "notes.txt").read_text() == "mine"
    with pytest.raises(StaticExportError, match="no SPA build"):
        export_static(published, canary.vault, tmp_path / "b", tmp_path, modules=LEAK_MODULES)


def test_cli_export_static(
    canary: Canary, published: Path, spa: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.delenv("LORE_PUBLISH_DIR", raising=False)
    missing = runner.invoke(cli.app, ["vault", "export-static", canary.vault, "--out", "x"])
    assert missing.exit_code == 1
    assert "LORE_PUBLISH_DIR" in missing.output
    monkeypatch.setattr(cli, "export_static", _with_leak_modules)
    out = tmp_path / "site"
    result = runner.invoke(
        cli.app,
        ["vault", "export-static", canary.vault, "--out", str(out),
         "--data-dir", str(published), "--spa", str(spa)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "exported:" in result.output
    assert (out / MANIFEST_NAME).is_file()


def _with_leak_modules(data_dir: Path, vault: str, out: Path, spa_dir: Path) -> StaticExportInfo:
    return export_static(data_dir, vault, out, spa_dir, modules=LEAK_MODULES)


def test_answers_store_each_object_once() -> None:
    node = {"id": "a", "name": "Ilsa"}
    other = {"id": "b", "name": "Wren"}
    recorded = _File(
        answers={"[]": {"nodes": [node, other], "truncated": False}},
        as_of={"[]": [["0", {"nodes": [node]}], ["5", {"nodes": [node, other], "tags": ["x"]}]]},
    )
    dumped = recorded.dump()
    assert dumped["pool"] == [node, other]
    assert dumped["answers"] == {"[]": {"nodes": {"#": [0, 1]}, "truncated": False}}
    assert dumped["as_of"]["[]"] == [
        ["0", {"nodes": {"#": [0]}}],
        ["5", {"nodes": {"#": [0, 1]}, "tags": ["x"]}],
    ]


def test_reads_naming_their_entity_in_the_query_have_a_file_per_entity() -> None:
    graph = StaticRead("graph", kind="*", variants=((("center", "{id}"), ("depth", "1")),))
    assert _key(graph, "m/graph/graph", "e1") == "static/split/m/graph/graph/center/e1"
    assert _key(graph, "m/graph/graph", None) == "m/graph/graph"
    members = StaticRead("{id}/members", kind="group")
    assert _key(members, "m/groups/e1/members", "e1") == "m/groups/e1/members"
