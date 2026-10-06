"""``TimelineView`` (``time-model.md`` §4.2-§4.6, ADR-0008): lineage and cut-offs, visibility of
time-bound records, override resolution, windows, branch-only entities and the query plan.

The timeline trees are inserted directly: branches are only created through services from M9 on.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import ForeignKey, Index, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased, mapped_column

from lore.core.db.base import Base
from lore.core.db.types import SortableBigInt
from lore.core.entities.models import Entity
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.time.models import Timeline
from lore.core.time.timeline_view import (
    LineageEntry,
    TimeBound,
    TimelineView,
    register_time_bound,
    time_bound,
)


class TvBase(DeclarativeBase):
    pass


class Happening(TvBase):
    """Like ``events``: a start and an end, both required."""

    __tablename__ = "tv_happenings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timeline_id: Mapped[str] = mapped_column(String)
    overrides_id: Mapped[str | None] = mapped_column(ForeignKey("tv_happenings.id"))
    start_t: Mapped[int] = mapped_column(SortableBigInt)
    end_t: Mapped[int] = mapped_column(SortableBigInt)

    __table_args__ = (Index("ix_tv_happenings_timeline_id_start_t", "timeline_id", "start_t"),)


class Marker(TvBase):
    """A record without an end column: an instant at its start."""

    __tablename__ = "tv_markers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timeline_id: Mapped[str] = mapped_column(String)
    overrides_id: Mapped[str | None] = mapped_column(String)
    at_t: Mapped[int] = mapped_column(SortableBigInt)


register_time_bound(TimeBound(Happening, start="start_t", end="end_t"))
register_time_bound(TimeBound(Marker, start="at_t"))

# prime P ── A (b=100) ── B (b=50: before A's own branch point)
#         │            └─ C (b=150: after it)
#         ├─ M (b=0: a branch migrated from v0.1.0, inherits nothing)
#         └─ U (branch point never resolved: inherits nothing)
TREE: dict[str, tuple[str | None, int | None]] = {
    "P": (None, None),
    "A": ("P", 100),
    "B": ("A", 50),
    "C": ("A", 150),
    "M": ("P", 0),
    "U": ("P", None),
}

# id: (timeline, overrides, start, end)
HAPPENINGS: dict[str, tuple[str, str | None, int, int]] = {
    "p0": ("P", None, 0, 5),  # at inception: not even in M (0 < 0 is false)
    "p1": ("P", None, 10, 20),
    "p2": ("P", None, 100, 200),  # starts exactly at A's branch moment: not inherited
    "p3": ("P", None, 60, 300),  # spans A's branch point
    "p4": ("P", None, 49, 49),  # an instant before every branch point but M's
    "a1": ("A", None, 120, 130),
    "a1o": ("C", "a1", 120, 125),  # C overrides A's record
    "p3a": ("A", "p3", 60, 100),  # A ends p3 at its branch moment
    "p3c": ("C", "p3", 60, 110),  # C overrides p3 again (root id, not p3a)
    "c1": ("C", None, 160, 170),
    "b1": ("B", None, 10, 12),  # created in B before its branch point (shared past modified)
}


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Entity.__table__, Timeline.__table__, Link.__table__])  # type: ignore[list-item]
    TvBase.metadata.create_all(engine)
    with Session(engine) as session:
        for name, (parent, branch_t) in TREE.items():
            session.add(Entity(id=name, kind="timeline", dimension_id="dim", name=name, slug=name))
            session.flush()
            session.add(
                Timeline(
                    entity_id=name,
                    dimension_id="dim",
                    parent_timeline_id=parent,
                    is_prime=parent is None,
                    branch_t=branch_t,
                )
            )
            session.flush()
        for key, (timeline, overrides, start, end) in HAPPENINGS.items():
            session.add(
                Happening(
                    id=key, timeline_id=timeline, overrides_id=overrides, start_t=start, end_t=end
                )
            )
            session.flush()
        yield session
    engine.dispose()


def view(session: Session, timeline: str) -> TimelineView:
    return TimelineView.for_timeline(session, timeline)


def ids(session: Session, statement: object) -> set[str]:
    return {row.id for row in session.scalars(statement)}  # type: ignore[call-overload]


# --- lineage -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timeline", "expected"),
    [
        ("P", [("P", None)]),
        ("A", [("A", None), ("P", 100)]),
        ("B", [("B", None), ("A", 50), ("P", 50)]),
        ("C", [("C", None), ("A", 150), ("P", 100)]),
        ("M", [("M", None), ("P", 0)]),
        ("U", [("U", None), ("P", 0)]),
    ],
)
def test_lineage_and_cutoffs(
    session: Session, timeline: str, expected: list[tuple[str, int | None]]
) -> None:
    assert view(session, timeline).lineage == tuple(
        LineageEntry(t, cutoff, depth) for depth, (t, cutoff) in enumerate(expected)
    )


def test_unknown_timeline(session: Session) -> None:
    with pytest.raises(NotFoundError):
        view(session, "nope")


def test_a_missing_parent_is_reported(session: Session) -> None:
    session.get_one(Timeline, "A").parent_timeline_id = "gone"
    session.flush()
    with pytest.raises(RuntimeError, match="missing parent"):
        view(session, "B")
    with pytest.raises(ValueError, match="at least"):
        TimelineView([])


def test_a_cycle_in_the_tree_is_reported(session: Session) -> None:
    session.get_one(Timeline, "P").parent_timeline_id = "B"
    session.flush()
    with pytest.raises(RuntimeError, match="cycle"):
        view(session, "B")


# --- visibility and overrides ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timeline", "expected"),
    [
        ("P", {"p0", "p1", "p2", "p3", "p4"}),
        ("A", {"p0", "p1", "p3a", "p4", "a1"}),
        ("B", {"p0", "p1", "p4", "b1"}),  # p3 starts at 60, after B's cut-off of 50
        ("C", {"p0", "p1", "p3c", "p4", "a1o", "c1"}),
        ("M", set()),
        ("U", set()),
    ],
)
def test_visible_rows_after_override_resolution(
    session: Session, timeline: str, expected: set[str]
) -> None:
    assert ids(session, view(session, timeline).select(Happening)) == expected


def test_a_filtered_override_falls_back_to_the_next_ancestor(session: Session) -> None:
    v = view(session, "C")
    statement = v.select(Happening, where=lambda h: [h.id != "p3c"])
    assert ids(session, statement) == {"p0", "p1", "p3a", "p4", "a1o", "c1"}
    # Conditions on the returned statement apply after resolution: nothing falls back.
    assert ids(session, v.select(Happening).where(Happening.id != "p3c")) == (
        {"p0", "p1", "p4", "a1o", "c1"}
    )


def test_the_statement_selects_full_rows(session: Session) -> None:
    rows = session.scalars(view(session, "A").select(Happening).order_by(Happening.start_t)).all()
    assert [(r.id, r.start_t, r.end_t) for r in rows][:3] == [
        ("p0", 0, 5),
        ("p1", 10, 20),
        ("p4", 49, 49),
    ]


def test_null_start_validity_rows_are_always_inherited(session: Session) -> None:
    def link(
        key: str, timeline: str, overrides: str | None, start: int | None, end: int | None
    ) -> Link:
        return Link(
            id=key,
            link_type="core.related",
            source_id="P",
            target_id="A",
            timeline_id=timeline,
            overrides_id=overrides,
            valid_from_t=start,
            valid_to_t=end,
        )

    session.add_all([link("l_open", "P", None, None, None), link("l_late", "P", None, 100, None)])
    session.flush()
    session.add_all(
        [link("l_open_a", "A", "l_open", None, 100), link("l_open_b", "B", "l_open", None, 90)]
    )
    session.flush()
    assert ids(session, view(session, "P").select(Link)) == {"l_open", "l_late"}
    assert ids(session, view(session, "M").select(Link)) == {"l_open"}
    assert ids(session, view(session, "A").select(Link)) == {"l_open_a"}
    assert ids(session, view(session, "B").select(Link)) == {"l_open_b"}
    assert ids(session, view(session, "C").select(Link)) == {"l_open_a"}

    # Null bounds are unbounded in windows too.
    v = view(session, "P")
    assert ids(session, v.select(Link).where(v.covering(Link, 0))) == {"l_open"}
    assert ids(session, v.select(Link, window=(10**50, 10**50 + 1))) == {"l_open", "l_late"}
    a = view(session, "A")
    assert ids(session, a.select(Link).where(a.covering(Link, 100))) == set()


# --- windows -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        ((0, 1000), {"p0", "p1", "p2", "p3", "p4"}),
        ((5, 10), set()),  # half-open on both sides: p0 ends at 5, p1 starts at 10
        ((5, 11), {"p1"}),
        ((49, 50), {"p4"}),  # the instant at 49 is inside
        ((48, 49), set()),  # the instant at 49 is not
        ((49, 49), {"p4"}),  # instant window: covering 49
        ((60, 60), {"p3"}),
        ((200, 200), {"p3"}),  # p2 ends at 200
        ((300, 400), set()),
    ],
)
def test_overlaps(session: Session, window: tuple[int, int], expected: set[str]) -> None:
    v = view(session, "P")
    assert ids(session, v.select(Happening).where(v.overlaps(Happening, *window))) == expected
    assert ids(session, v.select(Happening, window=window)) == expected


def test_covering(session: Session) -> None:
    v = view(session, "P")
    assert ids(session, v.select(Happening).where(v.covering(Happening, 10))) == {"p1"}
    assert ids(session, v.select(Happening).where(v.covering(Happening, 20))) == set()
    assert ids(session, v.select(Happening).where(v.covering(Happening, 49))) == {"p4"}


def test_windows_apply_to_the_winning_row(session: Session) -> None:
    # p3 (60-300) is overridden in A by p3a (60-100): after 100 it is gone in A, even though the
    # root row overlaps the window. The start bound applied before resolution can't change that.
    a = view(session, "A")
    assert ids(session, a.select(Happening, window=(150, 160))) == set()
    assert ids(session, a.select(Happening, window=(90, 101))) == {"p3a"}
    c = view(session, "C")
    assert ids(session, c.select(Happening, window=(105, 106))) == {"p3c"}


def test_windows_take_aliases(session: Session) -> None:
    v = view(session, "P")
    h = aliased(Happening)
    statement = select(h.id).where(h.timeline_id == "P", v.covering(h, 10))
    assert set(session.scalars(statement)) == {"p1"}


def test_instants_without_an_end_column(session: Session) -> None:
    session.add_all(
        [
            Marker(id="m1", timeline_id="P", at_t=10),
            Marker(id="m2", timeline_id="P", at_t=100),
        ]
    )
    session.flush()
    v = view(session, "P")
    assert ids(session, v.select(Marker, window=(10, 11))) == {"m1"}
    assert ids(session, v.select(Marker, window=(9, 10))) == set()
    assert ids(session, v.select(Marker).where(v.covering(Marker, 100))) == {"m2"}
    assert ids(session, view(session, "A").select(Marker)) == {"m1"}


def test_bad_windows_and_unregistered_tables(session: Session) -> None:
    v = view(session, "P")
    with pytest.raises(ValueError, match="ends before"):
        v.overlaps(Happening, 5, 4)
    with pytest.raises(ValueError, match="not a registered"):
        v.select(Entity)
    with pytest.raises(ValueError, match="already registered"):
        register_time_bound(TimeBound(Happening, start="end_t"))
    assert time_bound(Link).open_start


# --- entities ----------------------------------------------------------------------------------


def test_branch_only_entities(session: Session) -> None:
    for name, origin in [("everywhere", None), ("only_a", "A"), ("only_c", "C")]:
        session.add(
            Entity(id=name, kind="character", name=name, slug=name, origin_timeline_id=origin)
        )
    session.flush()

    def visible(timeline: str) -> set[str]:
        v = view(session, timeline)
        statement = select(Entity.id).where(Entity.kind == "character", *v.entities(Entity))
        return set(session.scalars(statement))

    assert visible("P") == {"everywhere"}
    assert visible("A") == {"everywhere", "only_a"}
    assert visible("B") == {"everywhere", "only_a"}
    assert visible("C") == {"everywhere", "only_a", "only_c"}
    assert visible("M") == {"everywhere"}
    assert view(session, "C").shows_entity("A")
    assert not view(session, "A").shows_entity("C")
    assert view(session, "P").shows_entity(None)


# --- query plan --------------------------------------------------------------------------------


def test_window_queries_use_the_timeline_start_index(session: Session) -> None:
    executed: list[tuple[str, Any]] = []

    def capture(_conn: Any, _cursor: Any, sql: str, params: Any, *_args: Any) -> None:
        executed.append((sql, params))

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert ids(session, view(session, "C").select(Happening, window=(100, 200))) == {
            "p3c",
            "a1o",
            "c1",
        }
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    sql, params = executed[-1]
    plan = " | ".join(
        row[3] for row in session.connection().exec_driver_sql(f"EXPLAIN QUERY PLAN {sql}", params)
    )
    assert "ix_tv_happenings_timeline_id_start_t (timeline_id=? AND start_t<?)" in plan, plan
