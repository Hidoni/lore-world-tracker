from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from lore.core.entities.models import Entity
from lore.core.history import recorder
from lore.core.history.recorder import record_bulk, stored_row
from lore.core.history.service import REVERT_HOOKS
from lore.core.vaults import VaultManager
from tests.conftest import local_client
from tests.entity_api import HEADERS, LinkApi, make_client, new_app, problem
from tests.history_utils import (
    changes_of,
    changesets,
    no_changeset,
    one_changeset,
    snapshot,
    without_bookkeeping,
)

MISSING = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return new_app(tmp_path)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with local_client(app, headers=HEADERS) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> LinkApi:
    return LinkApi(client)


@pytest.fixture(autouse=True)
def _no_merging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests check one changeset per request; merging has its own tests."""
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))


def feed(api: LinkApi, **params: Any) -> dict[str, Any]:
    response = api.client.get(f"{api.base}/changes", params=params)
    assert response.status_code == 200, response.json()
    page: dict[str, Any] = response.json()
    return page


def history(api: LinkApi, entity_id: str, **params: Any) -> Any:
    return api.client.get(f"{api.base}/entities/{entity_id}/history", params=params)


def revert(api: LinkApi, changeset_id: str) -> Any:
    return api.client.post(f"{api.base}/changes/{changeset_id}/revert")


def latest(api: LinkApi) -> dict[str, Any]:
    item: dict[str, Any] = feed(api, limit=1)["items"][0]
    return item


# --- capture --------------------------------------------------------------------------------


def test_every_write_is_one_changeset(api: LinkApi, app: FastAPI) -> None:
    with one_changeset(app, api.vault) as created:
        entity = api.make("misc", "Ana", aliases=[{"alias": "A"}], tags=["Hero"],
                          fields={})  # fmt: skip
    assert created.changeset["origin"] == "api"
    assert created.changeset["summary"] == "Created misc “Ana”"
    assert created.changeset["request_id"]
    assert {(c["table_name"], c["op"]) for c in created.changes} == {
        ("entities", "insert"), ("entity_aliases", "insert"), ("tags", "insert"),
        ("entity_tags", "insert"),
    }  # fmt: skip
    with one_changeset(app, api.vault) as edited:
        entity = api.patch(entity, name="Anna", tags=[]).json()["entity"]
    assert edited.changeset["summary"] == "Edited “Anna”"
    other = api.make("misc", "Bo")
    with one_changeset(app, api.vault) as linked:
        link = api.made_link("core.related", entity, other)
    assert linked.changeset["summary"] == "Added 1 link"
    with one_changeset(app, api.vault):
        api.patch_link(link, role="friend")
    with one_changeset(app, api.vault) as unlinked:
        api.delete_link(link["id"])
    assert unlinked.changeset["summary"] == "Removed 1 link"
    with one_changeset(app, api.vault) as trashed:
        api.delete(entity["id"])
    assert trashed.changeset["summary"] == "Trashed “Anna”"
    with one_changeset(app, api.vault) as restored:
        api.restore(entity["id"])
    assert restored.changeset["summary"] == "Restored “Anna”"
    api.delete(entity["id"])
    with one_changeset(app, api.vault) as purged:
        api.delete(entity["id"], purge=True)
    assert purged.changeset["summary"] == "Purged “Anna”"
    with one_changeset(app, api.vault) as typed:
        api.link_types(label="knows")
    assert typed.changeset["summary"] == "Changed link types"


def test_no_changes_no_changeset(api: LinkApi, app: FastAPI) -> None:
    entity = api.make("misc")
    no_changeset(app, api.vault, lambda: api.get(entity["id"]))
    no_changeset(app, api.vault, lambda: api.patch(entity))  # nothing sent
    no_changeset(app, api.vault, lambda: api.create("misc", "   "))  # rolled back
    no_changeset(app, api.vault, lambda: api.modules("extra", enabled=False))  # settings


def test_origins(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = LinkApi(client)
        client.headers["X-Lore-Client"] = "web"
        api.make("misc")
        assert latest(api)["origin"] == "ui"
        client.headers["X-Lore-Client"] = "cli"
        api.make("misc")
        assert latest(api)["origin"] == "cli"


def test_record_bulk(api: LinkApi, app: FastAPI) -> None:
    entity = api.make("misc", "Bulk")
    manager: VaultManager = app.state.vaults
    vault = manager.open(api.vault)
    with one_changeset(app, api.vault) as recorded, vault.write_sessions.begin() as session:
        table = Entity.__table__
        before = stored_row(session, table, entity["id"])  # type: ignore[arg-type]
        session.execute(update(Entity).where(Entity.id == entity["id"]).values(summary="Bulk!"))
        after = stored_row(session, table, entity["id"])  # type: ignore[arg-type]
        assert before is not None
        assert after is not None
        assert after["summary"] == "Bulk!"
        record_bulk(session, table, [before], [after])  # type: ignore[arg-type]
        recorder.describe(session, "Bulk edit")
    assert recorded.changeset["summary"] == "Bulk edit"
    assert recorded.changeset["origin"] == "system"


# --- reads ----------------------------------------------------------------------------------


def test_feed_and_detail(api: LinkApi) -> None:
    first = api.make("misc", "First", fields={})
    api.make("gadget", "Second", fields={"text": "x", "measurement": {"value": "1", "unit": "m"}})
    page = feed(api)
    assert [item["summary"] for item in page["items"]] == [
        "Created gadget “Second”", "Created misc “First”",
    ]  # fmt: skip
    assert page["next_cursor"] is None
    item = page["items"][1]
    assert item["entities"] == [{"id": first["id"], "name": "First", "kind": "misc",
                                 "exists": True}]  # fmt: skip
    assert item["change_count"] == 1
    assert item["reverted_by_changeset_id"] is None
    one = feed(api, limit=1)
    assert len(one["items"]) == 1
    rest = feed(api, limit=1, cursor=one["next_cursor"])
    assert rest["items"][0]["id"] == item["id"]

    detail = api.client.get(f"{api.base}/changes/{page['items'][0]['id']}").json()
    [change] = detail["changes"]
    assert (change["table_name"], change["op"], change["before"]) == ("entities", "insert", None)
    assert change["after"]["fields"] == {"text": "x", "measurement": {"value": "1", "unit": "m"}}
    assert change["entity_ids"] == [change["row_id"]]
    problem(api.client.get(f"{api.base}/changes/{MISSING}"), 404, "not_found")


def test_entity_history(api: LinkApi) -> None:
    ana, bo = api.make("misc", "Ana"), api.make("misc", "Bo")
    api.patch(ana, aliases=[{"alias": "Annie"}])
    api.made_link("core.related", ana, bo)
    summaries = [i["summary"] for i in history(api, ana["id"]).json()["items"]]
    assert summaries == ["Added 1 link", "Edited “Ana”", "Created misc “Ana”"]
    assert [i["summary"] for i in history(api, bo["id"]).json()["items"]] == [
        "Added 1 link", "Created misc “Bo”",
    ]  # a link belongs to both ends  # fmt: skip
    page = history(api, ana["id"], limit=2).json()
    assert len(page["items"]) == 2
    rest = history(api, ana["id"], cursor=page["next_cursor"]).json()
    assert [i["summary"] for i in rest["items"]] == ["Created misc “Ana”"]
    # purged entities keep their history (decided 2026-10-04)
    api.delete(bo["id"])
    api.delete(bo["id"], purge=True)
    gone = history(api, bo["id"]).json()["items"]
    assert gone[0]["summary"] == "Purged “Bo”"
    assert {"id": bo["id"], "name": "Bo", "kind": "misc", "exists": False} in gone[0]["entities"]
    problem(history(api, MISSING), 404, "not_found")
    beast = api.make("beast")
    api.modules("extra", enabled=False)
    problem(history(api, beast["id"]), 404, "module_disabled")


def test_read_only_servers_hide_history(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        api = LinkApi(client)
        entity = api.make("misc")
        changeset = latest(api)["id"]
    with make_client(tmp_path, read_only=True) as client:
        api = LinkApi(client, api.vault)
        problem(client.get(f"{api.base}/changes"), 404, "not_found")
        problem(client.get(f"{api.base}/changes/{changeset}"), 404, "not_found")
        problem(history(api, entity["id"]), 404, "not_found")
        problem(revert(api, changeset), 403, "read_only")


# --- undo -----------------------------------------------------------------------------------


def test_undo_create(api: LinkApi, app: FastAPI) -> None:
    before = snapshot(app, api.vault)
    entity = api.make("misc", "Ana", aliases=[{"alias": "A"}], tags=["T"])
    with one_changeset(app, api.vault) as undo:
        response = revert(api, latest(api)["id"])
    assert response.status_code == 200
    result = response.json()
    assert result["changeset"]["origin"] == "undo"
    assert result["changeset"]["summary"] == "Undid: Created misc “Ana”"
    assert result["affected"]["entities"] == [entity["id"]]
    assert undo.changeset["reverts_changeset_id"] is not None
    assert snapshot(app, api.vault) == before
    problem(api.get(entity["id"]), 404, "not_found")
    undone = feed(api)["items"][1]
    assert undone["reverted_by_changeset_id"] == result["changeset"]["id"]


def test_undo_edit_restores_content_and_moves_the_revision_on(api: LinkApi, app: FastAPI) -> None:
    entity = api.make("misc", "Ana", summary="old", tags=["a"])
    before = snapshot(app, api.vault)
    edited = api.patch(entity, name="Anna", summary="new", tags=["b"]).json()["entity"]
    revert(api, latest(api)["id"])
    after = snapshot(app, api.vault)
    restored = api.get(entity["id"]).json()
    assert (restored["name"], restored["summary"], [t["name"] for t in restored["tags"]]) == (
        "Ana", "old", ["a"],
    )  # fmt: skip
    assert restored["revision"] == edited["revision"] + 1  # decided 2026-10-04
    assert restored["updated_at"] > edited["updated_at"]
    for key in before.keys() - {("tags", t["id"]) for t in edited["tags"]}:
        assert without_bookkeeping(after.get(key)) == without_bookkeeping(before[key])
    problem(api.patch(edited, name="stale"), 409, "revision_conflict")


def test_undo_purge_restores_everything(api: LinkApi, app: FastAPI) -> None:
    ana = api.make("misc", "Ana", aliases=[{"alias": "A"}], tags=["T"])
    bo = api.make("misc", "Bo")
    api.made_link("core.related", ana, bo)
    api.delete(ana["id"])
    before = snapshot(app, api.vault)
    api.delete(ana["id"], purge=True)
    purge = latest(api)["id"]
    assert revert(api, purge).status_code == 200
    after = snapshot(app, api.vault)
    assert after.keys() == before.keys()
    for key, row in before.items():
        assert without_bookkeeping(after[key]) == without_bookkeeping(row)
    key = ("entities", ana["id"])
    assert after[key]["revision"] == before[key]["revision"] + 1
    restored = api.get(ana["id"]).json()
    assert restored["deleted_at"] is not None  # back in the trash, as before the purge
    assert len(api.links_of(bo, include_trashed="true")) == 1


def test_undo_conflicts_and_redo(api: LinkApi) -> None:
    entity = api.make("misc", "One")
    entity = api.patch(entity, name="Two").json()["entity"]
    rename = latest(api)["id"]
    api.patch(entity, summary="later")
    body = problem(revert(api, rename), 409, "revert_conflict")
    assert body["context"] == {"rows": [{"table_name": "entities", "row_id": entity["id"],
                                         "op": "update"}]}  # fmt: skip
    # undo the later change first, then the rename
    assert revert(api, latest(api)["id"]).status_code == 200
    assert revert(api, rename).status_code == 200
    assert api.get(entity["id"]).json()["name"] == "One"
    problem(revert(api, rename), 409, "conflict")  # already undone
    # redo = undo the undo
    undo = latest(api)
    assert undo["reverts_changeset_id"] == rename
    assert revert(api, undo["id"]).status_code == 200
    assert api.get(entity["id"]).json()["name"] == "Two"
    problem(revert(api, MISSING), 404, "not_found")


def test_revert_hooks(api: LinkApi, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    hooks = [lambda _s, changes: calls.append([c.table_name for c in changes])]
    monkeypatch.setattr("lore.core.history.service.REVERT_HOOKS", hooks)
    api.make("misc")
    revert(api, latest(api)["id"])
    assert calls == [["entities"]]
    assert REVERT_HOOKS == []


# --- merging --------------------------------------------------------------------------------


@pytest.fixture
def merging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(minutes=2))


@pytest.mark.usefixtures("merging")
def test_consecutive_edits_of_one_entity_merge(api: LinkApi, app: FastAPI) -> None:
    entity = api.make("misc", "Draft", summary="a")
    created = len(changesets(app, api.vault))
    for text in ("ab", "abc", "abcd"):
        entity = api.patch(entity, summary=text, aliases=[{"alias": text}]).json()["entity"]
    sets = changesets(app, api.vault)
    assert len(sets) == created + 1
    merged = sets[-1]
    assert merged["updated_at"] > merged["created_at"]
    [row] = [c for c in changes_of(app, api.vault, merged["id"]) if c["table_name"] == "entities"]
    assert (row["before"]["summary"], row["after"]["summary"]) == ("a", "abcd")
    aliases = [c for c in changes_of(app, api.vault, merged["id"])
               if c["table_name"] == "entity_aliases"]  # fmt: skip
    assert [(c["op"], c["after"]["alias"]) for c in aliases] == [("insert", "abcd")]
    # one undo reverts the whole burst
    revert(api, merged["id"])
    assert api.get(entity["id"]).json()["summary"] == "a"
    assert api.get(entity["id"]).json()["aliases"] == []


@pytest.mark.usefixtures("merging")
def test_what_does_not_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(tmp_path) as client:
        api = LinkApi(client)
        app = client.app
        ana, bo = api.make("misc", "Ana"), api.make("misc", "Bo")
        count = len(changesets(app, api.vault))  # type: ignore[arg-type]

        def step(action: Any) -> int:
            nonlocal count
            action()
            new = len(changesets(app, api.vault))  # type: ignore[arg-type]
            added, count = new - count, new
            return added

        def edit(entity: dict[str, Any], **body: Any) -> Any:
            return lambda: api.patch(api.get(entity["id"]).json(), **body)

        assert step(edit(ana, summary="1")) == 1  # creating isn't an edit: no merge into it
        assert step(edit(ana, summary="2")) == 0
        assert step(edit(bo, summary="1")) == 1  # another entity in between
        assert step(edit(ana, summary="3")) == 1
        assert step(lambda: api.delete(ana["id"])) == 1  # trash never merges
        assert step(lambda: api.restore(ana["id"])) == 1
        assert step(edit(ana, summary="4")) == 1
        client.headers["X-Lore-Client"] = "web"
        assert step(edit(ana, summary="5")) == 1  # another client
        assert (
            step(edit(ana, links_add=[{"link_type": "core.related", "target_id": bo["id"]}])) == 1
        )  # two entities
        client.headers["X-Lore-Client"] = "test"
        assert step(edit(ana, summary="6")) == 1
        revert(api, latest(api)["id"])
        count += 1
        assert step(edit(ana, summary="7")) == 1  # after an undo
        monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
        assert step(edit(ana, summary="8")) == 1  # outside the window


@pytest.mark.usefixtures("merging")
def test_edits_back_to_the_start_leave_no_changeset(api: LinkApi, app: FastAPI) -> None:
    entity = api.make("misc", summary="same")
    count = len(changesets(app, api.vault))
    api.patch(api.get(entity["id"]).json(), summary="changed")
    api.patch(api.get(entity["id"]).json(), summary="same")
    sets = changesets(app, api.vault)
    # the summary is back: only the revision/updated_at bookkeeping remains changed
    assert len(sets) == count + 1
    [row] = changes_of(app, api.vault, sets[-1]["id"])
    assert without_bookkeeping(row["before"]) == without_bookkeeping(row["after"])


def test_entities_query_helper_untouched(api: LinkApi, app: FastAPI) -> None:
    """Reads through the vault's read sessions never write history."""
    entity = api.make("misc")
    manager: VaultManager = app.state.vaults
    count = len(changesets(app, api.vault))
    with manager.open(api.vault).sessions.begin() as session:
        assert session.scalar(select(Entity.name).where(Entity.id == entity["id"]))
    assert len(changesets(app, api.vault)) == count


def test_openapi_operations(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    base = "/api/v1/vaults/{vault_id}"
    assert paths[f"{base}/changes"]["get"]["operationId"] == "changes_list"
    assert paths[f"{base}/changes/{{changeset_id}}"]["get"]["operationId"] == "changes_get"
    assert paths[f"{base}/changes/{{changeset_id}}/revert"]["post"]["operationId"] == (
        "changes_revert"
    )
    assert paths[f"{base}/entities/{{entity_id}}/history"]["get"]["operationId"] == (
        "entities_history"
    )


# --- undo keeps the rules (an undo is a save like any other) --------------------------------


def refused(api: LinkApi, app: FastAPI, changeset_id: str) -> list[str]:
    """Assert the undo is refused with problems and changes nothing; return the messages."""
    before = snapshot(app, api.vault)
    body = problem(revert(api, changeset_id), 409, "revert_conflict")
    assert snapshot(app, api.vault) == before
    return [p["message"] for p in body["context"]["problems"]]


def test_undo_respects_link_limits(api: LinkApi, app: FastAPI) -> None:
    old, new = api.make("misc", "Old owner"), api.make("misc", "New owner")
    gadget = api.make("gadget", "Engine")
    link = api.made_link("world.owns", old, gadget)
    api.delete_link(link["id"])
    removal = latest(api)["id"]
    api.made_link("world.owns", new, gadget)  # one owner at most
    [message] = refused(api, app, removal)
    assert "at most 1" in message
    assert summary_of(api.links_of(gadget)) == ["New owner"]


def summary_of(items: list[dict[str, Any]]) -> list[str]:
    return [item["other"]["name"] for item in items]


def test_undo_respects_parent_rules(api: LinkApi, app: FastAPI) -> None:
    b = api.make("misc", "B")
    a = api.make("misc", "A", parent_id=b["id"])
    api.patch(a, parent_id=None)
    move = latest(api)["id"]
    api.patch(api.get(b["id"]).json(), parent_id=a["id"])  # now B is under A
    [message] = refused(api, app, move)
    assert message == "A: its parent chain would loop back to it."


def test_undo_respects_required_fields(tmp_path: Path) -> None:
    from dataclasses import replace  # noqa: PLC0415

    from tests.entity_modules import EXTRA, WORLD  # noqa: PLC0415

    with make_client(tmp_path) as client:
        api = LinkApi(client)
        gadget = api.make("gadget")
        api.patch(gadget, fields={"text": "set"})
        edit = latest(api)["id"]
    kinds = tuple(
        replace(k, fields=tuple(replace(f, required=f.key == "text") for f in k.fields))
        if k.key == "gadget" else k
        for k in WORLD.kinds
    )  # fmt: skip
    with make_client(tmp_path, (replace(WORLD, kinds=kinds), EXTRA)) as client:
        api = LinkApi(client, api.vault)
        app = client.app
        assert refused(api, app, edit) == ["Thing: Text is required"]  # type: ignore[arg-type]


def test_undoing_a_creation_after_the_entity_got_children_or_links(
    api: LinkApi, app: FastAPI
) -> None:
    folder = api.make("misc", "Folder")
    creation = latest(api)["id"]
    child = api.make("misc", "Child", parent_id=folder["id"])
    messages = refused(api, app, creation)
    assert messages == [
        "A row of entities added or changed later still refers to it (entities): undo or "
        "delete that first."
    ]
    api.delete(child["id"])
    api.delete(child["id"], purge=True)
    link = api.made_link("core.related", folder, api.make("misc", "Other"))
    assert len(refused(api, app, creation)) == 1
    api.delete_link(link["id"])
    assert len(refused(api, app, creation)) == 1  # a trashed link still refers to it
    revert(api, latest(api)["id"])  # undo the link's trash...
    revert(api, feed(api)["items"][2]["id"])  # ...and its creation (newest first: 2 = create)
    assert revert(api, creation).status_code == 200


def test_undo_respects_custom_link_types(api: LinkApi, app: FastAPI) -> None:
    created = api.link_types(label="mentors", max_targets_per_source=1).json()
    creation = latest(api)["id"]
    a, b, c = api.make("misc", "A"), api.make("misc", "B"), api.make("misc", "C")
    api.made_link("custom.mentors", a, b)
    assert refused(api, app, creation) == ["1 links use the link type 'custom.mentors' now."]
    api.patch_type(created, max_targets_per_source=None)
    relaxed = latest(api)["id"]
    api.made_link("custom.mentors", a, c)
    [message] = refused(api, app, relaxed)
    assert message == (
        "Existing links break the link type 'custom.mentors': max_targets_per_source (1)"
    )
