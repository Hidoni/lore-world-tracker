"""Shared recurrence types and the plan contract (``recurrence.md`` §3-§4).

A plan maps each candidate period ``k = 0, 1, …`` to its positions: the time-ordered starts of the
occurrences the period can hold. Position ``j`` of period ``k`` has the key ``k.j`` when the rule
can select several positions per period, else ``k``. A position whose finer fields don't exist
(``missing: skip``) is ``None``: it has no occurrence but still consumes its ``j``.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from lore.chronology.calendar.arithmetic import add, duration_upper_bound
from lore.chronology.calendar.compile import ValidationError
from lore.chronology.calendar.compiled import CompiledCalendar
from lore.chronology.schema import CalendarDuration, DurationEnd, EndSpec

type RecurrenceErrorCode = Literal[
    "not_found", "rule.invalid", "rule.too_complex_to_count", "rule.too_many_positions"
]

SCAN_LIMIT = 100_000
"""Most candidate periods searched for one occurrence (first, last, next) or counted one by one."""
MAX_POSITIONS = 100_000
"""Most positions one period may hold (``rule.too_many_positions`` beyond)."""
TRUNCATE_FACTOR = 4
"""``expand`` gives up on items when the window has more than ``max_items * 4`` candidates."""
ITERATE_LIMIT = 10_000
"""Most periods ``expand`` visits; beyond, it estimates (sparse rules such as Fridays the 13th
over daily periods stay exact within it)."""
SAMPLES = 64
"""Candidates sampled to estimate the occurrences per period (until #21's averages)."""


class RecurrenceError(ValueError):
    """``not_found``, an invalid rule (``errors`` lists why), or a rule too large to evaluate."""

    def __init__(
        self, code: RecurrenceErrorCode, message: str, errors: tuple[ValidationError, ...] = ()
    ) -> None:
        super().__init__(message)
        self.code: RecurrenceErrorCode = code
        self.errors = errors


@dataclass(frozen=True, slots=True)
class RecurrenceContext:
    """What a rule needs besides itself (``recurrence.md`` §4 ``ctx``)."""

    series_start: int
    """The resolved series start."""
    end: EndSpec
    """The series' end spec: the occurrence duration (``duration``, ``instant`` or ``unknown``)."""
    dimension_duration: int
    """``D``: no occurrence starts after it."""
    calendar: CompiledCalendar | None = field(default=None, repr=False)
    """The rule's calendar (and the calendar of a calendar duration)."""
    resolved: Mapping[str, int] = field(default_factory=dict)
    """Resolved moments of the rule's time points, by JSON pointer (``/limit/until``)."""


@dataclass(frozen=True, slots=True)
class Occurrence:
    key: str
    start: int
    end: int

    def as_json(self) -> dict[str, str]:
        return {"key": self.key, "start": str(self.start), "end": str(self.end)}


class Plan(ABC):
    """Candidate periods ``k ≥ 0``; positions of later periods start later."""

    multi: bool = False
    """Keys are ``k.j`` (the rule may select several positions per period)."""

    def __init__(self, ctx: RecurrenceContext, last: int) -> None:
        self.ctx = ctx
        self.last = last
        """The latest allowed start: ``min(until, D)``."""
        end = ctx.end
        self.duration = end.duration if isinstance(end, DurationEnd) else None

    @abstractmethod
    def positions(self, k: int) -> list[int | None]:
        """Period ``k``'s positions in time order (ignoring the series bounds)."""

    @abstractmethod
    def k_range(self, low: int, high: int) -> tuple[int, int]:
        """Periods (``k ≥ 0``) whose positions may lie in ``[low, high]``; empty if ``lo > hi``."""

    @property
    @abstractmethod
    def dense(self) -> bool:
        """Every period has exactly one position with an occurrence."""

    def end_of(self, start: int) -> int:
        duration = self.duration
        if duration is None:
            return start
        if isinstance(duration, CalendarDuration):
            assert self.ctx.calendar is not None
            return add(self.ctx.calendar, start, duration)
        return start + int(duration.units)

    def exact_length(self) -> int | None:
        """The occurrence length when it is the same for every occurrence."""
        duration = self.duration
        if duration is None:
            return 0
        return None if isinstance(duration, CalendarDuration) else int(duration.units)

    def upper_length(self) -> int:
        duration = self.duration
        if duration is None:
            return 0
        if isinstance(duration, CalendarDuration):
            assert self.ctx.calendar is not None
            return duration_upper_bound(self.ctx.calendar, duration)
        return abs(int(duration.units))

    def key(self, k: int, j: int) -> str:
        return f"{k}.{j}" if self.multi else str(k)

    def occurrences(self, k: int) -> list[Occurrence]:
        """Period ``k``'s occurrences within the series bounds, in time order."""
        found: list[Occurrence] = []
        for j, start in enumerate(self.positions(k)):
            if start is not None and self.ctx.series_start <= start <= self.last:
                found.append(Occurrence(self.key(k, j), start, self.end_of(start)))
        return found

    def scan(self, k: int, step: Literal[1, -1]) -> list[Occurrence] | None:
        """The occurrences of the first period from ``k`` on (in direction ``step``) that has
        any, within :data:`SCAN_LIMIT` periods."""
        for candidate in range(k, k + step * SCAN_LIMIT, step):
            if candidate < 0:
                return None
            found = self.occurrences(candidate)
            if found:
                return found
        return None

    def estimate(self, k_lo: int, k_hi: int) -> int:
        """Occurrences in periods ``k_lo … k_hi``: exact for dense plans, else sampled."""
        count = k_hi - k_lo + 1
        if self.dense:
            return count
        samples = min(count, SAMPLES)
        ks = {k_lo + i * (count - 1) // max(samples - 1, 1) for i in range(samples)}
        hits = sum(sum(p is not None for p in self.positions(k)) for k in ks)
        return count * hits // len(ks)
