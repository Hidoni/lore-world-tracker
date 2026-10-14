"""The species module's consistency rules (``docs/modules/species.md``).

- ``species.member_before_emergence``: a member of a species (``is_a``) exists before the species
  emerged, or after it went extinct.
"""

from lore.core.consistency.narrative import links_of, narrative_rule, periods_within
from lore.core.registry.types import RuleDef, Trigger
from lore.modules.species.links import IS_A

CONSISTENCY_RULES: tuple[RuleDef, ...] = (
    narrative_rule(
        "species.member_before_emergence",
        "species",
        "Member outside the species' existence",
        "An entity of a species exists before the species emerged (or after it went extinct).",
        periods_within(
            "species.member_before_emergence",
            lambda ctx, subjects: links_of(ctx, subjects, IS_A),
            lambda member, species: f"“{member}” exists while its species “{species}” doesn't.",
        ),
        triggers=(Trigger("record", "*"), Trigger("link_type", IS_A)),
    ),
)

__all__ = ["CONSISTENCY_RULES"]
