"""Search routes (``docs/architecture/api.md`` §2, Search)."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from lore.core.api.deps import ModuleRegistryDep, SessionDep, VaultDep
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.registry import ModuleRegistry
from lore.core.search.queries import AUTHOR, READER, SearchQueries
from lore.core.search.schemas import QuickResults, SearchPage
from lore.core.vaults import OpenVault

router = APIRouter(prefix="/vaults/{vault_id}/search", tags=["search"])

KindsQuery = Annotated[
    list[str] | None,
    Query(alias="kind", description="Entity kinds or module document types (repeatable)."),
]
DimensionQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]


def _queries(vault: OpenVault, session: Session, registry: ModuleRegistry) -> SearchQueries:
    # Until the visibility framework (#40) passes its policy: a read-only server searches as a
    # reader.
    return SearchQueries(session, registry, READER if vault.read_only else AUTHOR)


@router.get("", name="search")
def search(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=500,
            description='Words match word beginnings; "quoted phrases" match exactly; OR '
            "between alternatives; -word or NOT word leaves out; parentheses group.",
        ),
    ],
    kinds: KindsQuery = None,
    dimension: DimensionQuery = None,
    include_multiversal: bool = True,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> SearchPage:
    """Full-text search over names, aliases, summaries, bodies, fields and module documents,
    best matches first, with highlighted snippets."""
    return _queries(vault, session, registry).search(
        q,
        kinds=kinds,
        dimension=dimension,
        include_multiversal=include_multiversal,
        cursor=cursor,
        limit=limit,
    )


@router.get("/quick", name="quick")
def quick(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    q: Annotated[str, Query(max_length=200)],
    kinds: KindsQuery = None,
    dimension: DimensionQuery = None,
    include_multiversal: bool = True,
) -> QuickResults:
    """The quick switcher: up to 20 names or aliases starting with the typed words, then names
    or public aliases containing the typed text."""
    return _queries(vault, session, registry).quick(
        q, kinds=kinds, dimension=dimension, include_multiversal=include_multiversal
    )
