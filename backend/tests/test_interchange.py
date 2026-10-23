"""The interchange format (``interchange.md``): exports of a whole vault or one dimension, for
the author or readers; imports with fresh or kept ids, conflicts, references, documents from an
older schema, broken files; the API and the CLI.

Worlds are copies of the v1.0.0 golden fixture vault (every feature of the MVP, media included);
after every import ``lore vault check`` must find nothing to fix."""

import hashlib
import io
import json
import shutil
import sqlite3
import zipfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lore import cli
from lore.app import create_app
from lore.config import Settings
from lore.core.interchange.export import dump_tables, export_interchange, exported_tables
from lore.core.interchange.format import (
    DOCUMENT_NAME,
    InvalidInterchangeError,
    codec,
    encode_row,
    encode_value,
    file_name,
    read_archive,
    sha256_of,
    write_archive,
)
from lore.core.maintenance import check_vault
from lore.core.vaults import VaultManager
from tests.conftest import local_client
from tests.entity_api import HEADERS, problem
from tests.visibility.canary import Canary, build_canary_vault, leak_client

FIXTURES = Path(__file__).parent / "fixtures" / "vaults"


@dataclass
class World:
    client: TestClient
    vault: str
    expected: dict[str, Any]

    @property
    def manager(self) -> VaultManager:
        manager: VaultManager = self.client.app.state.vaults  # type: ignore[attr-defined]
        return manager

    @property
    def base(self) -> str:
        return f"/api/v1/vaults/{self.vault}"

    def new_vault(self, name: str = "Target") -> str:
        created = self.client.post("/api/v1/vaults", json={"name": name})
        assert created.status_code == 201, created.json()
        vault_id: str = created.json()["id"]
        return vault_id

    def export(self, **params: Any) -> bytes:
        response = self.client.get(f"{self.base}/export/interchange", params=params)
        assert response.status_code == 200, response.text
        return response.content

    def import_(self, vault: str, data: bytes, **params: Any) -> Any:
        return self.client.post(
            f"/api/v1/vaults/{vault}/import/interchange",
            params=params,
            files={"file": ("world.zip", data, "application/zip")},
        )

    def imported(self, vault: str, data: bytes, **params: Any) -> dict[str, Any]:
        response = self.import_(vault, data, **params)
        assert response.status_code == 200, response.json()
        body: dict[str, Any] = response.json()
        return body

    def rows(self, vault: str) -> dict[str, list[dict[str, Any]]]:
        """Every authored table of a vault, as documents hold them."""
        registry = self.manager.module_registry
        assert registry is not None
        tables = exported_tables(registry)
        by_name = {table.name: table for table in tables}
        with self.manager.open(vault).sessions() as session:
            rows = dump_tables(session, tables)
        return {name: [encode_row(by_name[name], row) for row in r] for name, r in rows.items()}

    def problems(self, vault: str) -> list[Any]:
        return list(check_vault(self.manager, vault).problems)


def _world(tmp_path: Path, version: str = "v1.0.0") -> Iterator[World]:
    fixture = FIXTURES / version
    expected: dict[str, Any] = json.loads((fixture / "expected.json").read_text("utf-8"))
    shutil.copytree(fixture / "vault", tmp_path / "vaults" / expected["folder"])
    app = create_app(Settings(data_dir=tmp_path))
    with local_client(app, headers=HEADERS) as client:
        vault = expected["vault_id"]
        assert client.post(f"/api/v1/vaults/{vault}/migrate").status_code == 200
        assert client.get(f"/api/v1/vaults/{vault}/entities").status_code == 200
        yield World(client, vault, expected)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from _world(tmp_path)


def _document(data: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document: dict[str, Any] = json.loads(archive.read(DOCUMENT_NAME))
    return document


def _names(rows: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {entity["name"] for entity in rows["entities"]}


# --- whole vaults ---------------------------------------------------------------------------------


def _comparable(rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Rows with the time statuses ``lore vault check`` takes as the same (``ok`` and
    ``trashed_ref``: a trashed event's own slots) made equal, and without the ``updated_at`` of
    rows with time slots: the import resolves every slot again, and the statuses of such slots
    depend on the order they resolve in (a full ``reindex`` words them differently too)."""
    same: dict[str, list[dict[str, Any]]] = {}
    for name, table_rows in rows.items():
        same[name] = []
        for row in table_rows:
            if "time_status" not in row:
                same[name].append(row)
                continue
            status = "ok" if row["time_status"] == "trashed_ref" else row["time_status"]
            same[name].append({**row, "time_status": status, "updated_at": None})
    return same


def test_a_vault_moves_to_another_with_its_ids(world: World) -> None:
    data = world.export(audience="author")
    document = _document(data)
    assert document["format"] == "lore-interchange"
    assert document["format_version"] == 1
    assert document["scope"] == {"kind": "vault"}
    assert document["references"] == []
    assert len(document["files"]) == 2  # the media items' files
    target = world.new_vault()
    report = world.imported(target, data, ids="keep")
    assert report["entities"] == len(document["tables"]["entities"])
    assert report["dropped"] == {}
    assert report["files"] == 2
    # Every record, exactly: ids, revisions, timestamps, specs and resolved moments.
    assert _comparable(world.rows(target)) == _comparable(world.rows(world.vault))
    assert world.problems(target) == []


def test_fresh_ids_make_a_copy_each_time(world: World) -> None:
    data = world.export(audience="author")
    source = world.rows(world.vault)
    first = world.imported(world.vault, data)
    second = world.imported(world.vault, data)
    for report in (first, second):
        assert report["created"]["entities"] == len(source["entities"])
        # Tags, custom link types, kinds and fields, and media files are the vault's own.
        assert report["reused"] == {
            "custom_fields_defs": 3,
            "custom_fields_kinds": 1,
            "link_type_defs": 3,
            "media_items": 2,
            "tags": 5,
        }
    after = world.rows(world.vault)
    assert len(after["entities"]) == 3 * len(source["entities"])
    assert len({entity["id"] for entity in after["entities"]}) == len(after["entities"])
    assert len(after["links"]) == 3 * len(source["links"])
    assert world.problems(world.vault) == []
    # One changeset each, which undoes the import.
    changes = world.client.get(f"{world.base}/changes").json()["items"]
    assert changes[0]["id"] == second["changeset_id"]
    assert changes[0]["origin"] == "import"
    assert changes[0]["summary"].startswith("Imported “")
    reverted = world.client.post(f"{world.base}/changes/{second['changeset_id']}/revert")
    assert reverted.status_code == 200, reverted.json()
    assert len(world.rows(world.vault)["entities"]) == 2 * len(source["entities"])
    assert world.problems(world.vault) == []


def test_kept_ids_the_vault_has_the_same_are_left_alone(world: World) -> None:
    data = world.export(audience="author")
    before = world.rows(world.vault)
    report = world.imported(world.vault, data, ids="keep")
    assert report["created"] == {}
    assert report["updated"] == {}
    assert report["changeset_id"] is None  # nothing changed, nothing recorded
    assert world.rows(world.vault) == before


def test_kept_ids_that_differ_are_conflicts_or_overwritten(world: World) -> None:
    data = world.export(audience="author")
    entity = next(e for e in world.rows(world.vault)["entities"] if e["kind"] == "character")
    renamed = world.client.patch(
        f"{world.base}/entities/{entity['id']}",
        json={"name": "Renamed", "revision": entity["revision"]},
    )
    assert renamed.status_code == 200, renamed.json()
    before = world.rows(world.vault)
    refused = problem(world.import_(world.vault, data, ids="keep"), 409, "interchange_conflict")
    assert refused["context"]["count"] == 1
    assert refused["context"]["conflicts"] == [
        {
            "table": "entities",
            "id": entity["id"],
            "reason": "id",
            "columns": ["id"],
            "name": entity["name"],
        }
    ]
    assert world.rows(world.vault) == before  # nothing was imported
    backups = len(world.client.get(f"{world.base}/backups").json()["items"])
    report = world.imported(world.vault, data, ids="keep", on_conflict="overwrite")
    assert report["updated"] == {"entities": 1}
    assert report["created"] == {}
    shown = world.client.get(f"{world.base}/entities/{entity['id']}").json()
    assert shown["name"] == entity["name"]
    found = world.client.get(f"{world.base}/search", params={"q": entity["name"]}).json()
    assert entity["id"] in {hit["entity_id"] for hit in found["items"]}
    assert len(world.client.get(f"{world.base}/backups").json()["items"]) == backups + 1
    assert world.problems(world.vault) == []


def test_a_definition_that_differs_is_a_conflict_even_with_fresh_ids(world: World) -> None:
    data = world.export(audience="author")
    document = _document(data)
    link_type = document["tables"]["link_type_defs"][0]
    link_type["label"] = "Something else"
    bare = json.dumps({**document, "files": {}}).encode()  # a bare document: no files
    refused = problem(world.import_(world.vault, bare), 409, "interchange_conflict")
    assert refused["context"]["conflicts"][0]["table"] == "link_type_defs"
    assert refused["context"]["conflicts"][0]["id"] == link_type["key"]


# --- one dimension --------------------------------------------------------------------------------


def _dimension(world: World, name: str) -> str:
    rows = world.rows(world.vault)["entities"]
    return str(next(e["id"] for e in rows if e["kind"] == "dimension" and e["name"] == name))


def test_a_dimension_holds_its_records_and_refers_to_multiversal_ones(world: World) -> None:
    source = world.rows(world.vault)
    aetheria = _dimension(world, "Aetheria")
    data = world.export(audience="author", dimension="Aetheria")
    document = _document(data)
    assert document["scope"] == {"kind": "dimension", "dimension_id": aetheria, "name": "Aetheria"}
    entities = document["tables"]["entities"]
    assert {e["dimension_id"] for e in entities} == {None, aetheria}
    assert [e["id"] for e in entities if e["dimension_id"] is None] == [aetheria]
    multiversal = {
        e["id"]: e
        for e in source["entities"]
        if e["dimension_id"] is None and e["kind"] != "dimension"
    }
    references = document["references"]
    assert references
    assert all(reference["id"] in multiversal for reference in references)
    # Correspondences to other dimensions, and suppressions, stay home.
    assert document["tables"]["correspondences"] == []
    assert document["tables"]["consistency_suppressions"] == []
    # The same by id works too.
    assert (
        _document(world.export(audience="author", dimension=aetheria))["tables"]
        == document["tables"]
    )

    # Into a vault holding one of the referenced entities (matched by kind and name).
    target = world.new_vault()
    language = next(r for r in references if r["kind"] == "language")
    made = world.client.post(
        f"/api/v1/vaults/{target}/entities", json={"kind": "language", "name": language["name"]}
    )
    assert made.status_code == 201, made.json()
    report = world.imported(target, data)
    assert report["references_matched"] == 1
    assert {r["name"] for r in report["references_unmatched"]} == {
        r["name"] for r in references if r is not language
    }
    rows = world.rows(target)
    assert _names(rows) >= {e["name"] for e in entities} | {language["name"]}
    own = made.json()["entity"]["id"]
    assert any(own in (link["source_id"], link["target_id"]) for link in rows["links"])
    assert world.problems(target) == []


def test_a_dimension_goes_back_into_its_own_vault(world: World) -> None:
    data = world.export(audience="author", dimension="Mirror Earth")
    count = len(_document(data)["tables"]["entities"])
    report = world.imported(world.vault, data)
    assert report["created"]["entities"] == count
    assert report["references_unmatched"] == []
    assert world.problems(world.vault) == []


def test_an_unknown_dimension_is_not_found(world: World) -> None:
    response = world.client.get(f"{world.base}/export/interchange", params={"dimension": "Nowhere"})
    problem(response, 404, "not_found")


# --- readers --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def canary(tmp_path_factory: pytest.TempPathFactory) -> Canary:
    return build_canary_vault(tmp_path_factory.mktemp("canary"))


def test_a_readers_export_holds_no_private_data(canary: Canary) -> None:
    with leak_client(canary.data_dir) as client:
        manager: VaultManager = client.app.state.vaults  # type: ignore[attr-defined]
        out = io.BytesIO()
        export_interchange(manager, canary.vault, out, audience="readers")
        author = io.BytesIO()
        export_interchange(manager, canary.vault, author, audience="author")
    data = out.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        contents = b"".join(archive.read(name) for name in archive.namelist())
    assert [n for n in canary.needles if n.encode() in contents] == []
    # Not by leaving everything out: the public records are there.
    public = {**canary.public, **canary.records}
    assert [name for name, id_ in public.items() if id_.encode() not in contents] == []
    with zipfile.ZipFile(io.BytesIO(author.getvalue())) as archive:
        everything = b"".join(archive.read(name) for name in archive.namelist())
    assert [n for n in canary.strings if n.encode() not in everything] == []


def test_the_export_is_the_authors(world: World) -> None:
    url = f"{world.base}/export/interchange"
    problem(world.client.get(url, params={"as_reader": True}), 404, "not_found")


# --- older documents and broken files -----------------------------------------------------------


def _old_document(version: str) -> tuple[bytes, int]:
    """A document of a fixture vault's tables at its own schema revision (as the app of that
    version would have written it), with its media files; and its number of entities."""
    folder = FIXTURES / version / "vault"
    from lore.core.models import load_metadata as load_core_metadata  # noqa: PLC0415
    from lore.core.modules import ModuleRegistry  # noqa: PLC0415
    from lore.modules import ALL_MODULES  # noqa: PLC0415

    registry = ModuleRegistry(ALL_MODULES, core_metadata=load_core_metadata())
    current = {table.name: table for table in exported_tables(registry)}
    with closing(sqlite3.connect(folder / "lore.db")) as db:
        db.row_factory = sqlite3.Row
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        tables: dict[str, list[dict[str, Any]]] = {}
        for name, table in current.items():
            if name not in present:
                continue
            tables[name] = [
                {
                    key: encode_value(codec(table.c[key]), value) if key in table.c else value
                    for key, value in dict(row).items()
                }
                for row in db.execute(f'SELECT * FROM "{name}"')
            ]
    files: dict[str, Path] = {}
    for item in tables.get("media_items", []):
        path = folder / "media" / item["sha256"][:2] / item["sha256"]
        files[file_name("media_items", item["id"])] = path
    document = {
        "format": "lore-interchange",
        "format_version": 1,
        "app_version": version.removeprefix("v"),
        "schema_revision": revision,
        "exported_at": datetime.now(UTC).isoformat(),
        "source": {"vault_id": "old", "name": "Old"},
        "audience": "author",
        "scope": {"kind": "vault"},
        "modules": [],
        "tables": tables,
        "files": {name: sha256_of(path) for name, path in files.items()},
    }
    out = io.BytesIO()
    write_archive(out, document, files)
    return out.getvalue(), len(tables["entities"])


@pytest.mark.parametrize("version", ["v0.6.0", "v0.10.0"])
def test_a_document_of_an_older_schema_is_upgraded(world: World, version: str) -> None:
    data, entities = _old_document(version)
    assert _document(data)["schema_revision"] != world.manager.migrator.head()
    target = world.new_vault()
    report = world.imported(target, data)
    assert report["entities"] == entities
    assert report["dropped"] == {}
    assert world.problems(target) == []


def _broken(world: World, data: bytes, status: int, code: str) -> dict[str, Any]:
    return problem(world.import_(world.vault, data), status, code)


def test_broken_files_are_refused(world: World, tmp_path: Path) -> None:
    good = _document(world.export(audience="author"))
    _broken(world, b"not json", 422, "invalid_interchange")
    _broken(world, json.dumps({"format": "other"}).encode(), 422, "invalid_interchange")
    newer = {**good, "format_version": 2}
    _broken(world, json.dumps(newer).encode(), 409, "interchange_newer_than_app")
    unknown = {**good, "schema_revision": "ffffffffffff", "files": {}}
    _broken(world, json.dumps(unknown).encode(), 409, "interchange_newer_than_app")
    rows = json.loads(json.dumps(good["tables"]))
    rows["entities"][0]["surprise"] = 1
    _broken(world, json.dumps({**good, "tables": rows, "files": {}}).encode(), 422,
            "invalid_interchange")  # fmt: skip
    rows = json.loads(json.dumps(good["tables"]))
    rows["dimensions"][0]["duration"] = 12
    _broken(world, json.dumps({**good, "tables": rows, "files": {}}).encode(), 422,
            "invalid_interchange")  # fmt: skip
    # Files: listed but missing, not listed, a wrong checksum, an unsafe name.
    _broken(world, json.dumps(good).encode(), 422, "invalid_interchange")
    stray = io.BytesIO()
    with zipfile.ZipFile(stray, "w") as archive:
        archive.writestr(DOCUMENT_NAME, json.dumps({**good, "files": {}}))
        archive.writestr("files/media_items/x", b"x")
    _broken(world, stray.getvalue(), 422, "invalid_interchange")
    name = next(iter(good["files"]))
    lying = io.BytesIO()
    with zipfile.ZipFile(lying, "w") as archive:
        archive.writestr(DOCUMENT_NAME, json.dumps({**good, "files": {name: "0" * 64}}))
        archive.writestr(name, b"x")
    _broken(world, lying.getvalue(), 422, "invalid_interchange")
    unsafe = {**good, "files": {"../x": "0" * 64}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(DOCUMENT_NAME, json.dumps(unsafe))
    with pytest.raises(InvalidInterchangeError):
        read_archive(stream, tmp_path)


def test_a_file_that_isnt_its_media_item_is_refused(world: World) -> None:
    good = _document(world.export(audience="author"))
    name = next(iter(good["files"]))
    fake = b"<html>not an image</html>"
    document = {**good, "files": {**good["files"], name: hashlib.sha256(fake).hexdigest()}}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(DOCUMENT_NAME, json.dumps(document))
        for other in good["files"]:
            archive.writestr(other, fake if other == name else b"")
    response = world.import_(world.new_vault(), out.getvalue())
    assert response.status_code == 422, response.json()


def test_records_of_disabled_modules_are_refused(world: World) -> None:
    data = world.export(audience="author")
    target = world.new_vault()
    disabled = world.client.patch(f"/api/v1/vaults/{target}/modules/maps", json={"enabled": False})
    assert disabled.status_code == 200, disabled.json()
    refused = problem(world.import_(target, data), 409, "interchange_modules_disabled")
    assert refused["context"]["modules"] == ["maps"]
    assert world.rows(target)["entities"] == []


def test_a_read_only_server_doesnt_import(world: World, tmp_path: Path) -> None:
    data = world.export(audience="author")
    world.manager.close()
    app = create_app(Settings(data_dir=world.manager.data_dir, read_only=True))
    with local_client(app, headers=HEADERS) as reader:
        response = reader.post(
            f"{world.base}/import/interchange", files={"file": ("w.zip", data, "application/zip")}
        )
        problem(response, 403, "read_only")


# --- the CLI --------------------------------------------------------------------------------------


def test_cli_export_and_import(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = world.new_vault()
    world.manager.close()  # the CLI takes the vault lock
    monkeypatch.setenv("LORE_DATA_DIR", str(world.manager.data_dir))
    runner = CliRunner()
    out = tmp_path / "world.zip"
    command = ["vault", "export-json", world.vault, "--out", str(out), "--audience", "author"]
    exported = runner.invoke(cli.app, command)
    assert exported.exit_code == 0, exported.output
    assert exported.output.startswith(f"exported: {out}")
    again = runner.invoke(cli.app, command)
    assert again.exit_code == 1
    imported = runner.invoke(cli.app, ["vault", "import-json", target, str(out), "--keep-ids"])
    assert imported.exit_code == 0, imported.output
    assert imported.output.startswith("imported: ")
    clash = runner.invoke(cli.app, ["vault", "import-json", world.vault, str(out), "--keep-ids"])
    assert clash.exit_code == 0, clash.output  # the same records: nothing to do
    assert "0 records created" in clash.output
