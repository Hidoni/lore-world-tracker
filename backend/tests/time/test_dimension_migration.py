"""The v0.1.0 backfill of ``dimensions`` and ``timelines`` (migration ``39828513f6da``)."""

import json

from tests.migration_harness import MigrationHarness

BEFORE = "557b1fb3271d"
T0 = "2026-10-04T00:00:00.000000+00:00"


def _entity(
    migrations: MigrationHarness,
    entity_id: str,
    kind: str,
    *,
    dimension: str | None = None,
    created: str = T0,
    visibility: str = "public",
    deleted: str | None = None,
) -> None:
    migrations.execute(
        "INSERT INTO entities (id, kind, dimension_id, name, slug, sort_name, visibility, "
        "created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, 'x', ?, ?, ?, ?, ?)",
        (entity_id, kind, dimension, entity_id, entity_id, visibility, created, created, deleted),
    )


def test_backfill(migrations: MigrationHarness) -> None:
    migrations.upgrade(BEFORE)
    later = "2026-10-04T01:00:00.000000+00:00"
    # "world": a trashed timeline first, then the one that becomes the prime, then a branch
    _entity(migrations, "world", "dimension", visibility="spoiler")
    _entity(migrations, "old", "timeline", dimension="world", deleted=T0)
    _entity(migrations, "main", "timeline", dimension="world", visibility="private")
    _entity(migrations, "what-if", "timeline", dimension="world", created=later)
    # "void": trashed, and without any timeline
    _entity(migrations, "void", "dimension", visibility="private", deleted=T0)
    migrations.upgrade()

    assert migrations.rows("SELECT entity_id, base_unit, duration FROM dimensions") == [
        (dimension, json.dumps({"singular": "second", "plural": "seconds", "abbr": "s"}),
         "0101" + "1" + "0" * 100)
        for dimension in ("void", "world")
    ]  # fmt: skip
    timelines = migrations.rows(
        "SELECT t.entity_id, t.dimension_id, t.parent_timeline_id, t.is_prime, "
        "t.branch_point_spec, t.branch_t, e.name, e.visibility, e.deleted_at IS NOT NULL "
        "FROM timelines t JOIN entities e ON e.id = t.entity_id ORDER BY t.dimension_id, e.name"
    )
    zero = json.dumps(
        {"anchor": {"kind": "absolute", "t": "0"}, "precision": "base", "approximate": False}
    )
    new_prime = timelines[0][0]
    assert timelines == [
        (new_prime, "void", None, 1, None, None, "Prime", "private", 1),
        ("main", "world", None, 1, None, None, "main", "spoiler", 0),
        ("old", "world", "main", 0, zero, "00010", "old", "public", 1),
        ("what-if", "world", "main", 0, zero, "00010", "what-if", "public", 0),
    ]
    assert migrations.rows(
        "SELECT doc_id, kind, visibility, deleted, name FROM search_docs ORDER BY name"
    ) == [(new_prime, "timeline", "private", 1, "Prime")]
