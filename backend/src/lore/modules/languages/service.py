"""Reads of the languages module: the language family graph, through the request's
``VisibilityPolicy``."""

from dataclasses import dataclass

from sqlalchemy import or_, select

from lore.core.entities.models import Entity
from lore.core.links.models import Link
from lore.core.modules.spec import VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.languages.kinds import LANGUAGE
from lore.modules.languages.links import BORROWED_FROM, DESCENDED_FROM
from lore.modules.languages.schemas import FamilyEdge, FamilyNode, FamilyTree

KINDS = {DESCENDED_FROM: "descended_from", BORROWED_FROM: "borrowed_from"}


@dataclass
class Languages:
    context: VaultContext
    policy: VisibilityPolicy

    def family_tree(self, *, dimension: str | None, limit: int) -> FamilyTree:
        """Languages (of ``dimension`` and multiversal ones, or all) with the descent and
        borrowing links between them and the dialect edges of their parents."""
        session = self.context.session
        statement = (
            select(Entity)
            .where(
                Entity.kind == LANGUAGE, Entity.deleted_at.is_(None), *self.policy.entities(Entity)
            )
            .order_by(Entity.sort_name, Entity.id)
            .limit(limit + 1)
        )
        if dimension is not None:
            statement = statement.where(
                or_(Entity.dimension_id == dimension, Entity.dimension_id.is_(None))
            )
        languages = list(session.scalars(statement))
        truncated = len(languages) > limit
        languages = languages[:limit]
        ids = {language.id for language in languages}
        links = session.scalars(
            select(Link)
            .where(
                Link.link_type.in_(KINDS),
                Link.deleted_at.is_(None),
                Link.source_id.in_(ids),
                Link.target_id.in_(ids),
                *self.policy.links(Link),
            )
            .order_by(Link.id)
        )
        edges = [
            FamilyEdge(
                id=link.id,
                kind=KINDS[link.link_type],  # type: ignore[arg-type]
                source_id=link.source_id,
                target_id=link.target_id,
            )
            for link in links
        ]
        edges += [
            FamilyEdge(
                id=f"dialect:{language.id}",
                kind="dialect",
                source_id=language.id,
                target_id=language.parent_id,
            )
            for language in languages
            if language.parent_id in ids and language.parent_id is not None
        ]
        nodes = [
            FamilyNode(
                id=language.id,
                name=language.name,
                visibility=language.visibility,
                dimension_id=language.dimension_id,
                parent_id=language.parent_id if language.parent_id in ids else None,
            )
            for language in languages
        ]
        return FamilyTree(nodes=nodes, edges=edges, truncated=truncated)
