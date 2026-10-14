"""The graph benchmark's world (``docs/modules/graph.md``, ``scripts/graph-bench.sh``): a new
vault with one dimension, ``--nodes`` misc entities and ``--edges`` random ``core.related`` links
between them. Prints the vault id.

    uv run scripts/make_graph_bench_vault.py --out /tmp/bench-data

The vault and dimension are made through the API. The entities and links are bulk rows
written directly, as in ``tests/modules/test_graph_perf.py``: services would take minutes. Nothing
derives from them (no text, no time), but they aren't in history or the search index, so the
vault is only for measuring the graph. Don't use it for anything else.
"""

import argparse
import random
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import insert

from lore.app import create_app
from lore.config import Settings
from lore.core.db.base import new_id
from lore.core.db.types import utc_now
from lore.core.entities.models import Entity, entity_sort_name
from lore.core.links.models import Link

DIMENSION_EXT = {
    "base_unit": {"singular": "second", "plural": "seconds", "abbr": "s"},
    "duration": str(10**12),
}


def generate(data_dir: Path, nodes: int, edges: int, seed: int) -> str:
    rng = random.Random(seed)
    app = create_app(Settings(data_dir=data_dir))
    with TestClient(
        app, base_url="http://localhost", headers={"X-Lore-Client": "cli"}
    ) as client:
        response = client.post("/api/v1/vaults", json={"name": "Graph benchmark"})
        response.raise_for_status()
        vault_id: str = response.json()["id"]
        response = client.post(
            f"/api/v1/vaults/{vault_id}/entities",
            json={"kind": "dimension", "name": "Benchmark", "ext": DIMENSION_EXT},
        )
        response.raise_for_status()
        dimension_id = response.json()["entity"]["id"]
        opened = app.state.vaults.open(vault_id)
        now = utc_now()
        ids = [new_id() for _ in range(nodes)]
        with opened.write_sessions.begin() as session:
            session.execute(insert(Entity), [
                {"id": entity_id, "kind": "misc", "dimension_id": dimension_id,
                 "name": f"Node {index}", "sort_name": entity_sort_name(f"Node {index}"),
                 "slug": "node", "fields": {}, "field_visibility": {}, "visibility": "public",
                 "revision": 1, "created_at": now, "updated_at": now}
                for index, entity_id in enumerate(ids)
            ])  # fmt: skip
            links = []
            for _ in range(edges):
                source, target = rng.sample(ids, 2)
                links.append({"id": new_id(), "link_type": "core.related", "source_id": source,
                              "target_id": target, "data": {}, "visibility": "public",
                              "revision": 1, "created_at": now, "updated_at": now})  # fmt: skip
            for start in range(0, len(links), 10_000):
                session.execute(insert(Link), links[start : start + 10_000])
    return vault_id


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True, help="data directory to add it to")
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--edges", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    print(generate(args.out, args.nodes, args.edges, args.seed))


if __name__ == "__main__":
    main()
