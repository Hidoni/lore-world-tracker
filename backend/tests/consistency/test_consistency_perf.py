"""Full consistency scan budget (``testing.md`` §4, ``consistency.md`` §3.3): < 10 s over 100k
events (every rule enabled, the off-by-default duplicates rule too). Marked ``perf`` (nightly,
or ``pytest -m perf``)."""

import time
from pathlib import Path

import pytest

from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, new_app
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
