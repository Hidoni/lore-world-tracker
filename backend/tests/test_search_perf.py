"""Search performance budgets (``testing.md`` §4) over 100k entities: ``/search`` and
``/search/quick`` < 100 ms (p95), and < 300 ms for terms in most of the documents (#362: ranking
scores every match). Each word of ``WORDS`` is in about 80% of the bodies here; ``RARE`` is in 1%.
Marked ``perf`` (nightly, or ``pytest -m perf``)."""

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
from lore.core.modules import VaultContext
from lore.core.search.indexer import SearchIndexer
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api, new_app

ENTITIES = 100_000
BUDGET_MS = 100.0
BROAD_BUDGET_MS = 300.0
RARE, RARE_SHARE = "lantern", 0.01
RUNS = 20
SYLLABLES = [
    "ar",
    "bel",
    "cor",
    "dan",
    "el",
    "fen",
    "gor",
    "hal",
    "ith",
    "kar",
    "lor",
    "mor",
    "nar",
    "or",
    "quel",
    "ros",
    "sil",
    "thal",
    "ur",
    "val",
    "wyn",
    "zar",
]
WORDS = [
    "river",
    "tower",
    "storm",
    "king",
    "shadow",
    "forest",
    "blade",
    "harbor",
    "ember",
    "frost",
    "crown",
    "stone",
    "wolf",
    "song",
    "ash",
    "gate",
    "vale",
    "light",
    "iron",
    "sea",
]


def _name(rng: random.Random) -> str:
    return "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 4))).title()


def _text(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS + SYLLABLES) for _ in range(words))


def _p95_ms(call: Callable[[], Any]) -> float:
    call()  # warm up
    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        call()
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return timings[int(len(timings) * 0.95) - 1]


@pytest.mark.perf
def test_search_over_100k_entities(tmp_path: Path) -> None:
    rng = random.Random(42)
    app = new_app(tmp_path)
    with local_client(app, headers=HEADERS) as client:
        api = Api(client)
        opened = app.state.vaults.open(api.vault)
        now = utc_now()
        # Synthetic data: bulk rows (services would take minutes), then a real reindex.
        with opened.write_sessions.begin() as session:
            for start in range(0, ENTITIES, 5000):
                rows = []
                for _ in range(min(5000, ENTITIES - start)):
                    name = _name(rng)
                    text = _text(rng, 60)
                    if rng.random() < RARE_SHARE:
                        text = f"{text} {RARE}"
                    body = {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": text}],
                            }
                        ],
                    }
                    rows.append(
                        {
                            "id": new_id(),
                            "kind": "misc",
                            "name": name,
                            "sort_name": entity_sort_name(name),
                            "slug": name.lower(),
                            "summary": _text(rng, 12),
                            "body": body,
                            "body_schema_version": 1,
                            "fields": {},
                            "field_visibility": {},
                            "visibility": "public",
                            "revision": 1,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                session.execute(insert(Entity), rows)
            started = time.perf_counter()
            count = SearchIndexer(VaultContext(opened, session, app.state.registry)).reindex()
            reindex_s = time.perf_counter() - started
        assert count == ENTITIES

        def get(path: str, **params: Any) -> Callable[[], Any]:
            def call() -> Any:
                response = client.get(f"{api.base}{path}", params=params)
                assert response.status_code == 200
                return response.json()

            return call

        broad, rare = BROAD_BUDGET_MS, BUDGET_MS
        cases = {
            "rare word": (get("/search", q=RARE), rare),
            "rare word + common word": (get("/search", q=f"{RARE} river"), rare),
            "common word": (get("/search", q="river"), broad),
            "two words": (get("/search", q="storm king"), broad),
            "short prefix": (get("/search", q="ar"), broad),
            "phrase": (get("/search", q='"shadow forest"'), broad),
            "or + exclusion": (get("/search", q="(wolf OR frost) -sea"), broad),
            "page 3": (get("/search", q="ember", cursor="eyJvZmZzZXQiOiAxMDB9"), broad),
            "quick prefix": (get("/search/quick", q="kar"), rare),
            "quick substring": (get("/search/quick", q="hall"), rare),
        }
        results = {label: (_p95_ms(call), limit) for label, (call, limit) in cases.items()}
        report = ", ".join(f"{label}: {ms:.1f} ms" for label, (ms, _) in results.items())
        print(f"\nreindex {ENTITIES}: {reindex_s:.1f} s; p95 {report}")
        slow = {label: ms for label, (ms, limit) in results.items() if ms > limit}
        assert not slow, f"over budget: {slow}"
