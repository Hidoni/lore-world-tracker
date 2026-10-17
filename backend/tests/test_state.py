"""As-of state (``time-model.md`` §10.4-§10.5): existence intervals, unknown existence,
overlapping facts, precision boundaries (``possible``), the present moment, and the existence
filter of lists, the tree and children."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI

from lore.core.modules.spec import VaultContext
from lore.core.time.state import FACT, StateReader, bound_moments, timeline_resolver
from lore.core.visibility import READER
from tests.entity_api import Api, make_client, problem
from tests.test_facts import DAY, World, absolute

YEAR = 365 * DAY


def in_year(calendar: dict[str, Any], year: int) -> dict[str, Any]:
    fields = {"year": str(year)}
    return {"anchor": {"kind": "calendar", "calendar_id": calendar["id"], "fields": fields},
            "precision": "year"}  # fmt: skip


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with make_client(tmp_path) as client:
        yield World(Api(client))


def state(world: World, at: int | str, entity: dict[str, Any] | None = None, **params: Any) -> Any:
    entity = entity or world.gadget
    response = world.api.client.get(
        f"{world.api.base}/entities/{entity['id']}/state", params={"at": str(at), **params}
    )
    assert response.status_code == 200, response.json()
    return response.json()


def existence(world: World, at: int, entity: dict[str, Any] | None = None) -> str:
    found: str = state(world, at, entity)["existence"]
    return found


def test_existence_intervals_and_unknown(world: World) -> None:
    assert existence(world, 0) == "unknown"  # no existence facts: unknown
    built = world.made(field_key="core.exists", valid_from=absolute(10), valid_to=absolute(20))
    rebuilt = world.made(field_key="core.exists", valid_from=absolute(30))
    assert [existence(world, t) for t in (0, 9, 10, 19, 20, 29, 30, 10**9)] == [
        "not_exists", "not_exists", "exists", "exists",
        "not_exists", "not_exists", "exists", "exists",
    ]  # fmt: skip
    found = state(world, 15)
    assert found["existence_fact_ids"] == [built["id"]]
    assert (found["timeline_id"], found["at"]) == (world.timeline, "15")
    assert state(world, 40)["existence_fact_ids"] == [rebuilt["id"]]
    # Deleting every existence fact makes it unknown again.
    for fact in (built, rebuilt):
        assert world.delete(fact).status_code == 200
    assert existence(world, 15) == "unknown"


def test_fields_names_and_overlaps(world: World) -> None:
    gadget = world.api.make("gadget", "Clock", dimension_id=world.dimension["id"],
                            fields={"rank": "1", "titles": ["Old"]})  # fmt: skip
    three = world.made(gadget, field_key="rank", value="3", valid_from=absolute(10),
                       valid_to=absolute(50))  # fmt: skip
    seven = world.made(gadget, field_key="rank", value="7", valid_from=absolute(40))
    world.made(gadget, field_key="titles", value=["Keeper"], valid_from=absolute(10))
    world.made(gadget, field_key="titles", value=["Warden", "Keeper"], valid_from=absolute(20),
               valid_to=absolute(30))  # fmt: skip
    renamed = world.made(gadget, field_key="core.name", value="Great Clock",
                         valid_from=absolute(25))  # fmt: skip

    before = state(world, 5, gadget)
    assert before["fields"]["rank"] == {
        "value": "1", "source": "static", "fact_ids": [], "certainty": "certain",
        "ambiguous": False,
    }  # fmt: skip
    assert before["fields"]["titles"]["value"] == ["Old"]
    assert (before["name"], before["name_fact_id"]) == ("Clock", None)

    middle = state(world, 25, gadget)
    assert (middle["fields"]["rank"]["value"], middle["fields"]["rank"]["fact_ids"]) == (
        "3", [three["id"]]
    )  # fmt: skip
    # A multiple field joins the values of every covering fact (latest start first).
    assert middle["fields"]["titles"]["value"] == ["Warden", "Keeper"]
    assert middle["fields"]["titles"]["ambiguous"] is False
    assert (middle["name"], middle["name_fact_id"]) == ("Great Clock", renamed["id"])

    # Overlap of a single-valued field: the latest start wins, flagged.
    overlap = state(world, 45, gadget)["fields"]["rank"]
    assert (overlap["value"], overlap["ambiguous"]) == ("7", True)
    assert overlap["fact_ids"] == [seven["id"]]
    assert state(world, 50, gadget)["fields"]["rank"]["ambiguous"] is False
    # Fields without facts keep their static value; non-temporal fields aren't listed.
    assert state(world, 45, gadget)["fields"]["era"]["source"] == "static"
    assert "text" not in state(world, 45, gadget)["fields"]


def test_precision_boundaries_are_possible(world: World) -> None:
    """Existence from (some time in) year 2 until (some time in) year 4."""
    cal = world.calendar
    world.made(field_key="core.exists", valid_from=in_year(cal, 2), valid_to=in_year(cal, 4))
    expected = {
        0: "not_exists",
        YEAR - 1: "not_exists",
        YEAR: "possible",  # year 2 has begun: the start may still be ahead
        2 * YEAR - 2: "possible",
        2 * YEAR - 1: "exists",  # the last moment of year 2: started whatever moment it was
        3 * YEAR - 1: "exists",
        3 * YEAR: "possible",  # year 4: the end may have passed
        4 * YEAR - 2: "possible",
        4 * YEAR - 1: "not_exists",
        4 * YEAR: "not_exists",
    }
    assert {t: existence(world, t) for t in expected} == expected
    # Fields of a possible fact are possible too.
    world.made(field_key="rank", value="5", valid_from=in_year(cal, 2))
    assert state(world, YEAR + 1)["fields"]["rank"]["certainty"] == "possible"
    assert state(world, 2 * YEAR)["fields"]["rank"]["certainty"] == "certain"


def test_bound_moments_are_where_as_of_reads_change(world: World) -> None:
    """The static export records as-of reads once per interval between ``bound_moments`` (#374):
    each bound's first moment and last moment, and nothing changes in between."""
    cal = world.calendar
    world.made(field_key="core.exists", valid_from=in_year(cal, 2), valid_to=in_year(cal, 4))
    app = cast(FastAPI, world.api.client.app)
    opened = app.state.vaults.open(world.api.vault)
    with opened.sessions() as session:
        context = VaultContext(opened, session, app.state.registry)
        reader = StateReader(context, READER, world.timeline, 0)
        facts = reader.facts([world.gadget["id"]])[world.gadget["id"]]
        moments = bound_moments(timeline_resolver(context, READER, world.timeline), FACT, facts)
    assert moments == {YEAR, 2 * YEAR - 1, 3 * YEAR, 4 * YEAR - 1}
    edges = sorted({0, *moments})
    for start, end in zip(edges, [*edges[1:], 5 * YEAR], strict=True):
        assert existence(world, start) == existence(world, end - 1), (start, end)


def test_present_and_timelines(world: World) -> None:
    get = world.api.client.get
    url = f"{world.api.base}/entities/{world.gadget['id']}/state"
    body = problem(get(url, params={"at": "present"}), 422, "validation_error")
    assert body["errors"][0]["path"] == "at"
    patched = world.api.patch(world.dimension, ext={"present": absolute(77)})
    assert patched.status_code == 200, patched.json()
    assert state(world, "present")["at"] == "77"
    problem(get(url, params={"at": "-1"}), 422, "validation_error")
    problem(get(url), 422, "validation_error")
    problem(get(url, params={"at": "0", "timeline": world.gadget["id"]}), 404, "not_found")
    other = world.api.make("dimension", "Elsewhere")
    elsewhere = other["ext"]["prime_timeline_id"]
    problem(get(url, params={"at": "0", "timeline": elsewhere}), 422, "validation_error")

    # A multiversal entity needs a timeline; its facts may be in any dimension.
    wanderer = world.api.make("gadget", "Wanderer")
    problem(get(f"{world.api.base}/entities/{wanderer['id']}/state", params={"at": "0"}),
            422, "validation_error")  # fmt: skip
    world.made(wanderer, field_key="core.exists", timeline_id=elsewhere, valid_from=absolute(5))
    assert state(world, 9, wanderer, timeline=elsewhere)["existence"] == "exists"
    assert state(world, 9, wanderer, timeline=world.timeline)["existence"] == "unknown"

    # The entity GET includes the state with `at`, and not without.
    assert world.api.get(world.gadget["id"]).json()["state"] is None
    got = get(f"{world.api.base}/entities/{world.gadget['id']}", params={"at": "present"})
    assert got.json()["state"]["at"] == "77"


def test_lists_tree_and_children_filter_by_existence(world: World) -> None:
    dim = world.dimension["id"]
    make = world.api.make
    parent = make("gadget", "Shelf", dimension_id=dim)
    names = [f"G{i:03}" for i in range(30)]
    gadgets = {n: make("gadget", n, dimension_id=dim, parent_id=parent["id"]) for n in names}
    # Even ones exist from t = 100; odd ones until t = 100; G000 has no existence facts.
    for index, name in enumerate(names[1:], start=1):
        bound = {"valid_from" if index % 2 == 0 else "valid_to": absolute(100)}
        world.made(gadgets[name], field_key="core.exists", **bound)
    world.made(gadgets["G001"], field_key="core.exists", valid_from=in_year(world.calendar, 1),
               valid_to=in_year(world.calendar, 2))  # fmt: skip

    def listed(path: str, **params: Any) -> list[tuple[str, str | None]]:
        items: list[tuple[str, str | None]] = []
        cursor = None
        while True:
            query = {"limit": 4, **params, **({"cursor": cursor} if cursor else {})}
            response = world.api.client.get(f"{world.api.base}{path}", params=query)
            assert response.status_code == 200, response.json()
            page = response.json()
            items += [(i["name"], i["existence"]) for i in page["items"] if i["name"] in names]
            cursor = page["next_cursor"]
            if cursor is None:
                return items

    later = {"timeline": world.timeline, "at": "150"}
    odd_possible = ("G001", "possible")  # inside year 1: its start may still be ahead
    expected_later = [("G000", "unknown"), odd_possible] + [
        (n, "exists") for i, n in enumerate(names) if i and i % 2 == 0
    ]
    assert listed("/entities", kind="gadget", **later) == expected_later
    assert listed(f"/entities/{parent['id']}/children", **later) == expected_later
    assert listed("/tree", parent=parent["id"], **later) == expected_later
    # `at` with a dimension and no timeline: its prime timeline.
    assert listed("/entities", kind="gadget", dimension=dim, at="150") == expected_later
    earlier = listed("/entities", kind="gadget", at="50", dimension=dim)
    assert [n for n, _ in earlier] == ["G000", *(n for i, n in enumerate(names) if i % 2)]
    # Without `at`, everything, with no existence.
    assert {e for _, e in listed("/entities", kind="gadget")} == {None}
    problem(world.api.client.get(f"{world.api.base}/entities", params={"at": "0"}),
            422, "validation_error")  # fmt: skip
