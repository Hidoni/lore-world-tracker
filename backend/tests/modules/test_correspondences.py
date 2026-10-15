"""The correspondences module (``docs/modules/correspondences.md``, ``time-model.md`` §12):
creating correspondences between dimensions, their sync points (validation after resolution,
anchors that move them, the hard order rule), mapping moments (interpolation, extrapolation,
composition along paths) and the inconsistent-paths warning."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete

from lore.core.modules.spec import VaultContext
from lore.core.time.check import verify_time
from lore.core.time.models import Correspondence, CorrespondencePoint
from lore.core.vaults.manager import VaultManager
from tests.entity_api import LinkApi, invalid, make_client, problem
from tests.entity_modules import with_real_modules
from tests.modules.test_branches import at, start_of


@pytest.fixture
def api(tmp_path: Path) -> Iterator[LinkApi]:
    with make_client(tmp_path, with_real_modules()) as client:
        yield LinkApi(client)


class Worlds:
    """Aetheria, the Dreamrealm and the Underworld, each with a calendar."""

    def __init__(self, api: LinkApi) -> None:
        self.api = api
        self.aetheria = self.dimension("Aetheria")
        self.dream = self.dimension("Dreamrealm")
        self.under = self.dimension("Underworld")

    def dimension(self, name: str) -> str:
        made = self.api.make("dimension", name)
        self.api.calendar(made["id"])
        dimension_id: str = made["id"]
        return dimension_id

    @property
    def base(self) -> str:
        return f"{self.api.base}/m/correspondences"

    def create(self, a: str, b: str, points: list[tuple[Any, Any]], **body: Any) -> Any:
        return self.api.client.post(self.base, json={
            "dimension_a_id": a, "dimension_b_id": b, "name": body.pop("name", "Portal"),
            "points": [{"a": pa if isinstance(pa, dict) else at(pa),
                        "b": pb if isinstance(pb, dict) else at(pb)} for pa, pb in points],
            **body})  # fmt: skip

    def made(self, *args: Any, **body: Any) -> dict[str, Any]:
        response = self.create(*args, **body)
        assert response.status_code == 201, response.json()
        found: dict[str, Any] = response.json()["correspondence"]
        return found

    def map(self, source: str, target: str, t: int) -> dict[str, Any]:
        response = self.api.client.get(f"{self.base}/map", params={
            "from_dimension": source, "to_dimension": target, "t": str(t)})  # fmt: skip
        assert response.status_code == 200, response.json()
        found: dict[str, Any] = response.json()
        return found

    def findings(self, rule: str) -> list[dict[str, Any]]:
        response = self.api.client.get(f"{self.api.base}/consistency/findings",
                                       params={"rule": rule})  # fmt: skip
        items: list[dict[str, Any]] = response.json()["items"]
        return items


@pytest.fixture
def worlds(api: LinkApi) -> Worlds:
    return Worlds(api)


def test_interpolates_between_sync_points(api: LinkApi, worlds: Worlds) -> None:
    portal = worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    assert [(p["a_t"], p["b_t"]) for p in portal["points"]] == [("100", "1000"), ("200", "3000")]
    found = worlds.map(worlds.aetheria, worlds.dream, 150)
    assert (found["result_t"], found["defined"], found["path"]) == ("2000", True, [portal["id"]])
    # Floors: one Aetherian unit is twenty Dreamrealm units, so 2010 maps back to 150.
    assert worlds.map(worlds.dream, worlds.aetheria, 2010)["result_t"] == "150"
    # Without extrapolation the mapping stops at the sync points.
    outside = worlds.map(worlds.aetheria, worlds.dream, 50)
    assert (outside["result_t"], outside["defined"]) == (None, False)
    # The same dimension maps to itself; unconnected dimensions don't map.
    assert worlds.map(worlds.aetheria, worlds.aetheria, 7)["result_t"] == "7"
    assert worlds.map(worlds.aetheria, worlds.under, 150) == {
        "from_dimension": worlds.aetheria, "to_dimension": worlds.under, "t": "150",
        "result_t": None, "defined": False, "path": []}  # fmt: skip
    batch = api.client.post(f"{worlds.base}/map-batch", json={
        "from_dimension": worlds.aetheria, "to_dimension": worlds.dream,
        "t": ["100", "150", "250"]}).json()  # fmt: skip
    assert [(i["t"], i["result_t"]) for i in batch["items"]] == [
        ("100", "1000"), ("150", "2000"), ("250", None)]  # fmt: skip
    listed = api.client.get(worlds.base, params={"dimension": worlds.dream}).json()["items"]
    assert [c["id"] for c in listed] == [portal["id"]]
    assert api.client.get(worlds.base, params={"dimension": worlds.under}).json()["items"] == []


def test_extrapolates_with_rates(api: LinkApi, worlds: Worlds) -> None:
    # One Aetherian unit is 365 Dreamrealm units after the portal opened (time-model.md §13).
    rate = {"num": "365", "den": "1"}
    worlds.made(worlds.aetheria, worlds.dream, [(100, 0)], extrapolation="rate",
                rate_before=rate, rate_after=rate)  # fmt: skip
    assert worlds.map(worlds.aetheria, worlds.dream, 110)["result_t"] == "3650"
    assert worlds.map(worlds.dream, worlds.aetheria, 3650)["result_t"] == "110"
    # Before the portal the Dreamrealm didn't exist yet: below its 0.
    assert worlds.map(worlds.aetheria, worlds.dream, 99)["defined"] is False
    # Rates must be positive, and a single point needs both.
    refused = worlds.create(worlds.aetheria, worlds.dream, [(100, 0)], extrapolation="rate",
                            rate_after=rate)  # fmt: skip
    assert invalid(refused) == ["rate_before"]
    zero = {"num": "0", "den": "1"}
    refused = worlds.create(worlds.aetheria, worlds.dream, [(100, 0), (200, 10)],
                            extrapolation="rate", rate_after=zero)  # fmt: skip
    assert invalid(refused) == ["rate_after"]


def test_sync_points_move_forward_together(api: LinkApi, worlds: Worlds) -> None:
    refused = worlds.create(worlds.aetheria, worlds.dream, [(100, 1000), (200, 500)])
    errors = problem(refused, 422, "validation_error")["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [("points.1", "non_monotonic")]
    assert invalid(worlds.create(worlds.aetheria, worlds.aetheria, [(1, 1)])) == ["dimension_b_id"]
    # A sync point anchored to an event moves with it, and may not break the order.
    portal_event = api.make("event", "Portal opens", dimension_id=worlds.aetheria,
                            ext={"start": at(100)})  # fmt: skip
    portal = worlds.made(worlds.aetheria, worlds.dream,
                         [(start_of(portal_event), 1000), (300, 3000)])  # fmt: skip
    moved = api.patch(api.get(portal_event["id"]).json(), ext={"start": at(150)})
    assert moved.status_code == 200, moved.json()
    current = api.client.get(f"{worlds.base}/{portal['id']}").json()
    assert current["points"][0]["a_t"] == "150"
    assert worlds.map(worlds.aetheria, worlds.dream, 150)["result_t"] == "1000"
    broken = api.patch(api.get(portal_event["id"]).json(), ext={"start": at(400)})
    body = problem(broken, 422, "consistency_error")
    assert "core.correspondence.non_monotonic" in str(body)
    # An anchor in the other dimension doesn't resolve there.
    elsewhere = worlds.create(worlds.aetheria, worlds.dream, [(100, start_of(portal_event))])
    assert invalid(elsewhere)[0].startswith("points.0")


def test_edits_replace_the_sync_points(api: LinkApi, worlds: Worlds) -> None:
    portal = worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    url = f"{worlds.base}/{portal['id']}"
    changed = api.client.patch(url, json={"revision": portal["revision"], "name": "Gate",
                                          "points": [{"a": at(100), "b": at(2000)},
                                                     {"a": at(200), "b": at(2500)}]})  # fmt: skip
    assert changed.status_code == 200, changed.json()
    assert changed.json()["correspondence"]["name"] == "Gate"
    assert worlds.map(worlds.aetheria, worlds.dream, 150)["result_t"] == "2250"
    stale = api.client.patch(url, json={"revision": portal["revision"], "name": "Old"})
    problem(stale, 409, "revision_conflict")
    assert api.client.delete(url).status_code == 200
    assert worlds.map(worlds.aetheria, worlds.dream, 150)["defined"] is False
    assert api.client.get(url).status_code == 404


def test_composes_along_the_shortest_path(api: LinkApi, worlds: Worlds) -> None:
    first = worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 2000)])
    second = worlds.made(worlds.under, worlds.dream, [(10, 1000), (20, 3000)])
    found = worlds.map(worlds.aetheria, worlds.under, 150)
    # 150 → 1500 in the Dreamrealm → 12 in the Underworld (1500 is a quarter of 1000..3000).
    assert (found["result_t"], found["path"]) == ("12", [first["id"], second["id"]])
    assert worlds.findings("correspondences.inconsistent_paths") == []
    # A direct correspondence becomes the shortest path; it disagrees with the chain.
    direct = worlds.made(worlds.aetheria, worlds.under, [(100, 10), (200, 40)], name="Rift")
    assert worlds.map(worlds.aetheria, worlds.under, 150)["path"] == [direct["id"]]
    found_rules = worlds.findings("correspondences.inconsistent_paths")
    assert found_rules, "the disagreeing paths are reported"
    assert {s["id"] for s in found_rules[0]["subjects"]} >= {worlds.aetheria, worlds.under}
    assert found_rules[0]["severity"] == "warning"
    # Agreeing (up to rounding) is fine.
    fixed = api.client.patch(f"{worlds.base}/{direct['id']}", json={
        "revision": direct["revision"],
        "points": [{"a": at(100), "b": at(10)}, {"a": at(200), "b": at(15)}]})  # fmt: skip
    assert fixed.status_code == 200, fixed.json()
    assert worlds.findings("correspondences.inconsistent_paths") == []


def test_undo_and_redo(api: LinkApi, worlds: Worlds) -> None:
    worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    latest = api.client.get(f"{api.base}/changes", params={"limit": 1}).json()["items"][0]
    undone = api.client.post(f"{api.base}/changes/{latest['id']}/revert", json={})
    assert undone.status_code == 200, undone.json()
    assert api.client.get(worlds.base).json()["items"] == []
    assert worlds.map(worlds.aetheria, worlds.dream, 150)["defined"] is False
    redo = undone.json()["changeset"]["id"]
    redone = api.client.post(f"{api.base}/changes/{redo}/revert", json={})
    assert redone.status_code == 200, redone.json()
    assert worlds.map(worlds.aetheria, worlds.dream, 150)["result_t"] == "2000"


# --- anchors across dimensions (#327, time-model.md §5.2) ----------------------------------------


def test_anchors_to_another_dimension_map_through_correspondences(
    api: LinkApi, worlds: Worlds
) -> None:
    portal_opens = api.make("event", "Portal opens", dimension_id=worlds.aetheria,
                            ext={"start": at(150)})  # fmt: skip
    # Without a correspondence the anchor is refused (no raw moment across dimensions).
    refused = api.create("event", "Arrival", dimension_id=worlds.dream,
                         ext={"start": start_of(portal_opens)})  # fmt: skip
    errors = problem(refused, 422, "invalid_date")["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [("ext.start.anchor.ref", "unmapped")]
    portal = worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    arrival = api.make("event", "Arrival", dimension_id=worlds.dream,
                       ext={"start": start_of(portal_opens, 5)})  # fmt: skip
    assert arrival["ext"]["start_t"] == str(2000 + 5)
    # It moves with the event it is anchored to…
    moved = api.patch(api.get(portal_opens["id"]).json(), ext={"start": at(160)})
    assert moved.status_code == 200, moved.json()
    assert api.get(arrival["id"]).json()["ext"]["start_t"] == str(2200 + 5)
    # …and with the correspondence.
    changed = api.client.patch(f"{worlds.base}/{portal['id']}", json={
        "revision": portal["revision"],
        "points": [{"a": at(100), "b": at(1000)}, {"a": at(200), "b": at(2000)}]})  # fmt: skip
    assert changed.status_code == 200, changed.json()
    assert api.get(arrival["id"]).json()["ext"]["start_t"] == str(1600 + 5)
    # Deleting the only correspondence would leave it unmapped: refused.
    current = changed.json()["correspondence"]
    gone = api.client.delete(f"{worlds.base}/{current['id']}")
    assert gone.status_code == 422, gone.json()
    assert "unmapped" in str(gone.json())
    # Through other dimensions too (the shortest path).
    under_feast = api.make("event", "Feast", dimension_id=worlds.under,
                           ext={"start": at(15)})  # fmt: skip
    worlds.made(worlds.under, worlds.aetheria, [(10, 100), (20, 200)])
    echo = api.make("event", "Echo", dimension_id=worlds.dream,
                    ext={"start": start_of(under_feast)})  # fmt: skip
    assert echo["ext"]["start_t"] == "1500"


def test_a_cycle_through_sync_points_is_refused(api: LinkApi, worlds: Worlds) -> None:
    opening = api.make("event", "Opening", dimension_id=worlds.aetheria, ext={"start": at(150)})
    worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    echo = api.make("event", "Echo", dimension_id=worlds.dream,
                    ext={"start": start_of(opening)})  # fmt: skip
    # A sync point anchored to the echo, which is mapped through the correspondences.
    cycle = worlds.create(worlds.aetheria, worlds.dream, [(50, start_of(echo))], name="Loop")
    problem(cycle, 409, "time_cycle")


def test_vault_check_reports_unmapped_anchors(api: LinkApi, worlds: Worlds) -> None:
    """A vault from before correspondences mapped anchors: an anchor across dimensions whose
    correspondence is gone (simulated by removing it under the services) is reported."""
    opening = api.make("event", "Opening", dimension_id=worlds.aetheria, ext={"start": at(150)})
    portal = worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    api.make("event", "Echo", dimension_id=worlds.dream, ext={"start": start_of(opening)})
    manager: VaultManager = api.client.app.state.vaults  # type: ignore[attr-defined]
    opened = manager.open(api.vault)
    registry = api.client.app.state.registry  # type: ignore[attr-defined]

    def problems() -> list[str]:
        with opened.sessions() as session:
            return [p.message for p in verify_time(VaultContext(opened, session, registry))]

    assert problems() == []
    with opened.write_sessions.begin() as session:
        session.execute(delete(CorrespondencePoint))
        session.execute(delete(Correspondence).where(Correspondence.id == portal["id"]))
    [found] = problems()
    assert "doesn't resolve (unmapped)" in found


def test_effect_before_cause_across_dimensions(api: LinkApi, worlds: Worlds) -> None:
    """A cause in Aetheria and its effect in the Dreamrealm compare once mapped (#123)."""
    rule = "core.event.effect_before_cause"
    spell = api.make("event", "The Spell", dimension_id=worlds.aetheria, ext={"start": at(150)})
    dream = api.make("event", "The Dream", dimension_id=worlds.dream, ext={"start": at(1500)})
    api.made_link("core.causes", spell, dream)
    # Without a correspondence the pair isn't checked.
    assert worlds.findings(rule) == []
    # Aetheria 150 is Dreamrealm 2000: the dream (1500) comes first. The rule is rechecked on a
    # rescan (a correspondence isn't one of its triggers) or when either event changes.
    worlds.made(worlds.aetheria, worlds.dream, [(100, 1000), (200, 3000)])
    moved = api.patch(api.get(dream["id"]).json(), ext={"start": at(1999)})
    assert moved.status_code == 200, moved.json()
    [finding] = worlds.findings(rule)
    assert [s["id"] for s in finding["subjects"]] == [dream["id"], spell["id"]]
    assert finding["certainty"] == "definite"
    later = api.patch(api.get(dream["id"]).json(), ext={"start": at(2000)})
    assert later.status_code == 200, later.json()
    assert worlds.findings(rule) == []
