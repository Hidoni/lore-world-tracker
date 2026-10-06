"""Stored time points as readers see them (``visibility-and-sharing.md`` §2): an anchor that
references a record the reader can't see (a private calendar, a slot of a hidden record) still
resolves, but the reader gets the resolved moment, not the reference.

    times = ReaderTimes(context, policy)
    shown = times.point(link.valid_from_spec, dimension_id)   # unchanged for authors

Such a point is returned as an ``absolute`` anchor at its resolved moment, keeping its precision
when the dimension's default calendar has that level (``base`` otherwise) and its circa flag. A
point that doesn't resolve (or whose dimension is unknown) is left out (``None``).
"""

from typing import TYPE_CHECKING, Any

from lore.chronology.schema import CalendarAnchor, CalendarDuration, RelativeAnchor, TimePoint
from lore.core.errors import ConflictError
from lore.core.time.models import Calendar
from lore.core.time.resolve import BASE, Resolver, owner_visible
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID, SpecError, dump_spec, parse_time_point
from lore.core.visibility import AUTHOR, VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.modules.spec import VaultContext


class ReaderTimes:
    """Redacts stored time points for one request's policy (a no-op for authors)."""

    def __init__(self, context: VaultContext, policy: VisibilityPolicy) -> None:
        self.context = context
        self.policy = policy
        self._resolvers: dict[str, Resolver] = {}

    def point(self, document: Any, dimension_id: str | None) -> Any:
        """A stored time point (a document or a ``TimePoint``) as the policy may see it."""
        if document is None or not self.policy.reader:
            return document
        try:
            point = parse_time_point(document)
        except SpecError:
            return None  # never stored like this; nothing to show
        if self._visible(point):
            return document
        t, precision = self._moment(point, self._dimension(point) or dimension_id)
        if t is None:
            return None
        anchor = {"kind": "absolute", "t": str(t)}
        shown = TimePoint.model_validate(
            {"anchor": anchor, "precision": precision, "approximate": point.approximate}
        )
        return dump_spec(shown)

    def _moment(self, point: TimePoint, dimension_id: str | None) -> tuple[int | None, str]:
        """The point's resolved moment and the precision to show it with."""
        author = None if dimension_id is None else self._resolver(dimension_id)
        result = None if author is None else author.resolve(point)
        if author is None or result is None or result.t is None or result.t < 0:
            return None, BASE
        keep = point.precision == BASE or author.has_default_level(point.precision)
        return result.t, point.precision if keep else BASE

    def _resolver(self, dimension_id: str) -> Resolver | None:
        """An author's resolver (the point resolves through everything; only its moment is
        shown)."""
        if dimension_id not in self._resolvers:
            try:
                self._resolvers[dimension_id] = Resolver(self.context, dimension_id, policy=AUTHOR)
            except ConflictError:  # not a dimension
                return None
        return self._resolvers[dimension_id]

    def _calendar_visible(self, calendar_id: str) -> bool:
        return calendar_id == ABSOLUTE_CALENDAR_ID or bool(
            self.policy.visible_ids(self.context.session, [calendar_id])
        )

    def _visible(self, point: TimePoint) -> bool:
        anchor = point.anchor
        if isinstance(anchor, CalendarAnchor):
            return self._calendar_visible(anchor.calendar_id)
        if isinstance(anchor, RelativeAnchor):
            if isinstance(anchor.offset, CalendarDuration) and not self._calendar_visible(
                anchor.offset.calendar_id
            ):
                return False
            provider = self.context.registry.slot_registry().get(anchor.ref.type)
            return provider is not None and owner_visible(
                self.context.session, self.policy, provider, anchor.ref.id
            )
        return True

    def _dimension(self, point: TimePoint) -> str | None:
        """The dimension a point's calendar belongs to (``None`` without a calendar)."""
        anchor = point.anchor
        calendar_id = None
        if isinstance(anchor, CalendarAnchor):
            calendar_id = anchor.calendar_id
        elif isinstance(anchor, RelativeAnchor) and isinstance(anchor.offset, CalendarDuration):
            calendar_id = anchor.offset.calendar_id
        row = None if calendar_id is None else self.context.session.get(Calendar, calendar_id)
        return None if row is None else row.dimension_id
