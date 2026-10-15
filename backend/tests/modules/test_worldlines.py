"""The worldlines module (``docs/modules/worldlines.md``, ``time-model.md`` §11): replacing
segments (validation after resolution, anchors that move them), exact subjective time across
rates, presence (twice at once), the implicit worldline from existence and the personal timeline.
"""

from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from tests.entity_api import LinkApi, invalid, make_client
from tests.entity_modules import with_real_modules
from tests.modules.test_branches import at, start_of

DAY = 86_400
YEAR = 365 * DAY


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


def subjective(value: dict[str, str] | None) -> Fraction | int | None:
    return None if value is None else Fraction(int(value["num"]), int(value["den"]))


class World:
    """Aetheria (a calendar of 365-day years) and its prime timeline; Vey, a traveler."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.aetheria = api.make("dimension", "Aetheria")
        api.calendar(self.aetheria["id"])
        self.prime: str = self.aetheria["ext"]["prime_timeline_id"]
        self.vey = self.character("Vey")

    def character(self, name: str, **body: Any) -> dict[str, Any]:
        body.setdefault("dimension_id", self.aetheria["id"])
        return self.api.make("character", name, **body)

    def event(self, name: str, t: int) -> dict[str, Any]:
        return self.api.make("event", name, dimension_id=self.aetheria["id"],
                             ext={"start": at(t)})  # fmt: skip

    def url(self, entity: dict[str, Any], path: str) -> str:
        return f"{self.api.base}/m/worldlines/entities/{entity['id']}/{path}"

    def segment(self, start: Any, end: Any, **body: Any) -> dict[str, Any]:
        return {
            "dimension_id": body.pop("dimension_id", self.aetheria["id"]),
            "timeline_id": body.pop("timeline_id", self.prime),
            "start": start if isinstance(start, dict) else at(start),
            "end": end if isinstance(end, dict) else at(end),
            **body,
        }

    def put(self, entity: dict[str, Any], segments: list[dict[str, Any]]) -> Any:
        return self.api.client.put(self.url(entity, "segments"), json={"segments": segments})

    def replaced(self, entity: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.put(entity, segments)
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()["worldline"]
        return found

    def get(self, entity: dict[str, Any], path: str = "segments", **params: Any) -> Any:
        response = self.api.client.get(self.url(entity, path), params=params)
        assert response.status_code == 200, response.json()
        return response.json()

    def present(self, entity: dict[str, Any], t: int, **params: Any) -> list[str | None]:
        params.setdefault("dimension", self.aetheria["id"])
        found = self.get(entity, "presence", t=str(t), **params)
        return [s["id"] for s in found["segments"]]

    def exists(self, entity: dict[str, Any], **body: Any) -> None:
        response = self.api.client.post(
            f"{self.api.base}/entities/{entity['id']}/facts",
            json={"field_key": "core.exists", "timeline_id": self.prime, **body},
        )
        assert response.status_code == 201, response.json()


@pytest.fixture
def world(api: LinkApi) -> World:
    return World(api)


def test_subjective_time_across_rates(world: World) -> None:
    """Vey lives years 10-30, jumps back to year 5 for a year at double rate, then lives years
    40-41 at half rate: 20 + 2 + ½ years of their own time."""
    half = {"num": "1", "den": "2"}
    worldline = world.replaced(world.vey, [
        world.segment(10 * YEAR, 30 * YEAR),
        world.segment(5 * YEAR, 6 * YEAR, rate={"num": "2", "den": "1"}, note="The Return"),
        world.segment(40 * YEAR, 41 * YEAR, rate=half),
    ])  # fmt: skip
    assert worldline["implicit"] is False
    assert worldline["personal_dimension_id"] == world.aetheria["id"]
    segments = worldline["segments"]
    assert [s["seq"] for s in segments] == [1, 2, 3]
    assert [(subjective(s["subjective_start"]), subjective(s["subjective_end"]))
            for s in segments] == [(0, 20 * YEAR), (20 * YEAR, 22 * YEAR),
                                   (22 * YEAR, 22 * YEAR + YEAR // 2)]  # fmt: skip
    assert segments[2]["rate"] == half
    assert world.get(world.vey) == worldline
    # Experienced events come in Vey's own order, with their ages.
    for name, t in (("War", 15 * YEAR), ("Founding", 5 * YEAR + YEAR // 2),
                    ("Eclipse", 40 * YEAR + 1)):  # fmt: skip
        event = world.event(name, t)
        world.api.made_link("core.participant", event, world.vey, role="witness")
    timeline = world.get(world.vey, "personal-timeline")
    assert timeline["truncated"] is False
    items = [(i["kind"], i["name"], subjective(i["subjective_t"])) for i in timeline["items"]]
    assert items == [
        ("participation", "War", 5 * YEAR),
        ("jump", None, 20 * YEAR),
        ("participation", "Founding", 21 * YEAR),
        ("jump", None, 22 * YEAR),
        ("participation", "Eclipse", 22 * YEAR + Fraction(1, 2)),
    ]
    founding = timeline["items"][2]
    assert founding["age"] == {"t": str(21 * YEAR), "display": "21 Years"}
    assert founding["roles"] == ["witness"]
    assert founding["segment_id"] == segments[1]["id"]
    eclipse = timeline["items"][4]
    assert eclipse["age"]["t"] == str(22 * YEAR)  # floored
    jump = timeline["items"][1]
    assert (jump["t"], jump["to_t"], jump["to_timeline_id"]) == (
        str(30 * YEAR), str(5 * YEAR), world.prime)  # fmt: skip
    only = world.get(world.vey, "personal-timeline", include="jumps")["items"]
    assert [i["kind"] for i in only] == ["jump", "jump"]


def test_validation(world: World) -> None:
    def errors(*segments: dict[str, Any]) -> list[str]:
        return invalid(world.put(world.vey, list(segments)))

    assert errors(world.segment(10, 20), world.segment(30, 40, rate={"num": "0", "den": "1"})) == [
        "segments.1.rate"
    ]
    assert errors(world.segment(20, 10)) == ["segments.0.end"]
    other = world.api.make("dimension", "Dreamrealm")
    world.api.calendar(other["id"])
    assert errors(world.segment(1, 2, dimension_id=other["id"])) == ["segments.0.timeline_id"]
    war = world.event("War", 100)
    assert errors(world.segment(1, start_of(war), dimension_id=other["id"],
                                timeline_id=other["ext"]["prime_timeline_id"])) == [
        "segments.0.end"]  # fmt: skip
    assert errors(world.segment(1, 2, departure_event_id=world.vey["id"])) == [
        "segments.0.departure_event_id"
    ]
    place = world.api.make("location", "Harbor", dimension_id=world.aetheria["id"])
    assert invalid(world.put(place, [world.segment(1, 2)])) == ["segments"]
    # Nothing was written.
    assert world.get(world.vey)["implicit"] is True


def test_present_twice(world: World) -> None:
    """Vey lives years 10-30 and comes back for years 20-25: present twice in between."""
    first, second = world.replaced(world.vey, [
        world.segment(10 * YEAR, 30 * YEAR), world.segment(20 * YEAR, 25 * YEAR),
    ])["segments"]  # fmt: skip
    assert world.present(world.vey, 22 * YEAR) == [first["id"], second["id"]]
    assert world.present(world.vey, 12 * YEAR) == [first["id"]]
    assert world.present(world.vey, 30 * YEAR) == [first["id"]]  # both ends belong to it
    assert world.present(world.vey, 5 * YEAR) == []
    # A participation both visits cover: the first, unless the link picks one.
    meeting = world.event("Meeting", 22 * YEAR)
    world.api.made_link("core.participant", meeting, world.vey)
    [item] = world.get(world.vey, "personal-timeline", include="participations")["items"]
    assert (item["segment_id"], item["segment_ids"]) == (first["id"], [first["id"], second["id"]])
    assert subjective(item["subjective_t"]) == 12 * YEAR
    later = world.event("Farewell", 24 * YEAR)
    world.api.made_link("core.participant", later, world.vey, data={"segment_id": second["id"]})
    items = world.get(world.vey, "personal-timeline", include="participations")["items"]
    farewell = next(i for i in items if i["name"] == "Farewell")
    assert farewell["segment_id"] == second["id"]
    assert subjective(farewell["subjective_t"]) == 20 * YEAR + 4 * YEAR
    # An event no segment covers: absent, no subjective time.
    world.api.made_link("core.participant", world.event("Flood", 50 * YEAR), world.vey)
    flood = world.get(world.vey, "personal-timeline")["items"][-1]
    assert (flood["name"], flood["subjective_t"], flood["segment_ids"]) == ("Flood", None, [])


def test_implicit_worldline_is_the_existence(world: World) -> None:
    # Without existence facts: the whole time of the home dimension.
    [whole] = world.get(world.vey)["segments"]
    assert (whole["id"], whole["start_t"], whole["timeline_id"]) == (None, "0", world.prime)
    assert world.present(world.vey, 5 * YEAR) == [None]
    # With them: the existence periods, merged, in order.
    world.exists(world.vey, valid_from=at(10 * YEAR), valid_to=at(40 * YEAR))
    world.exists(world.vey, valid_from=at(30 * YEAR), valid_to=at(70 * YEAR))
    world.exists(world.vey, valid_from=at(90 * YEAR), valid_to=at(95 * YEAR))
    worldline = world.get(world.vey)
    assert worldline["implicit"] is True
    assert [(s["start_t"], s["end_t"], subjective(s["subjective_start"]))
            for s in worldline["segments"]] == [
        (str(10 * YEAR), str(70 * YEAR), 0), (str(90 * YEAR), str(95 * YEAR), 60 * YEAR)
    ]  # fmt: skip
    # Presence agrees with the existence the entity's state reports.
    for t in (5 * YEAR, 10 * YEAR, 69 * YEAR, 70 * YEAR, 80 * YEAR, 92 * YEAR, 95 * YEAR):
        state = world.api.client.get(f"{world.api.base}/entities/{world.vey['id']}/state",
                                     params={"at": str(t)}).json()  # fmt: skip
        assert (world.present(world.vey, t) != []) == (state["existence"] == "exists"), t
    items = world.get(world.vey, "personal-timeline")["items"]
    assert [(i["kind"], subjective(i["subjective_t"])) for i in items] == [
        ("existence_start", 0), ("existence_end", 60 * YEAR),
        ("existence_start", 60 * YEAR), ("existence_end", 65 * YEAR),
    ]  # fmt: skip
    assert items[1]["age"]["display"] == "60 Years"
    # A multiversal entity without segments has no worldline.
    drifter = world.api.make("character", "Drifter")
    empty = world.get(drifter)
    assert (empty["segments"], empty["personal_dimension_id"]) == ([], None)
    # Explicit segments replace it; an empty list brings it back.
    world.replaced(world.vey, [world.segment(1, 2)])
    assert world.present(world.vey, 20 * YEAR) == []
    assert world.replaced(world.vey, [])["implicit"] is True
    assert world.present(world.vey, 20 * YEAR) == [None]


def test_propagation_moves_anchored_segments(world: World) -> None:
    departure = world.event("Departure", 30 * YEAR)
    first, second = world.replaced(world.vey, [
        world.segment(10 * YEAR, start_of(departure), departure_event_id=departure["id"]),
        world.segment(5 * YEAR, 6 * YEAR),
    ])["segments"]  # fmt: skip
    assert first["end_t"] == str(30 * YEAR)
    assert first["departure_event_id"] == departure["id"]
    moved = world.api.patch(world.api.get(departure["id"]).json(), ext={"start": at(32 * YEAR)})
    assert moved.status_code == 200, moved.json()
    first, second = world.get(world.vey)["segments"]
    assert first["end_t"] == str(32 * YEAR)
    assert subjective(second["subjective_start"]) == 22 * YEAR
    jump = world.get(world.vey, "personal-timeline", include="jumps")["items"][0]
    assert (jump["t"], jump["event_id"]) == (str(32 * YEAR), departure["id"])


def test_undo_and_purge(world: World) -> None:
    world.replaced(world.vey, [world.segment(1, 2)])
    latest = world.api.client.get(f"{world.api.base}/changes", params={"limit": 1}).json()
    undone = world.api.client.post(
        f"{world.api.base}/changes/{latest['items'][0]['id']}/revert", json={}
    )
    assert undone.status_code == 200, undone.json()
    assert world.get(world.vey)["implicit"] is True
    redo = undone.json()["changeset"]["id"]
    assert world.api.client.post(f"{world.api.base}/changes/{redo}/revert", json={}).status_code \
        == 200  # fmt: skip
    assert world.get(world.vey)["segments"][0]["end_t"] == "2"
    assert world.api.delete(world.vey["id"]).status_code == 200
    assert world.api.delete(world.vey["id"], purge=True).status_code == 200


# --- time travel and participations (#121) -------------------------------------------------------


def findings(world: World, rule: str) -> list[dict[str, Any]]:
    response = world.api.client.get(f"{world.api.base}/consistency/findings", params={"rule": rule})
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def travel(world: World, entity: dict[str, Any], **body: Any) -> Any:
    return world.api.client.post(world.url(entity, "time-travel"), json=body)


def test_time_travel_within_the_timeline(world: World) -> None:
    """Vey (no existence facts: all of time) vanishes in year 30 and turns up in year 5."""
    response = travel(world, world.vey,
                      departure={"at": at(30 * YEAR), "event_name": "The Vanishing"},
                      destination={"dimension_id": world.aetheria["id"], "arrival": at(5 * YEAR),
                                   "until": at(40 * YEAR), "event_name": "A stranger arrives"})  # fmt: skip
    assert response.status_code == 200, response.json()
    result = response.json()
    first, second = result["worldline"]["segments"]
    assert (first["start_t"], first["end_t"]) == ("0", str(30 * YEAR))
    assert (second["start_t"], second["end_t"]) == (str(5 * YEAR), str(40 * YEAR))
    assert result["timeline_id"] == world.prime and result["branch_id"] is None
    assert first["departure_event_id"] == result["departure_event_id"]
    assert second["arrival_event_id"] == result["arrival_event_id"]
    # Vey takes part in both events, each with its visit.
    items = world.get(world.vey, "personal-timeline")["items"]
    kinds = [(i["kind"], i["name"], i["assignment"]) for i in items]
    assert kinds == [
        ("participation", "The Vanishing", "chosen"),
        ("jump", None, None),
        ("participation", "A stranger arrives", "chosen"),
    ]
    assert items[2]["segment_id"] == second["id"]
    # The cut follows the departure event.
    vanishing = world.api.get(result["departure_event_id"]).json()
    moved = world.api.patch(vanishing, ext={"start": at(31 * YEAR)})
    assert moved.status_code == 200, moved.json()
    assert world.get(world.vey)["segments"][0]["end_t"] == str(31 * YEAR)
    # A departure outside the worldline is refused (Vey is gone after year 40).
    refused = travel(world, world.vey, departure={"at": at(50 * YEAR)},
                     destination={"dimension_id": world.aetheria["id"], "arrival": at(1)})  # fmt: skip
    assert invalid(refused) == ["departure"]


def test_time_travel_into_a_new_branch(world: World) -> None:
    experiment = world.event("The Experiment", 20 * YEAR)
    world.replaced(world.vey, [world.segment(10 * YEAR, 60 * YEAR),
                               world.segment(70 * YEAR, 80 * YEAR)])  # fmt: skip
    response = travel(world, world.vey, departure={"event_id": experiment["id"]},
                      destination={"dimension_id": world.aetheria["id"], "arrival": at(15 * YEAR),
                                   "new_branch": {"name": "Vey's Return"},
                                   "event_name": "Return"})  # fmt: skip
    assert response.status_code == 200, response.json()
    result = response.json()
    branch = result["branch_id"]
    assert branch is not None and result["timeline_id"] == branch
    segments = result["worldline"]["segments"]
    # Cut at the experiment, the branch visit, then the later segment as before.
    assert [(s["timeline_id"], s["start_t"], s["end_t"]) for s in segments] == [
        (world.prime, str(10 * YEAR), str(20 * YEAR)),
        (branch, str(15 * YEAR), "1000000000000"),
        (world.prime, str(70 * YEAR), str(80 * YEAR)),
    ]
    assert segments[0]["departure_event_id"] == experiment["id"]
    timeline = world.api.get(branch).json()
    assert (timeline["name"], timeline["ext"]["branch_t"]) == ("Vey's Return", str(15 * YEAR))
    # The arrival event exists only in the branch.
    arrival = world.api.get(result["arrival_event_id"]).json()
    assert arrival["origin_timeline_id"] == branch
    # A new branch and a timeline at once are refused; nothing is written.
    refused = travel(world, world.vey, departure={"at": at(75 * YEAR)},
                     destination={"dimension_id": world.aetheria["id"], "arrival": at(1),
                                  "timeline_id": world.prime, "new_branch": {"name": "X"}})  # fmt: skip
    assert invalid(refused) == ["destination.new_branch"]
    assert len(world.get(world.vey)["segments"]) == 3


def test_time_travel_to_another_dimension(world: World) -> None:
    dream = world.api.make("dimension", "Dreamrealm")
    world.api.calendar(dream["id"])
    response = travel(world, world.vey, departure={"at": at(30 * YEAR)},
                      destination={"dimension_id": dream["id"], "arrival": at(100),
                                   "rate": {"num": "2", "den": "1"}})  # fmt: skip
    assert response.status_code == 200, response.json()
    _first, second = response.json()["worldline"]["segments"]
    assert (second["dimension_id"], second["timeline_id"]) == (
        dream["id"], dream["ext"]["prime_timeline_id"])  # fmt: skip
    assert second["rate"] == {"num": "2", "den": "1"}
    assert world.present(world.vey, 100, dimension=dream["id"]) == [second["id"]]
    # An arrival outside the destination's time names the wizard's field.
    refused = travel(world, world.vey, departure={"at": at(10 * YEAR)},
                     destination={"dimension_id": dream["id"], "arrival": at(-5)})  # fmt: skip
    assert refused.status_code == 422


def test_participations_are_assigned_to_visits(world: World) -> None:
    """Vey lives years 10-30 and comes back for 20-25; existence 10-30 (so the core rule would
    see the year-50 flood as outside it)."""
    world.exists(world.vey, valid_from=at(10 * YEAR), valid_to=at(30 * YEAR))
    first, second = world.replaced(world.vey, [
        world.segment(10 * YEAR, 30 * YEAR), world.segment(20 * YEAR, 25 * YEAR),
    ])["segments"]  # fmt: skip
    world.api.made_link("core.participant", world.event("Founding", 12 * YEAR), world.vey)
    meeting = world.event("Meeting", 22 * YEAR)
    link = world.api.made_link("core.participant", meeting, world.vey)
    flood = world.event("Flood", 50 * YEAR)
    world.api.made_link("core.participant", flood, world.vey)
    items = {i["name"]: i for i in world.get(world.vey, "personal-timeline")["items"]}
    assert items["Founding"]["assignment"] == "implied"
    assert items["Meeting"]["assignment"] == "ambiguous"
    assert items["Flood"]["assignment"] == "absent"
    [ambiguous] = findings(world, "worldlines.ambiguous_participation")
    assert {s["id"] for s in ambiguous["subjects"]} == {world.vey["id"], meeting["id"]}
    [absent] = findings(world, "worldlines.absent_participant")
    assert {s["id"] for s in absent["subjects"]} == {world.vey["id"], flood["id"]}
    # The core rule leaves entities with a worldline to these rules.
    assert findings(world, "core.event.participant_not_existing") == []
    # Choosing the second visit settles it; a visit of someone else is refused.
    chosen = world.api.patch_link(link, data={"segment_id": second["id"]})
    assert chosen.status_code == 200, chosen.json()
    assert findings(world, "worldlines.ambiguous_participation") == []
    items = {i["name"]: i for i in world.get(world.vey, "personal-timeline")["items"]}
    assert (items["Meeting"]["assignment"], items["Meeting"]["segment_id"]) == (
        "chosen", second["id"])  # fmt: skip
    other = world.character("Ilsa")
    refused = world.api.link("core.participant", meeting, other,
                             data={"segment_id": first["id"]})  # fmt: skip
    assert invalid(refused) == ["data.segment_id"]
    # A chosen visit that doesn't cover the event makes it absent.
    again = world.api.patch_link(chosen.json()["link"], data={"segment_id": first["id"]})
    assert again.status_code == 200, again.json()
    assert findings(world, "worldlines.ambiguous_participation") == []
    assert len(findings(world, "worldlines.absent_participant")) == 1
    # Back to the implicit worldline: the core rule checks the existence again.
    world.replaced(world.vey, [])
    assert [f["rule_id"] for f in findings(world, "core.event.participant_not_existing")] == [
        "core.event.participant_not_existing"
    ]
