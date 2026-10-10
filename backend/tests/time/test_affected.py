"""``affected`` of write responses after time propagation (``frontend.md`` §5.1, ``api.md`` §2,
``time-model.md`` §7.2): the entities whose moments or statuses a write changed, their
dimensions and ``time_changed``."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lore.chronology.schema import TimePoint
from lore.core.history import recorder
from lore.core.history.tables import HistoryTable
from lore.core.modules import ModuleSpec
from lore.core.modules.spec import VaultContext
from lore.core.time import SlotDef, SlotProvider, moment_column, spec_column, status_column
from lore.core.time.changes import moved_entities
from lore.core.time.propagate import TimeWriter
from lore.core.time.specs import parse_time_point
from tests.entity_api import LinkApi, make_client
from tests.entity_modules import ENTITY_MODULES
from tests.time.test_events import after, at, event, in_year
from tests.time.test_proposals import two_months

D = 10**12


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LinkApi]:
    monkeypatch.setattr(recorder, "MERGE_WINDOW", timedelta(0))
    with make_client(tmp_path) as client:
        yield LinkApi(client)


@pytest.fixture
def world(api: LinkApi) -> dict[str, Any]:
    dimension = api.make("dimension", "Aetheria")
    return {"dimension": dimension, "calendar": api.calendar(dimension["id"])}


@pytest.fixture
def chain(api: LinkApi, world: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Wedding ← Feast ← Hangover (each anchored to the one before), and a Duel on its own."""
    wedding = event(api, world, "Wedding", start=at(100))
    feast = event(api, world, "Feast", start=after(wedding, 5))
    hangover = event(api, world, "Hangover", start=after(feast, 5))
    return {
        "wedding": wedding,
        "feast": feast,
        "hangover": hangover,
        "duel": event(api, world, "Duel", start=at(7)),
    }


def affected(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.json()
    found: dict[str, Any] = response.json()["affected"]
    return found


def ids(*entities: dict[str, Any]) -> set[str]:
    return {entity["id"] for entity in entities}


def last_change(api: LinkApi) -> str:
    found: str = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]["id"]
    return found


def undo(api: LinkApi, changeset_id: str) -> Any:
    return api.client.post(f"{api.base}/changes/{changeset_id}/revert")


def test_moving_an_anchor_reports_its_dependents(
    api: LinkApi, world: dict[str, Any], chain: dict[str, dict[str, Any]]
) -> None:
    wedding, feast, hangover = chain["wedding"], chain["feast"], chain["hangover"]
    moved = affected(api.patch(wedding, ext={"start": at(200)}))
    assert moved["entities"][0] == wedding["id"]  # the written entity comes first
    assert set(moved["entities"]) == ids(wedding, feast, hangover)
    assert len(moved["entities"]) == 3  # each once
    assert moved["dimensions"] == [world["dimension"]["id"]]
    assert moved["time_changed"] is True

    # Moving the middle of the chain doesn't touch what it is anchored to.
    middle = affected(api.patch(feast, ext={"start": after(wedding, 9)}))
    assert set(middle["entities"]) == ids(feast, hangover)
    assert middle["time_changed"] is True


def test_writes_that_move_nothing(api: LinkApi, chain: dict[str, dict[str, Any]]) -> None:
    wedding = chain["wedding"]
    renamed = affected(api.patch(wedding, name="The Wedding"))
    assert renamed["entities"] == [wedding["id"]]
    assert renamed["time_changed"] is False

    wedding = api.get(wedding["id"]).json()
    same = affected(api.patch(wedding, ext={"start": at(100), "importance": 5}))
    assert (same["entities"], same["time_changed"]) == ([wedding["id"]], False)

    # The same moment, typed another way: the anchor changes, the moment doesn't.
    feast = chain["feast"]
    retyped = affected(api.patch(feast, ext={"start": at(105)}))
    assert (retyped["entities"], retyped["time_changed"]) == ([feast["id"]], False)


def test_a_new_event_is_a_time_change(api: LinkApi, world: dict[str, Any]) -> None:
    created = api.create(
        "event", "Duel", dimension_id=world["dimension"]["id"], ext={"start": at(7)}
    )
    found = affected(created, 201)
    assert found["entities"] == [created.json()["entity"]["id"]]
    assert found["time_changed"] is True
    other = affected(api.create("dimension", "Elsewhere"), 201)
    assert other["time_changed"] is False


def test_calendar_edits(api: LinkApi) -> None:
    dimension = api.make("dimension", "Aetheria")
    calendar = api.make(
        "calendar", "Reckoning", dimension_id=dimension["id"], ext={"definition": two_months()}
    )
    world = {"dimension": dimension, "calendar": calendar}
    dated = event(api, world, "Dated", start=in_year(calendar, 3))
    follower = event(api, world, "Follower", start=after(dated, 5))
    fixed = event(api, world, "Fixed", start=at(7))
    proposal = api.client.post(
        f"{api.base}/calendars/{calendar['id']}/proposals",
        json={"definition": two_months(frost=32)},
    ).json()
    applied = affected(
        api.client.post(
            f"{api.base}/calendars/{calendar['id']}/proposals/{proposal['id']}/apply", json={}
        )
    )
    assert ids(dated, follower, calendar) <= set(applied["entities"])
    assert fixed["id"] not in applied["entities"]
    assert applied["dimensions"] == [dimension["id"]]
    assert applied["time_changed"] is True


def test_dimension_duration_and_present(api: LinkApi, world: dict[str, Any]) -> None:
    dimension = world["dimension"]
    lasting = event(api, world, "Reign", start=at(10), end={"kind": "end_of_time"})
    brief = event(api, world, "Duel", start=at(7))
    longer = affected(api.patch(dimension, ext={"duration": str(2 * D)}))
    assert set(longer["entities"]) == ids(dimension, lasting)
    assert brief["id"] not in longer["entities"]
    assert dimension["id"] in longer["dimensions"]
    assert longer["time_changed"] is True

    dimension = api.get(dimension["id"]).json()
    now = affected(api.patch(dimension, ext={"present": after(brief, 1)}))
    assert (now["entities"], now["time_changed"]) == ([dimension["id"]], True)
    assert now["dimensions"] == [dimension["id"]]

    # The present follows its anchor.
    moved = affected(api.patch(brief, ext={"start": at(8)}))
    assert set(moved["entities"]) == ids(brief, dimension)
    assert moved["time_changed"] is True


def test_trash_restore_and_purge_of_an_anchor_target(
    api: LinkApi, chain: dict[str, dict[str, Any]]
) -> None:
    wedding, duel = chain["wedding"], chain["duel"]
    chained = ids(wedding, chain["feast"], chain["hangover"])
    alone = affected(api.delete(duel["id"]))
    assert (alone["entities"], alone["time_changed"]) == ([duel["id"]], False)

    # What is anchored to the Wedding, directly or not, is now `trashed_ref`.
    trashed = affected(api.delete(wedding["id"]))
    assert set(trashed["entities"]) == chained
    assert trashed["time_changed"] is True
    again = affected(api.delete(wedding["id"]))  # idempotent: nothing changes
    assert (again["entities"], again["time_changed"]) == ([wedding["id"]], False)

    restored = affected(api.restore(wedding["id"]))
    assert set(restored["entities"]) == chained
    assert restored["time_changed"] is True

    api.delete(wedding["id"])
    purged = affected(api.delete(wedding["id"], purge=True))  # the Feast is frozen: `ok` again
    assert set(purged["entities"]) == chained
    assert purged["time_changed"] is True


def test_undo(api: LinkApi, chain: dict[str, dict[str, Any]]) -> None:
    wedding, feast, hangover = chain["wedding"], chain["feast"], chain["hangover"]
    api.patch(wedding, ext={"start": at(200)})
    undone = affected(undo(api, last_change(api)))
    assert set(undone["entities"]) == ids(wedding, feast, hangover)
    assert undone["time_changed"] is True
    assert api.get(hangover["id"]).json()["ext"]["start_t"] == "110"

    wedding = api.get(wedding["id"]).json()
    api.patch(wedding, name="The Wedding")
    renamed = affected(undo(api, last_change(api)))
    assert (renamed["entities"], renamed["time_changed"]) == ([wedding["id"]], False)


def test_changes_are_per_request(api: LinkApi, chain: dict[str, dict[str, Any]]) -> None:
    api.patch(chain["wedding"], ext={"start": at(200)})
    later = affected(api.patch(chain["duel"], name="The Duel"))
    assert (later["entities"], later["time_changed"]) == ([chain["duel"]["id"]], False)


def test_series_rules_and_bounds(api: LinkApi, world: dict[str, Any]) -> None:
    feast = event(api, world, "Feast", start=at(100))
    rule = {"kind": "interval", "every": "1000", "limit": {"kind": "count", "count": "3"}}
    recurring = affected(api.patch(feast, ext={"recurrence": rule}))
    assert (recurring["entities"], recurring["time_changed"]) == ([feast["id"]], True)

    feast = api.get(feast["id"]).json()
    same = affected(api.patch(feast, ext={"recurrence": feast["ext"]["recurrence"]}))
    assert same["time_changed"] is False


# --- module records that belong to an entity ----------------------------------------------------


class NoteBase(DeclarativeBase):
    pass


class Sighting(NoteBase):
    """A module record of an entity (``entity_id``) with a time point."""

    __tablename__ = "sg_sightings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_id: Mapped[str | None] = mapped_column(String)
    dimension_id: Mapped[str] = mapped_column(String)
    start_spec: Mapped[TimePoint | None] = spec_column()
    start_t: Mapped[int | None] = moment_column()
    time_status: Mapped[str | None] = status_column()


SIGHTING = "sg.sighting"
SG = ModuleSpec(
    id="sg",
    name="Sightings",
    description="Records of entities with a time point (tests).",
    models=(Sighting,),
    history_tables=(HistoryTable.of(Sighting),),
    slot_providers=(
        SlotProvider(
            SIGHTING,
            Sighting,
            (SlotDef("start", referenceable=True),),
            entity_column="entity_id",
            dimension_column="dimension_id",
        ),
    ),
)


def test_module_records_report_their_entities(tmp_path: Path) -> None:
    with make_client(tmp_path, modules=(*ENTITY_MODULES, SG)) as client:
        api = LinkApi(client)
        opened = client.app.state.vaults.open(api.vault)  # type: ignore[attr-defined]
        registry = client.app.state.registry  # type: ignore[attr-defined]
        Sighting.metadata.create_all(opened.engine)
        dimension = api.make("dimension", "Aetheria")
        world = {"dimension": dimension, "calendar": api.calendar(dimension["id"])}
        duel = event(api, world, "Duel", start=at(7))
        witness = api.make("gadget", "Witness", dimension_id=dimension["id"])
        seen = parse_time_point(after(duel, 1))
        with opened.write_sessions.begin() as session:
            writer = TimeWriter(VaultContext(opened, session, registry))
            for record_id, owner in (("seen", witness["id"]), ("unowned", None)):
                row = Sighting(
                    id=record_id, entity_id=owner, dimension_id=dimension["id"], start_spec=seen
                )
                session.add(row)
                session.flush()
                writer.set_spec(SIGHTING, record_id, "start", seen)
            writer.propagate()
            assert moved_entities(session, writer.slots) == [witness["id"]]

        moved = affected(api.patch(duel, ext={"start": at(70)}))
        assert set(moved["entities"]) == ids(duel, witness)
        assert moved["time_changed"] is True
