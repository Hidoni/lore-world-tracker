"""Read-only server mode (``visibility-and-sharing.md`` §7, R-SHR-1): every mutating route is
``403 read_only`` before routing, a full read-only run changes no file of the data folder, and
only the exposed vaults are served."""

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text

from lore.core.db import create_vault_engine, writer_active
from lore.core.vaults import VaultManager
from tests.entity_api import Api, LinkApi, make_client
from tests.entity_modules import with_real_modules

SAFE = {"GET", "HEAD", "OPTIONS"}
DUMMY_ID = "01999999-0000-7000-8000-000000000000"


def _checksums(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _author_world(data_dir: Path) -> str:
    """A vault with some content, written by an author server that is then shut down."""
    with make_client(data_dir, with_real_modules()) as client:
        api = LinkApi(client)
        world = api.make("dimension", "Aetheria")
        home = {"dimension_id": world["id"]}
        api.calendar(world["id"])
        varn = api.make("location", "Varn", **home)
        ilsa = api.make("character", "Ilsa", **home, body={"type": "doc", "content": []})
        api.made_link("locations.resides_in", ilsa, varn)
        return api.vault


def _filled(path: str, vault: str) -> str:
    """A route's path with its parameters filled in (the vault's id, a dummy id elsewhere)."""
    path = path.replace("{vault_id}", vault)
    return re.sub(r"\{[^}]+\}", DUMMY_ID, path)


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    )


def test_every_mutating_route_is_refused_before_routing(tmp_path: Path) -> None:
    vault = _author_world(tmp_path)
    with make_client(tmp_path, with_real_modules(), read_only=True) as client:
        assert isinstance(client.app, FastAPI)
        mutating = [(m, p) for m, p in _routes(client.app) if m not in SAFE]
        assert len(mutating) > 50
        for method, path in mutating:
            response = client.request(method, _filled(path, vault), json={})
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["code"] == "read_only", (method, path)
        # Also where no route exists, and without the client header (no CSRF check first).
        response = client.post("/api/v1/nowhere", headers={"X-Lore-Client": ""})
        assert (response.status_code, response.json()["code"]) == (403, "read_only")


def test_a_read_only_run_changes_no_file(tmp_path: Path) -> None:
    vault = _author_world(tmp_path)
    before = _checksums(tmp_path)
    with make_client(tmp_path, with_real_modules(), read_only=True) as client:
        assert isinstance(client.app, FastAPI)
        api = Api(client, vault)
        entities = client.get(f"{api.base}/entities").json()["items"]
        assert {e["name"] for e in entities} >= {"Aetheria", "Varn", "Ilsa"}
        ids = [entity["id"] for entity in entities]
        for _method, path in [(m, p) for m, p in _routes(client.app) if m == "GET"]:
            targets = [_filled(path, vault)]
            if "{entity_id}" in path:
                targets += [_filled(path.replace("{entity_id}", i), vault) for i in ids]
            for target in targets:
                response = client.get(target)
                assert response.status_code < 500, (target, response.text)
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            client.request(method, f"{api.base}/entities", json={"kind": "misc", "name": "X"})
        assert client.get("/api/v1/meta").json()["read_only"] is True
    assert _checksums(tmp_path) == before


def test_only_exposed_vaults_are_served(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        shown = Api(client).vault
        hidden = Api(client).vault
    folder = next(p.name for p in (tmp_path / "vaults").iterdir() if p.name.endswith(shown[:8]))
    with make_client(tmp_path, read_only=True, exposed_vaults=[folder]) as client:
        listed = [vault["id"] for vault in client.get("/api/v1/vaults").json()["items"]]
        assert listed == [shown]
        assert client.get(f"/api/v1/vaults/{shown}/registry").status_code == 200
        for path in ("", "/registry", "/entities"):
            response = client.get(f"/api/v1/vaults/{hidden}{path}")
            assert response.status_code == 404, (path, response.json())
        assert client.get("/api/v1/meta").json()["exposed_vaults"] == [folder]


def test_a_vault_an_author_is_writing_is_read_through_the_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an author server writing the same folder (its ``-wal`` exists), readers open the
    database ``mode=ro`` (not ``immutable``), so they see the author's committed writes; with no
    writer, ``immutable``."""
    calls: list[dict[str, Any]] = []

    def spy(path: Path, **options: Any) -> Any:
        calls.append(options)
        return create_vault_engine(path, **options)

    monkeypatch.setattr("lore.core.vaults.manager.create_vault_engine", spy)
    author = VaultManager(tmp_path)
    info = author.create("Aetheria")
    try:
        opened = author.open(info.id)
        with opened.write_sessions.begin() as session:
            session.execute(text("CREATE TABLE seen (x)"))
        assert writer_active(info.database_path)
        reader = VaultManager(tmp_path, read_only=True)
        try:
            calls.clear()
            engine = reader.open(info.id).engine
            assert calls == [{"read_only": True, "immutable": False}]
            with engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM seen")).scalar() == 0
        finally:
            reader.close()
    finally:
        author.close()
    assert not writer_active(info.database_path)
    reader = VaultManager(tmp_path, read_only=True)
    try:
        calls.clear()
        reader.open(info.id)
        assert calls == [{"read_only": True, "immutable": True}]
    finally:
        reader.close()
