"""Calendar proposal budget (``testing.md`` §4): previewing and applying a calendar edit over 10k
dependent records take < 5 s each. Marked ``perf`` (nightly, or ``pytest -m perf``)."""

import random
import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert

from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity, entity_sort_name
from lore.core.modules.spec import VaultContext
from lore.core.time.check import rebuild_time
from lore.core.time.models import Event
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, new_app
from tests.time.test_proposals import two_months

EVENTS = 10_000
BUDGET_S = 5.0


def populate(app: Any, api: Api, seed: int = 7) -> str:
    """A dimension whose prime holds ``EVENTS`` events dated in a two-month calendar (bulk rows,
    then the time index is rebuilt). Returns the calendar's id."""
    rng = random.Random(seed)
    dimension = api.make("dimension")
    calendar = api.make("calendar", "Reckoning", dimension_id=dimension["id"],
                        ext={"definition": two_months()})  # fmt: skip
    prime = api.get(dimension["id"]).json()["ext"]["prime_timeline_id"]
    opened = app.state.vaults.open(api.vault)
    now = utc_now()
    with opened.write_sessions.begin() as session:
        entities, rows = [], []
        for index in range(EVENTS):
            entity_id = new_id()
            name = f"Event {index}"
            month = rng.choice(["frostfall", "thawing"])
            fields = {"year": str(rng.randrange(1, 10_000)), "month": month,
                      "day": str(rng.randrange(1, 31))}  # fmt: skip
            anchor = {"kind": "calendar", "calendar_id": calendar["id"], "fields": fields}
            start = {"anchor": anchor, "precision": "day", "approximate": False}
            entities.append({
                "id": entity_id, "kind": "event", "dimension_id": dimension["id"],
                "name": name, "sort_name": entity_sort_name(name), "slug": "event",
                "fields": {}, "field_visibility": {}, "visibility": "public",
                "revision": 1, "created_at": now, "updated_at": now,
            })  # fmt: skip
            rows.append({
                "id": new_id(), "entity_id": entity_id, "timeline_id": prime,
                "start_spec": start, "start_t": 0, "end_spec": {"kind": "instant"}, "end_t": 0,
                "time_status": "ok", "importance": 3, "revision": 1,
                "created_at": now, "updated_at": now,
            })  # fmt: skip
        session.execute(insert(Entity), entities)
        session.execute(insert(Event), rows)
        rebuild_time(VaultContext(opened, session, app.state.registry))
    calendar_id: str = calendar["id"]
    return calendar_id


@pytest.mark.perf
def test_calendar_proposal_over_10k_dependents(tmp_path: Path) -> None:
    app = new_app(tmp_path)
    with local_client(app, headers=HEADERS) as client:
        api = Api(client)
        calendar_id = populate(app, api)
        url = f"{api.base}/calendars/{calendar_id}/proposals"
        started = time.perf_counter()
        response = client.post(url, json={"definition": two_months(frost=30)})
        preview = time.perf_counter() - started
        assert response.status_code == 201, response.json()
        proposal = response.json()
        assert proposal["summary"]["changed"] > EVENTS  # starts and their instant ends
        started = time.perf_counter()
        applied = client.post(f"{url}/{proposal['id']}/apply", json={"strategies": {}})
        apply_s = time.perf_counter() - started
        assert applied.status_code == 200, applied.json()
        print(f"\npreview {preview:.2f} s, apply {apply_s:.2f} s")
        assert preview < BUDGET_S, f"preview took {preview:.2f} s"
        assert apply_s < BUDGET_S, f"apply took {apply_s:.2f} s"
