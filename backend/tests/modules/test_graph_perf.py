"""The graph's budget (``docs/modules/graph.md``, R-NFR-1): 10k nodes and 50k edges in under a
second, for the author and for readers. Marked ``perf`` (nightly, or ``pytest -m perf``)."""

import json
import random
import time
from pathlib import Path

import pytest
from sqlalchemy import insert

from lore.app import create_app
from lore.config import Settings
from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity, entity_sort_name
from lore.core.links.models import Link
from lore.core.modules.spec import VaultContext
from lore.core.visibility import AUTHOR, READER
from lore.modules.graph.service import GraphReader, Query
from tests.conftest import local_client
from tests.entity_api import HEADERS, Api
from tests.entity_modules import with_real_modules

NODES, EDGES = 10_000, 50_000
BUDGET_S = 1.0


@pytest.mark.perf
def test_graph_of_10k_nodes_and_50k_edges(tmp_path: Path) -> None:
    rng = random.Random(7)
    app = create_app(Settings(data_dir=tmp_path), modules=with_real_modules())
    with local_client(app, headers=HEADERS) as client:
        api = Api(client)
        dimension = api.make("dimension")
        opened = app.state.vaults.open(api.vault)
        now = utc_now()
        ids = [new_id() for _ in range(NODES)]
        # Bulk rows: services would take minutes, and nothing derives from these.
        with opened.write_sessions.begin() as session:
            session.execute(insert(Entity), [
                {"id": entity_id, "kind": "misc", "dimension_id": dimension["id"],
                 "name": f"Node {index}", "sort_name": entity_sort_name(f"Node {index}"),
                 "slug": "node", "fields": {}, "field_visibility": {}, "visibility": "public",
                 "revision": 1, "created_at": now, "updated_at": now}
                for index, entity_id in enumerate(ids)
            ])  # fmt: skip
            links = []
            for _ in range(EDGES):
                source, target = rng.sample(ids, 2)
                links.append({"id": new_id(), "link_type": "core.related", "source_id": source,
                              "target_id": target, "data": {}, "visibility": "public",
                              "revision": 1, "created_at": now, "updated_at": now})  # fmt: skip
            for start in range(0, EDGES, 10_000):
                session.execute(insert(Link), links[start : start + 10_000])
        url = f"{api.base}/m/graph/graph"
        whole = {"dimension": dimension["id"], "limit": 20_000}
        response = client.get(url, params=whole)  # and warms the vault's caches
        assert response.status_code == 200, response.json()
        assert len(response.json()["edges"]) == EDGES
        # The server's work (the graph and its JSON), without the test client's transfer.
        registry = app.state.vaults.module_registry
        for policy in (AUTHOR, READER):
            with opened.sessions() as session:
                reader = GraphReader(VaultContext(opened, session, registry), policy)
                started = time.perf_counter()
                body = json.dumps(reader.graph(Query(dimension=dimension["id"], limit=20_000)))
                elapsed = time.perf_counter() - started
            print(f"\ngraph ({'reader' if policy.reader else 'author'}): {elapsed:.2f} s, "
                  f"{len(body) // 1000} kB")  # fmt: skip
            assert elapsed < BUDGET_S, f"the graph took {elapsed:.2f} s"
