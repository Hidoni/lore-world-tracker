"""Timeline window budgets (``testing.md`` §4, R-NFR-1; decided 2026-10-07) over 100k events at
1,500 px, p95: < 150 ms cold for windows with up to 20k overlapping events, < 500 ms cold for the
whole-dimension zoom-out, < 150 ms for any window already computed (``WINDOWS`` cache). Marked
``perf`` (nightly, or ``pytest -m perf``)."""

import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert

from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity, entity_sort_name
from lore.core.time.cache import WINDOWS
from lore.core.time.models import Event
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, new_app

EVENTS = 100_000
BUDGET_MS = 150.0
ZOOMED_OUT_MS = 500.0
RUNS = 20
D = 10**12
INSTANT = {"kind": "instant"}


def _p95_ms(call: Callable[[], Any]) -> float:
    call()  # warm up
    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        call()
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return timings[int(len(timings) * 0.95) - 1]


def _point(t: int) -> dict[str, Any]:
    return {"anchor": {"kind": "absolute", "t": str(t)}, "precision": "base", "approximate": False}


def populate(app: Any, api: Api, events: int = EVENTS, seed: int = 42) -> str:
    """A dimension (D = 10^12) whose prime timeline holds ``events`` random events: bulk rows
    (services would take minutes; there are no anchors to propagate). Returns the prime's id."""
    rng = random.Random(seed)
    dimension = api.make("dimension")
    api.calendar(dimension["id"])
    prime: str = api.get(dimension["id"]).json()["ext"]["prime_timeline_id"]
    opened = app.state.vaults.open(api.vault)
    now = utc_now()
    with opened.write_sessions.begin() as session:
        for chunk in range(0, events, 5000):
            entities, rows = [], []
            for index in range(chunk, min(chunk + 5000, events)):
                entity_id = new_id()
                name = f"Event {index}"
                start = rng.randrange(D)
                roll = rng.random()
                length = 0 if roll < 0.3 else rng.randrange(D // (10 if roll > 0.99 else 10**5))
                end = min(start + length, D)
                entities.append({
                    "id": entity_id, "kind": "event", "dimension_id": dimension["id"],
                    "name": name, "sort_name": entity_sort_name(name), "slug": "event",
                    "fields": {}, "field_visibility": {}, "visibility": "public",
                    "revision": 1, "created_at": now, "updated_at": now,
                })  # fmt: skip
                rows.append({
                    "id": new_id(), "entity_id": entity_id, "timeline_id": prime,
                    "start_spec": _point(start), "start_t": start,
                    "end_spec": INSTANT if end == start else
                    {"kind": "time_point", "time_point": _point(end)},
                    "end_t": end, "time_status": "ok",
                    "importance": rng.choices([1, 2, 3, 4, 5], [30, 30, 25, 10, 5])[0],
                    "revision": 1, "created_at": now, "updated_at": now,
                })  # fmt: skip
            session.execute(insert(Entity), entities)
            session.execute(insert(Event), rows)
    return prime


@pytest.mark.perf
def test_window_over_100k_events(tmp_path: Path) -> None:
    app = new_app(tmp_path)
    with local_client(app, headers=HEADERS) as client:
        api = Api(client)
        prime = populate(app, api)

        def window(start: int, end: int, *, cold: bool, **params: Any) -> Callable[[], Any]:
            url = f"{api.base}/timelines/{prime}/window"
            query = {"from": str(start), "to": str(end), "px": 1500, **params}

            def call() -> Any:
                if cold:
                    WINDOWS.clear()
                response = client.get(url, params=query)
                assert response.status_code == 200, response.json()
                return response.json()

            return call

        mid = D // 2
        zoomed_in: dict[str, tuple[int, int, dict[str, Any]]] = {
            "1/100": (mid, mid + D // 100, {}),
            "1/10,000": (mid, mid + D // 10_000, {}),
            "1/1,000,000": (mid, mid + D // 1_000_000, {}),
            "1/100 as reader": (mid, mid + D // 100, {"as_reader": "true"}),
        }
        zoomed_out: dict[str, tuple[int, int, dict[str, Any]]] = {
            "whole dimension": (0, D + 1, {}),
            "whole, importance ≥ 4": (0, D + 1, {"min_importance": 4}),
            "whole, as reader": (0, D + 1, {"as_reader": "true"}),
        }
        whole = window(0, D + 1, cold=True)()
        assert len(whole["items"]) == 1500
        assert whole["culled"] == sum(b["starts"] for b in whole["buckets"])
        assert window(mid, mid + D // 100, cold=True)()["total"] <= 20_000

        budgets = [
            *((f"cold {k}", window(a, b, cold=True, **p), BUDGET_MS)
              for k, (a, b, p) in zoomed_in.items()),
            *((f"cold {k}", window(a, b, cold=True, **p), ZOOMED_OUT_MS)
              for k, (a, b, p) in zoomed_out.items()),
            *((f"cached {k}", window(a, b, cold=False, **p), BUDGET_MS)
              for k, (a, b, p) in {**zoomed_in, **zoomed_out}.items()),
        ]  # fmt: skip
        results = {label: (_p95_ms(call), limit) for label, call, limit in budgets}
        report = ", ".join(f"{label}: {ms:.1f} ms" for label, (ms, _) in results.items())
        print(f"\np95 {report}")
        slow = {label: ms for label, (ms, limit) in results.items() if ms > limit}
        assert not slow, f"over budget: {slow}"
