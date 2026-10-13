"""Facts (``time-model.md`` §10.2-§10.4, ``data-model.md`` §6.3) and time-point fields in
propagation (§5.6): CRUD, validation, validity anchored to events, multiversal entities,
search and visibility."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select

from lore.core.time.models import EntityTimeField
from lore.core.vaults.manager import TIME_FIELDS_SYNCED, _ensure_time_fields
from lore.core.vaults.meta import VaultMeta
from tests.entity_api import Api, make_client, problem

DAY = 86_400


def absolute(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base"}


def after(record_type: str, record_id: str, slot: str, units: int = 0) -> dict[str, Any]:
    ref = {"type": record_type, "id": record_id, "slot": slot}
    offset = {"kind": "base", "units": str(units)}
    return {"anchor": {"kind": "relative", "ref": ref, "offset": offset}, "precision": "base"}


class World:
    """Aetheria (with a calendar) and its prime timeline, a gadget and an event."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.dimension = api.make("dimension", "Aetheria")
        self.calendar = api.calendar(self.dimension["id"])
        self.timeline = self.dimension["ext"]["prime_timeline_id"]
        self.gadget = api.make("gadget", "Engine", dimension_id=self.dimension["id"])
        self.event = api.make(
            "event", "Forging", dimension_id=self.dimension["id"],
            ext={"start": absolute(100 * DAY)},
        )  # fmt: skip

    def facts(self, entity: dict[str, Any] | None = None, **params: Any) -> list[dict[str, Any]]:
        entity = entity or self.gadget
        response = self.api.client.get(f"{self.api.base}/entities/{entity['id']}/facts",
                                       params=params)  # fmt: skip
        assert response.status_code == 200, response.json()
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    def add(self, entity: dict[str, Any] | None = None, **body: Any) -> Any:
        entity = entity or self.gadget
        body.setdefault("timeline_id", self.timeline)
        return self.api.client.post(f"{self.api.base}/entities/{entity['id']}/facts", json=body)

    def made(self, entity: dict[str, Any] | None = None, **body: Any) -> dict[str, Any]:
        response = self.add(entity, **body)
        assert response.status_code == 201, response.json()
        fact: dict[str, Any] = response.json()["fact"]
        return fact

    def patch(self, fact: dict[str, Any], **body: Any) -> Any:
        body.setdefault("revision", fact["revision"])
        return self.api.client.patch(f"{self.api.base}/facts/{fact['id']}", json=body)

    def delete(self, fact: dict[str, Any]) -> Any:
        return self.api.client.delete(f"{self.api.base}/facts/{fact['id']}")


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with make_client(tmp_path) as client:
        yield World(Api(client))


def test_crud(world: World) -> None:
    first = world.made(field_key="rank", value="3", valid_to=absolute(50 * DAY), note="squire")
    assert (first["value"], first["valid_from_t"], first["valid_to_t"]) == (
        "3",
        None,
        str(50 * DAY),
    )
    assert (first["time_status"], first["visibility"], first["note"]) == ("ok", "public", "squire")
    second = world.made(field_key="rank", value="7", valid_from=absolute(50 * DAY),
                        source_event_id=world.event["id"])  # fmt: skip
    world.made(field_key="core.exists", valid_from=absolute(0))
    # By field, then start (open starts first).
    assert [(f["field_key"], f["value"]) for f in world.facts()] == [
        ("core.exists", True), ("rank", "3"), ("rank", "7")
    ]  # fmt: skip
    assert [f["value"] for f in world.facts(field="rank")] == ["3", "7"]
    assert world.facts(timeline=world.event["id"]) == []

    updated = world.patch(second, value="8", note="knight")
    assert updated.status_code == 200, updated.json()
    assert (updated.json()["fact"]["value"], updated.json()["fact"]["revision"]) == ("8", 2)
    problem(world.patch(second, value="9"), 409, "revision_conflict")

    deleted = world.delete(first)
    assert deleted.status_code == 200, deleted.json()
    assert deleted.json()["fact"]["deleted_at"] is not None
    assert [f["value"] for f in world.facts(field="rank")] == ["8"]
    problem(world.patch(first, value="1"), 404, "not_found")


def test_validation(world: World) -> None:
    def refused(code: str = "validation_error", **body: Any) -> list[str]:
        body = problem(world.add(**body), 422, code)
        return [error["path"] for error in body["errors"]]

    assert refused(field_key="text", value="x") == ["field_key"]  # not temporal
    assert refused(field_key="nope", value="x") == ["field_key"]
    assert refused(field_key="rank", value="many") == ["value"]
    assert refused(field_key="rank") == ["value"]
    assert refused(field_key="core.exists", value=False) == ["value"]
    assert refused(field_key="core.name", value=" ") == ["value"]
    assert refused(field_key="rank", value="1", source_event_id=world.gadget["id"]) == [
        "source_event_id"
    ]
    assert refused(field_key="rank", value="1", overrides_id=world.event["id"]) == ["overrides_id"]
    assert refused(field_key="rank", value="1", timeline_id=world.event["id"]) == ["timeline_id"]
    other = world.api.make("dimension", "Elsewhere")
    assert refused(field_key="rank", value="1", timeline_id=other["ext"]["prime_timeline_id"]) == [
        "timeline_id"
    ]
    # A bound that doesn't resolve (a slot that doesn't exist).
    nowhere = after("event", world.gadget["id"], "start")
    body = problem(
        world.add(field_key="rank", value="1", valid_from=nowhere), 422, "time_constraint"
    )
    assert body["errors"]
    # A typed value is normalized by its field type.
    lore = world.made(field_key="lore", value={"type": "doc", "content": []})
    assert lore["value"] == {"type": "doc", "content": []}
    assert world.made(field_key="core.name", value="  Old Engine ")["value"] == "Old Engine"


def test_validity_anchored_to_an_event_moves_with_it(world: World) -> None:
    fact = world.made(field_key="rank", value="2",
                      valid_from=after("event", world.event["id"], "start", DAY))  # fmt: skip
    assert fact["valid_from_t"] == str(101 * DAY)
    moved = world.api.patch(world.event, ext={"start": absolute(200 * DAY)})
    assert moved.status_code == 200, moved.json()
    assert world.facts(field="rank")[0]["valid_from_t"] == str(201 * DAY)
    # A fact's bounds may be referenced in turn.
    later = world.made(field_key="rank", value="3",
                       valid_from=after("fact", fact["id"], "valid_from", DAY))  # fmt: skip
    assert later["valid_from_t"] == str(202 * DAY)


def test_multiversal_entity_facts_in_two_dimensions(world: World) -> None:
    traveller = world.api.make("gadget", "Wanderer")  # no dimension: multiversal
    other = world.api.make("dimension", "Elsewhere")
    world.api.calendar(other["id"])
    here = world.made(traveller, field_key="core.exists", valid_from=absolute(5 * DAY))
    there = world.made(traveller, field_key="core.exists",
                       timeline_id=other["ext"]["prime_timeline_id"],
                       valid_from=absolute(9 * DAY))  # fmt: skip
    assert {f["timeline_id"] for f in world.facts(traveller)} == {
        world.timeline,
        other["ext"]["prime_timeline_id"],
    }
    assert (here["valid_from_t"], there["valid_from_t"]) == (str(5 * DAY), str(9 * DAY))


def test_time_point_fields_and_facts_propagate(world: World) -> None:
    api = world.api
    start = after("event", world.event["id"], "start", DAY)
    gadget = api.make("gadget", "Clock", dimension_id=world.dimension["id"],
                      fields={"time_point": start})  # fmt: skip
    era = world.made(gadget, field_key="era", value=after("event", world.event["id"], "start"))
    assert era["value_t"] == str(100 * DAY)
    assert api.patch(world.event, ext={"start": absolute(300 * DAY)}).status_code == 200
    assert world.facts(gadget, field="era")[0]["value_t"] == str(300 * DAY)
    # The entity's own time-point field resolves too: its value can be referenced by nothing,
    # but an unresolvable one is refused.
    refused = api.patch(gadget, fields={"time_point": after("event", gadget["id"], "start")})
    problem(refused, 422, "time_constraint")
    # A multiversal entity keeps its value without a moment.
    drifter = api.make("gadget", "Drifter", fields={"time_point": absolute(5)})
    assert drifter["fields"]["time_point"]["anchor"] == absolute(5)["anchor"]


def test_search_and_visibility(world: World) -> None:
    api = world.api
    world.made(field_key="core.name", value="Thundermaw")
    world.made(field_key="rank", value="4", visibility="private")
    world.made(field_key="hidden_rank", value="9")
    hits = api.client.get(f"{api.base}/search", params={"q": "Thundermaw"}).json()["items"]
    assert [hit["entity_id"] for hit in hits] == [world.gadget["id"]]

    def reader(**params: Any) -> list[tuple[str, Any]]:
        params["as_reader"] = "true"
        items = world.facts(**params)
        return [(f["field_key"], f["value"]) for f in items]

    # Readers see public facts of fields they may see.
    assert reader() == [("core.name", "Thundermaw")]
    sourced = world.made(field_key="rank", value="5", source_event_id=world.event["id"])
    api.patch(world.event, visibility="private")
    shown = next(f for f in world.facts(as_reader="true") if f["id"] == sourced["id"])
    assert shown["source_event_id"] is None
    private = api.make("gadget", "Secret", dimension_id=world.dimension["id"],
                       visibility="private")  # fmt: skip
    problem(api.client.get(f"{api.base}/entities/{private['id']}/facts",
                           params={"as_reader": "true"}), 404, "not_found")  # fmt: skip


def test_purge_and_history(world: World) -> None:
    api = world.api
    fact = world.made(field_key="rank", value="1", source_event_id=world.event["id"])
    changes = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"]
    reverted = api.client.post(f"{api.base}/changes/{changes[0]['id']}/revert")
    assert reverted.status_code == 200, reverted.json()
    assert world.facts() == []
    fact = world.made(field_key="rank", value="1", source_event_id=world.event["id"])
    assert api.delete(world.event["id"]).status_code == 200
    assert api.delete(world.event["id"], purge=True).status_code == 200
    assert world.facts()[0]["source_event_id"] is None
    assert api.delete(world.gadget["id"]).status_code == 200
    purged = api.delete(world.gadget["id"], purge=True)
    assert purged.status_code == 200, purged.json()
    del fact


def test_stored_time_fields_resolve_and_older_vaults_sync_on_open(world: World) -> None:
    api = world.api
    start = after("event", world.event["id"], "start", DAY)
    gadget = api.make("gadget", "Clock", dimension_id=world.dimension["id"],
                      fields={"time_point": start})  # fmt: skip
    vault = api.client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]

    def rows() -> dict[str, tuple[str | None, str | None]]:
        with vault.sessions() as session:
            return {
                row.field_key: (None if row.t is None else str(row.t), row.time_status)
                for row in session.scalars(
                    select(EntityTimeField).where(EntityTimeField.entity_id == gadget["id"])
                )
            }

    assert rows() == {"time_point": (str(101 * DAY), "ok")}
    # A vault from before the table: its values get rows (and resolve) when it opens.
    with vault.write_sessions.begin() as session:
        session.execute(delete(EntityTimeField))
        session.execute(delete(VaultMeta).where(VaultMeta.key == TIME_FIELDS_SYNCED))
    assert rows() == {}
    assert vault.registry is not None
    with vault.write_sessions.begin() as session:
        _ensure_time_fields(vault, session, vault.registry)
    assert rows() == {"time_point": (str(101 * DAY), "ok")}


def test_changes_caused_by_an_event(world: World) -> None:
    caused = world.made(field_key="rank", value="2", source_event_id=world.event["id"])
    world.made(field_key="rank", value="1")  # no source
    other = world.api.make("gadget", "Clock", dimension_id=world.dimension["id"])
    named = world.made(other, field_key="core.name", value="Old Clock",
                       source_event_id=world.event["id"])  # fmt: skip
    url = f"{world.api.base}/facts"
    response = world.api.client.get(url, params={"source_event": world.event["id"]})
    assert response.status_code == 200, response.json()
    assert {f["id"] for f in response.json()["items"]} == {caused["id"], named["id"]}
    # Trashed facts drop out; a non-event or a missing id is 404.
    assert world.delete(caused).status_code == 200
    items = world.api.client.get(url, params={"source_event": world.event["id"]}).json()["items"]
    assert [f["id"] for f in items] == [named["id"]]
    problem(world.api.client.get(url, params={"source_event": world.gadget["id"]}), 404,
            "not_found")  # fmt: skip
