"""Full consistency scan budget (``testing.md`` §4, ``consistency.md`` §3.3): < 10 s over 100k
events (every rule enabled, the off-by-default duplicates rule too), and the incremental check's
cost per write, which must not grow with the vault (#235). Marked ``perf`` (nightly, or
``pytest -m perf``)."""

import time
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, LinkApi, new_app
from tests.time.test_window_perf import populate

BUDGET_S = 10.0


@pytest.mark.perf
def test_full_scan_over_100k_events(tmp_path: Path) -> None:
    app = new_app(tmp_path)
    with local_client(app, headers=HEADERS) as client:
        api = Api(client)
        populate(app, api)
        rule = "core.event.duplicate_name_same_time"
        assert client.patch(f"{api.base}/consistency/rules/{rule}",
                            json={"severity": "warning"}).status_code == 200  # fmt: skip
        started = time.perf_counter()
        response = client.post(f"{api.base}/consistency/scan")
        elapsed = time.perf_counter() - started
        assert response.status_code == 200, response.json()
        print(f"\nfull scan: {elapsed:.2f} s, {response.json()}")
        assert elapsed < BUDGET_S, f"the scan took {elapsed:.2f} s"


WRITES = 40


def _write_costs(api: LinkApi, label: str) -> tuple[float, float]:
    """Seconds per event and per link written through the API: sub-events of an era, dated
    relative to each other, then causal and plain links between them."""
    dimension = api.make("dimension", f"Realm {label}")
    api.calendar(dimension["id"])

    def event(name: str, start: Any, **body: Any) -> dict[str, Any]:
        return api.make("event", name, dimension_id=dimension["id"], ext={"start": start}, **body)

    era = event(f"Era {label}", {"anchor": {"kind": "absolute", "t": "1000"}, "precision": "base"})
    started = time.perf_counter()
    events = [era]
    for index in range(WRITES):
        previous = events[-1]
        start = {"anchor": {"kind": "relative",
                            "ref": {"type": "event", "id": previous["id"], "slot": "start"},
                            "offset": {"kind": "base", "units": "10"}},
                 "precision": "base"}  # fmt: skip
        events.append(event(f"Event {label} {index}", start, parent_id=era["id"]))
    per_event = (time.perf_counter() - started) / WRITES
    started = time.perf_counter()
    for index in range(WRITES):
        api.made_link("core.causes", events[index], events[index + 1])
        api.made_link("core.related", events[index + 1], events[0])
    per_link = (time.perf_counter() - started) / (2 * WRITES)
    return per_event, per_link


@pytest.mark.perf
def test_writes_cost_the_same_in_a_large_vault(tmp_path: Path) -> None:
    """Every write runs the incremental check: an event or a link must cost about the same to
    write next to 100k events as in an empty vault (allowing for noise and deeper indexes)."""
    app = new_app(tmp_path)
    with local_client(app, headers=HEADERS) as client:
        api = LinkApi(client)
        rule = "core.event.duplicate_name_same_time"
        assert client.patch(f"{api.base}/consistency/rules/{rule}",
                            json={"severity": "warning"}).status_code == 200  # fmt: skip
        _write_costs(api, "warm-up")
        empty = _write_costs(api, "empty")
        populate(app, api)
        full = _write_costs(api, "full")
        print(
            f"\nper write, empty vault -> 100k events: event {empty[0] * 1000:.1f} -> "
            f"{full[0] * 1000:.1f} ms, link {empty[1] * 1000:.1f} -> {full[1] * 1000:.1f} ms"
        )
        assert full[0] < 2 * empty[0] + 0.005, "an event costs more to write in a large vault"
        assert full[1] < 2 * empty[1] + 0.005, "a link costs more to write in a large vault"
