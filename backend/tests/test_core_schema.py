import random
import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, create_engine, delete, func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from lore.chronology.numbers import from_sortable_key, sortable_key
from lore.core.db import create_vault_engine
from lore.core.db.base import not_trashed
from lore.core.db.types import SortableBigInt, UTCDateTime
from lore.core.entities.models import Entity, EntityAlias, EntityTag, Tag
from lore.core.links.models import CustomLinkType, Link
from lore.core.richtext.models import Mention
from lore.core.types import MomentStr
from tests.migration_harness import FIRST_REVISION, MigrationHarness

HUGE = 10**1000 - 1  # the largest moment (1000 digits)


@pytest.fixture
def engine(migrations: MigrationHarness) -> Iterator[Engine]:
    migrations.upgrade()
    engine = create_vault_engine(migrations.path)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def make_entity(session: Session, name: str = "Aetheria", **values: object) -> Entity:
    values.setdefault("kind", "misc")
    entity = Entity(name=name, slug=name.lower(), **values)
    session.add(entity)
    session.flush()
    return entity


def make_link(session: Session, source: Entity, target: Entity, **values: object) -> Link:
    link = Link(link_type="core.related", source_id=source.id, target_id=target.id, **values)
    session.add(link)
    session.flush()
    return link


# --- SortableBigInt -------------------------------------------------------------------------


def test_sortable_big_int_encodes_parameters_and_results() -> None:
    column_type = SortableBigInt()
    dialect = create_engine("sqlite://").dialect
    assert column_type.process_bind_param(0, dialect) == "00010"
    assert column_type.process_bind_param(1023, dialect) == "00041023"
    assert column_type.process_bind_param(None, dialect) is None
    assert column_type.process_result_value("00041023", dialect) == 1023
    assert column_type.process_literal_param(7, dialect) == "'00017'"
    for bad, error in [(-1, ValueError), (10**1000, ValueError), (True, TypeError),
                       (1.0, TypeError), ("7", TypeError)]:  # fmt: skip
        with pytest.raises(error):
            column_type.process_bind_param(bad, dialect)


def test_moments_round_trip_as_sortable_text(session: Session) -> None:
    source, target = make_entity(session, "A"), make_entity(session, "B")
    link = make_link(session, source, target, valid_from_t=HUGE, valid_to_t=0)
    session.commit()
    session.expire_all()
    assert session.get(Link, link.id).valid_from_t == HUGE  # type: ignore[union-attr]
    stored = session.execute(text("SELECT valid_from_t, valid_to_t FROM links")).one()
    assert stored == (sortable_key(HUGE), "00010")
    assert stored[0].startswith("1000")


def test_negative_moments_are_rejected(session: Session) -> None:
    source, target = make_entity(session, "A"), make_entity(session, "B")
    with pytest.raises(StatementError, match="sortable key"):
        make_link(session, source, target, valid_from_t=-1)


def random_moments(rng: random.Random, count: int) -> list[int]:
    moments = {0, 1, 9, 10, 99, 100, HUGE, HUGE - 1, 10**999}
    while len(moments) < count:
        digits = rng.choice([1, 2, 3, 5, 18, 19, 20, 40, 300, 999, 1000])
        moments.add(rng.randrange(10 ** (digits - 1) if digits > 1 else 0, 10**digits))
    return list(moments)


def test_order_by_and_comparisons_are_numeric(session: Session) -> None:
    rng = random.Random(32)
    moments = random_moments(rng, 200)
    a, b = make_entity(session, "A"), make_entity(session, "B")
    timeline = make_entity(session, "Prime", kind="timeline")
    for moment in moments:
        make_link(session, a, b, timeline_id=timeline.id, valid_from_t=moment)
    session.commit()
    ordered = session.scalars(select(Link.valid_from_t).order_by(Link.valid_from_t)).all()
    assert ordered == sorted(moments)
    descending = session.scalars(select(Link.valid_from_t).order_by(Link.valid_from_t.desc()))
    assert list(descending) == sorted(moments, reverse=True)
    for threshold in [*rng.sample(moments, 20), 0, HUGE, 5, 10**500]:
        below = select(Link.valid_from_t).where(Link.valid_from_t < threshold)
        assert sorted(moment for moment in session.scalars(below) if moment is not None) == sorted(
            m for m in moments if m < threshold
        )
        at_least = select(Link.valid_from_t).where(Link.valid_from_t >= threshold)
        assert sorted(m for m in session.scalars(at_least) if m is not None) == sorted(
            m for m in moments if m >= threshold
        )
    assert session.scalar(select(func.max(Link.valid_from_t))) == HUGE
    between = select(func.count()).where(Link.valid_from_t.between(10, 10**20))
    assert session.scalar(between) == sum(10 <= m <= 10**20 for m in moments)


@given(
    st.lists(st.integers(0, 10**60) | st.integers(0, HUGE), min_size=2, max_size=20),
    st.integers(0, 10**60) | st.integers(0, HUGE),
)
def test_sql_comparisons_match_python(moments: list[int], threshold: int) -> None:
    """Text comparison of the keys in SQLite (BINARY collation) is numeric comparison."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE t (k TEXT)")
        connection.executemany("INSERT INTO t VALUES (?)", [(sortable_key(m),) for m in moments])
        ordered = connection.execute("SELECT k FROM t ORDER BY k").fetchall()
        assert [from_sortable_key(key) for (key,) in ordered] == sorted(moments)
        below = connection.execute(
            "SELECT k FROM t WHERE k < ? ORDER BY k", (sortable_key(threshold),)
        ).fetchall()
        assert [from_sortable_key(key) for (key,) in below] == sorted(
            m for m in moments if m < threshold
        )
    finally:
        connection.close()


def test_time_range_queries_use_the_index(session: Session) -> None:
    plan = session.execute(
        text(
            "EXPLAIN QUERY PLAN SELECT id FROM links "
            "WHERE timeline_id = :timeline AND valid_from_t < :cutoff ORDER BY valid_from_t"
        ),
        {"timeline": "t", "cutoff": sortable_key(10**30)},
    ).all()
    details = " ".join(row[-1] for row in plan)
    assert "USING INDEX ix_links_timeline_id_valid_from_t (timeline_id=? AND valid_from_t<?)" in (
        details
    )
    assert "TEMP B-TREE" not in details  # ordered by the index, no sort step
    # the same through the ORM: SortableBigInt encodes the bound moment
    orm_sql = select(Link.id).where(Link.timeline_id == "t", Link.valid_from_t < 10**30)
    compiled = orm_sql.compile(session.get_bind(), compile_kwargs={"literal_binds": True})
    assert f"'{sortable_key(10**30)}'" in str(compiled)
    orm_plan = session.execute(text(f"EXPLAIN QUERY PLAN {compiled}")).all()
    assert "ix_links_timeline_id_valid_from_t" in " ".join(row[-1] for row in orm_plan)


# --- ids, timestamps, revisions -------------------------------------------------------------


def test_ids_are_lowercase_uuid7(session: Session) -> None:
    entities = [make_entity(session, f"E{i}") for i in range(5)]
    for entity in entities:
        parsed = uuid.UUID(entity.id)
        assert parsed.version == 7
        assert entity.id == str(parsed)  # lowercase, hyphenated
    ids = [entity.id for entity in entities]
    assert ids == sorted(ids)  # time-ordered
    alias = EntityAlias(entity_id=entities[0].id, alias="The First")
    tag = Tag(name="Ancient")
    session.add_all([alias, tag])
    session.flush()
    assert uuid.UUID(alias.id).version == 7
    assert uuid.UUID(tag.id).version == 7


def test_timestamps_are_aware_utc(session: Session) -> None:
    before = datetime.now(UTC)
    entity = make_entity(session)
    session.commit()
    session.expire_all()
    assert entity.created_at.tzinfo is not None
    assert entity.created_at.utcoffset() == timedelta(0)
    assert before <= entity.created_at <= datetime.now(UTC)
    raw = session.scalar(text("SELECT created_at FROM entities"))
    assert raw.endswith("+00:00")
    assert len(raw) == len("2026-10-03T18:00:00.000000+00:00")
    entity.deleted_at = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=2)))
    session.commit()
    assert session.scalar(text("SELECT deleted_at FROM entities")) == (
        "2026-01-01T10:00:00.000000+00:00"
    )
    entity.deleted_at = datetime(2026, 1, 1)
    with pytest.raises(StatementError, match="timezone-aware"):
        session.flush()
    session.rollback()
    with pytest.raises(TypeError):
        UTCDateTime().process_bind_param("2026-01-01", session.bind.dialect)  # type: ignore[union-attr]


def test_revision_and_updated_at_change_on_update(session: Session, engine: Engine) -> None:
    entity = make_entity(session)
    session.commit()
    assert entity.revision == 1
    created, updated = entity.created_at, entity.updated_at
    entity.name = "Renamed"
    session.commit()
    assert entity.revision == 2
    assert entity.created_at == created
    assert entity.updated_at > updated
    # a concurrent update makes the stale writer fail instead of overwriting
    with Session(engine) as other:
        other.get(Entity, entity.id).summary = "theirs"  # type: ignore[union-attr]
        other.commit()
    entity.summary = "mine"
    with pytest.raises(StaleDataError):
        session.commit()


# --- constraints ----------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["entities", "entity_aliases", "links"])
def test_visibility_check(session: Session, table: str) -> None:
    a, b = make_entity(session, "A"), make_entity(session, "B")
    alias = EntityAlias(entity_id=a.id, alias="x")
    session.add(alias)
    link = make_link(session, a, b)
    session.commit()
    row_id = {"entities": a.id, "entity_aliases": alias.id, "links": link.id}[table]
    for allowed in ("public", "spoiler", "private"):
        session.execute(text(f"UPDATE {table} SET visibility = :v WHERE id = :id"),
                        {"v": allowed, "id": row_id})  # fmt: skip
    with pytest.raises(IntegrityError, match=r"ck_\w+_visibility"):
        session.execute(text(f"UPDATE {table} SET visibility = 'secret' WHERE id = :id"),
                        {"id": row_id})  # fmt: skip


def test_defaults_apply_to_raw_inserts(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO entities (id, kind, name, sort_name, slug, created_at, updated_at) "
            "VALUES ('e', 'misc', 'Raw', 'raw', 'raw', '2026-01-01T00:00:00.000000+00:00', "
            "'2026-01-01T00:00:00.000000+00:00')"
        )
    )
    raw = session.get(Entity, "e")
    assert raw is not None
    assert (raw.visibility, raw.summary, raw.fields, raw.field_visibility, raw.revision) == (
        "public",
        "",
        {},
        {},
        1,
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Dragons", "dragons"),
        ("Élan", "élan"),
        ("Ærø", "ÆRØ"),
        ("Ἀθῆναι", "ἀθῆναι"),  # Greek
        ("Москва", "МОСКВА"),  # noqa: RUF001
        ("Straße", "STRASSE"),  # case folding, not just lowercasing
        ("\u00c9lan", "E\u0301lan"),  # precomposed vs. combining accent (NFC)
    ],
)
def test_tag_names_are_unique_ignoring_case(session: Session, first: str, second: str) -> None:
    session.add(Tag(name=first))
    session.flush()
    session.add(Tag(name=second))
    with pytest.raises(IntegrityError, match="UNIQUE"):
        session.flush()


def test_tag_name_key_follows_renames(session: Session) -> None:
    tag = Tag(name="Élan")
    session.add(tag)
    session.flush()
    assert tag.name_key == "élan"
    tag.name = "Dragons"
    session.flush()
    assert tag.name_key == "dragons"
    session.add(Tag(name="Élan"))  # the old name is free again
    session.flush()


def test_authored_rows_restrict_deletes(session: Session) -> None:
    a, b = make_entity(session, "A"), make_entity(session, "B")
    child = make_entity(session, "Child", parent_id=a.id)
    session.add_all([EntityAlias(entity_id=b.id, alias="Bee")])
    tag = Tag(name="t")
    session.add(tag)
    session.flush()
    session.add(EntityTag(entity_id=child.id, tag_id=tag.id))
    session.commit()
    for entity_id in (a.id, b.id, child.id):
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.execute(delete(Entity).where(Entity.id == entity_id))
        session.rollback()


def test_mentions_are_derived_and_cascade(session: Session) -> None:
    a, b = make_entity(session, "A"), make_entity(session, "B")
    session.add(Mention(source_entity_id=a.id, target_entity_id=b.id, count_public=2))
    session.commit()
    session.execute(delete(Entity).where(Entity.id == b.id))
    session.commit()
    assert session.scalar(select(func.count()).select_from(Mention)) == 0


def test_link_overrides_and_type_defs(session: Session) -> None:
    a, b = make_entity(session, "A"), make_entity(session, "B")
    root = make_link(session, a, b, data={"rank": "Captain"})
    override = make_link(session, a, b, overrides_id=root.id, role="admiral")
    definition = CustomLinkType(key="custom.sworn_enemy", label="sworn enemy of", symmetric=True)
    session.add(definition)
    session.commit()
    assert override.overrides_id == root.id
    assert root.data == {"rank": "Captain"}
    assert (definition.source_kinds, definition.temporal, definition.revision) == (
        "*",
        "optional",
        1,
    )
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        session.execute(delete(Link).where(Link.id == root.id))


def test_not_trashed(session: Session) -> None:
    kept = make_entity(session, "Kept")
    make_entity(session, "Trashed", deleted_at=datetime.now(UTC))
    names = session.scalars(select(Entity.name).where(not_trashed(Entity))).all()
    assert names == [kept.name]


# --- migration ------------------------------------------------------------------------------


def test_core_schema_migration_downgrades(migrations: MigrationHarness) -> None:
    from alembic import command  # noqa: PLC0415

    migrations.upgrade()
    assert {"entities", "entity_aliases", "tags", "entity_tags", "links", "link_type_defs",
            "mentions"} <= migrations.tables()  # fmt: skip
    engine = create_vault_engine(migrations.path)
    try:
        with engine.connect() as connection, connection.begin():
            command.downgrade(migrations.migrator.config(connection), FIRST_REVISION)
    finally:
        engine.dispose()
    assert migrations.tables() == {"alembic_version", "vault_meta"}


# --- MomentStr ------------------------------------------------------------------------------


class Window(BaseModel):
    start: MomentStr


def test_moment_str() -> None:
    assert Window.model_validate({"start": "0"}).start == 0
    assert Window.model_validate({"start": str(HUGE)}).start == HUGE
    assert Window(start=5).model_dump(mode="json") == {"start": "5"}
    assert Window(start=5).model_dump() == {"start": 5}
    for bad in ["-1", "01", "+1", " 1", "1.0", str(10**1000), -1, 10**1000, True, 1.5]:
        with pytest.raises(ValidationError):
            Window.model_validate({"start": bad})
    schema = Window.model_json_schema()["properties"]["start"]
    assert schema["type"] == "string"
    assert schema["pattern"] == "^(0|[1-9][0-9]*)$"
    assert schema["maxLength"] == 1000
