"""Search routes (``docs/architecture/api.md`` §2, Search)."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.registry import ModuleRegistry
from lore.core.search.queries import SearchQueries
from lore.core.search.schemas import QuickResults, SearchPage
from lore.core.visibility import VisibilityPolicy

router = APIRouter(prefix="/vaults/{vault_id}/search", tags=["search"])

KindsQuery = Annotated[
    list[str] | None,
    Query(alias="kind", description="Entity kinds or module document types (repeatable)."),
]
DimensionQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]


def _queries(session: Session, registry: ModuleRegistry, policy: VisibilityPolicy) -> SearchQueries:
    return SearchQueries(session, registry, policy)


@router.get("", name="search")
def search(
    *,
    _vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
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
    return _queries(session, registry, policy).search(
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
    _vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    q: Annotated[str, Query(max_length=200)],
    kinds: KindsQuery = None,
    dimension: DimensionQuery = None,
    include_multiversal: bool = True,
) -> QuickResults:
    """The quick switcher: up to 20 names or aliases starting with the typed words, then names
    or public aliases containing the typed text."""
    return _queries(session, registry, policy).quick(
        q, kinds=kinds, dimension=dimension, include_multiversal=include_multiversal
    )
