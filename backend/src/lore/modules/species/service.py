"""Reads of the species module: members and the descent graph, through the request's
``VisibilityPolicy``."""

from dataclasses import dataclass

from sqlalchemy import or_, select

from lore.core.entities.models import Entity
from lore.core.entities.service import EntityService
from lore.core.errors import NotFoundError
from lore.core.links.models import Link
from lore.core.links.schemas import EntityLinks
from lore.core.links.service import LinkService
from lore.core.modules.spec import VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.species.kinds import SPECIES
from lore.modules.species.links import DESCENDED_FROM, IS_A
from lore.modules.species.schemas import DescentEdge, DescentNode, DescentTree


@dataclass
class Species:
    context: VaultContext
    policy: VisibilityPolicy

    def members(self, species_id: str) -> EntityLinks:
        """Everyone and everything that `is_a` the species, at any time."""
        entity = EntityService(self.context, self.policy).load_visible(species_id)
        if entity.kind != SPECIES:
            raise NotFoundError(f"No species {species_id}.")
        context = self.context
        links = LinkService(context.session, context.registry, self.policy, context.vault)
        return links.entity_links(species_id, direction="in", types=[IS_A])

    def descent_tree(self, *, dimension: str | None, limit: int) -> DescentTree:
        """Species (of ``dimension`` and multiversal ones, or all) with the descent links
        between them and the subspecies edges of their parents."""
        session = self.context.session
        statement = (
            select(Entity)
            .where(
                Entity.kind == SPECIES,
                Entity.deleted_at.is_(None),
                *self.policy.entities(Entity),
            )
            .order_by(Entity.sort_name, Entity.id)
            .limit(limit + 1)
        )
        if dimension is not None:
            statement = statement.where(
                or_(Entity.dimension_id == dimension, Entity.dimension_id.is_(None))
            )
        found = list(session.scalars(statement))
        truncated = len(found) > limit
        found = found[:limit]
        ids = {species.id for species in found}
        links = session.scalars(
            select(Link)
            .where(
                Link.link_type == DESCENDED_FROM,
                Link.deleted_at.is_(None),
                Link.source_id.in_(ids),
                Link.target_id.in_(ids),
                *self.policy.links(Link),
            )
            .order_by(Link.id)
        )
        edges = [
            DescentEdge(
                id=link.id,
                kind="descended_from",
                source_id=link.source_id,
                target_id=link.target_id,
            )
            for link in links
        ]
        edges += [
            DescentEdge(
                id=f"subspecies:{species.id}",
                kind="subspecies",
                source_id=species.id,
                target_id=species.parent_id,
            )
            for species in found
            if species.parent_id is not None and species.parent_id in ids
        ]
        nodes = [
            DescentNode(
                id=species.id,
                name=species.name,
                visibility=species.visibility,
                dimension_id=species.dimension_id,
                parent_id=species.parent_id if species.parent_id in ids else None,
            )
            for species in found
        ]
        return DescentTree(nodes=nodes, edges=edges, truncated=truncated)
