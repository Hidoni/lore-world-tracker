"""The correspondences module's consistency rules (``docs/modules/correspondences.md``).

- ``correspondences.inconsistent_paths`` (warning): a correspondence and another path between
  the same two dimensions (through other correspondences) disagree at one of its sync points by
  a whole base unit or more (``time-model.md`` §12.3). Paths are compared exactly, without the
  flooring each mapping step does, so rounding alone never reports.
"""

from collections.abc import Iterable, Iterator

from lore.core.consistency.engine import FindingDraft, RuleContext
from lore.core.registry.types import RuleDef, Trigger
from lore.core.time.correspondences import CorrespondenceGraph

RULE = "correspondences.inconsistent_paths"


def _findings(ctx: RuleContext, subjects: Iterable[str] | None) -> Iterator[FindingDraft]:
    wanted = None if subjects is None else set(subjects)
    graph = CorrespondenceGraph.load(ctx.session)
    for correspondence_id in sorted(graph.compiled):
        row = graph.rows[correspondence_id]
        ends = (row.dimension_a_id, row.dimension_b_id)
        if wanted is not None and not wanted & set(ends):
            continue
        path = graph.path(*ends, without=correspondence_id)
        if not path:
            continue
        compiled = graph.compiled[correspondence_id]
        for position, (a, b) in enumerate(compiled.points):
            other = graph.exact(path, a)
            if other is None or abs(other - b) < 1:
                continue
            yield FindingDraft(
                RULE,
                ends,
                f"“{row.name}” and another chain of correspondences disagree about what happens "
                "at the same time in these dimensions.",
                discriminator=correspondence_id,
                data={
                    "correspondence_id": correspondence_id,
                    "point": position,
                    "expected_t": str(b),
                    "other_t": str(other.numerator // other.denominator),
                    "other_path": [edge.correspondence_id for edge in path],
                },
            )
            break


CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    RuleDef(
        id=RULE,
        owner="correspondences",
        title="Correspondences disagree",
        description="Two ways of relating the same dimensions (one correspondence, and a chain "
        "of others) put a sync point at different moments. Adjust one of them.",
        category="structural",
        default_severity="warning",
        configurable=True,
        triggers=(Trigger("record", "dimension"),),
        check=_findings,
        scan=lambda ctx: _findings(ctx, None),
    ),
)
