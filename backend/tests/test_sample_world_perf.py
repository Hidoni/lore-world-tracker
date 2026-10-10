"""Backend budgets (``testing.md`` §4) on the ``large`` sample world (about 100k events typed in
every way the time model allows, 500k links; ``tests/sample_world.py`` builds it once and caches
it): timeline windows, a full consistency scan and a calendar proposal over its 10k+ dependents.
The synthetic-data perf tests next to each feature check the same budgets on uniform data.
Marked ``perf`` (``make perf``); the tests share one copy of the world and run in file order
(the proposal is applied last). ``LORE_PERF_SAMPLE_SIZE`` picks another size for a quick try
(the budgets are for ``large``)."""

import copy
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from scripts.make_sample_vault import SIZES, Size

from lore.app import create_app
from lore.config import Settings
from lore.core.time.cache import SERIES, WINDOWS
from tests.conftest import local_client
from tests.entity_api import HEADERS
from tests.sample_world import copy_world
from tests.time.test_window_perf import BUDGET_MS, ZOOMED_OUT_MS, _p95_ms

pytestmark = pytest.mark.perf

SIZE = cast(Size, os.environ.get("LORE_PERF_SAMPLE_SIZE", "large"))
LARGE = SIZE == "large"
SCAN_BUDGET_S = 10.0
PROPOSAL_BUDGET_S = 5.0
# The bulk's events start from t = 3,000,000 on, about 30 days apart.
BULK_END = 3_000_000 + SIZES[SIZE].events * 30 * 86_400


class World:
    def __init__(self, client: TestClient, base: str) -> None:
        self.client = client
        self.base = base

    def get(self, path: str, **params: Any) -> Any:
        response = self.client.get(f"{self.base}{path}", params=params)
        assert response.status_code == 200, response.json()
        return response.json()

    def named(self, kind: str, name: str) -> dict[str, Any]:
        page = self.get("/entities", kind=kind, q=name, limit=50)
        found: dict[str, Any] = next(e for e in page["items"] if e["name"] == name)
        return self.get(f"/entities/{found['id']}")  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    data_dir: Path = tmp_path_factory.mktemp("large") / "data"
    built = copy_world(SIZE, data_dir)
    with local_client(create_app(Settings(data_dir=data_dir)), headers=HEADERS) as client:
        yield World(client, f"/api/v1/vaults/{built.vault_id}")


def test_windows(world: World) -> None:
    aetheria = world.named("dimension", "Aetheria")
    prime, duration = aetheria["ext"]["prime_timeline_id"], int(aetheria["ext"]["duration"])

    def window(start: int, end: int, *, cold: bool, **params: Any) -> Callable[[], Any]:
        query = {"from": str(start), "to": str(end), "px": 1500, **params}

        def call() -> Any:
            if cold:
                WINDOWS.clear()
            return world.get(f"/timelines/{prime}/window", **query)

        return call

    mid = BULK_END // 2
    zoomed_in: dict[str, tuple[int, int, dict[str, Any]]] = {
        "1/10 of the bulk": (mid, mid + BULK_END // 10, {}),
        "1/100 of the bulk": (mid, mid + BULK_END // 100, {}),
        "1/10,000 of the bulk": (mid, mid + BULK_END // 10_000, {}),
        "1/10 as reader": (mid, mid + BULK_END // 10, {"as_reader": "true"}),
    }
    zoomed_out: dict[str, tuple[int, int, dict[str, Any]]] = {
        "the whole bulk": (0, BULK_END, {}),
        "the whole dimension": (0, duration + 1, {}),
        "whole bulk, importance ≥ 4": (0, BULK_END, {"min_importance": 4}),
        "whole bulk, as reader": (0, BULK_END, {"as_reader": "true"}),
    }
    tenth = window(mid, mid + BULK_END // 10, cold=True)()
    assert 0 < tenth["total"] <= 20_000
    whole = window(0, BULK_END, cold=True)()
    assert whole["total"] > (50_000 if LARGE else tenth["total"])
    assert whole["series_bands"] or any(i.get("series_id") for i in whole["items"])

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
    print(f"\nwindow p95 ({tenth['total']} events in 1/10, {whole['total']} in all): {report}")
    # Not a budget: a window's first computation since the app started (or since its series
    # changed) also expands the series it shows; the cold windows above have them cached.
    first = {}
    for label, (a, b, p) in {**zoomed_in, **zoomed_out}.items():
        SERIES.clear()
        started = time.perf_counter()
        window(a, b, cold=True, **p)()
        first[label] = (time.perf_counter() - started) * 1000
    print("first window with no series cached: "
          + ", ".join(f"{label}: {ms:.0f} ms" for label, ms in first.items()))  # fmt: skip
    slow = {label: ms for label, (ms, limit) in results.items() if ms > limit}
    assert not slow, f"over budget: {slow}"


def test_full_consistency_scan(world: World) -> None:
    rule = "core.event.duplicate_name_same_time"
    patched = world.client.patch(
        f"{world.base}/consistency/rules/{rule}", json={"severity": "warning"}
    )
    assert patched.status_code == 200, patched.json()
    started = time.perf_counter()
    response = world.client.post(f"{world.base}/consistency/scan")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.json()
    print(f"\nfull scan: {elapsed:.2f} s, {response.json()}")
    assert elapsed < SCAN_BUDGET_S, f"the scan took {elapsed:.2f} s"


def test_calendar_proposal_over_its_dependents(world: World) -> None:
    """Frostfall gains a day in the Imperial Reckoning (``time-model.md`` §13): everything typed
    in it after Frostfall moves, and what is relative to that."""
    imperial = world.named("calendar", "Imperial Reckoning")
    definition = copy.deepcopy(imperial["ext"]["definition"])
    for template in definition["regimes"][1]["templates"].values():
        for child in template.get("sequence", []):
            if child.get("id") == "frostfall":
                child["template"] = "m31"
    url = f"{world.base}/calendars/{imperial['id']}/proposals"
    started = time.perf_counter()
    response = world.client.post(url, json={"definition": definition})
    preview = time.perf_counter() - started
    assert response.status_code == 201, response.json()
    proposal = response.json()
    assert proposal["summary"]["affected"] > (10_000 if LARGE else 100), proposal["summary"]
    # The author accepts what the shift breaks (ends typed as moments, now before their start).
    accepted = {item["key"]: "keep_date" for item in proposal["items"] if item["problem"]}
    started = time.perf_counter()
    applied = world.client.post(f"{url}/{proposal['id']}/apply", json={"strategies": accepted})
    apply_s = time.perf_counter() - started
    assert applied.status_code == 200, applied.json()
    summary = f"{proposal['summary']}, {len(accepted)} accepted"
    print(f"\nproposal ({summary}): preview {preview:.2f} s, apply {apply_s:.2f} s")
    assert preview < PROPOSAL_BUDGET_S, f"preview took {preview:.2f} s"
    assert apply_s < PROPOSAL_BUDGET_S, f"apply took {apply_s:.2f} s"
