"""Generic entity routes (``docs/architecture/api.md`` §2, Entities)."""

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query
from sqlalchemy.orm import Session

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.entities.queries import EntityQueries, ExistenceOf
from lore.core.entities.schemas import (
    AT_PATTERN,
    ID_PATTERN,
    EntityCreate,
    EntityDeleteResult,
    EntityOut,
    EntityPage,
    EntityStateOut,
    EntityUpdate,
    EntityWriteResult,
    FieldValueList,
    ListSort,
    TagList,
    TrashPage,
    TreePage,
)
from lore.core.entities.service import EntityService
from lore.core.facts.state import EntityStates, existence_of
from lore.core.modules.registry import ModuleRegistry
from lore.core.modules.spec import VaultContext
from lore.core.vaults import OpenVault
from lore.core.visibility import AUTHOR, VisibilityPolicy

router = APIRouter(prefix="/vaults/{vault_id}/entities", tags=["entities"])
tree_router = APIRouter(prefix="/vaults/{vault_id}", tags=["tree"])
trash_router = APIRouter(prefix="/vaults/{vault_id}", tags=["trash"])
tags_router = APIRouter(prefix="/vaults/{vault_id}", tags=["tags"])

EntityIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Entity id.")]
IdQuery = Annotated[str | None, Query(pattern=ID_PATTERN)]
KindsQuery = Annotated[
    list[str] | None, Query(alias="kind", description="Kind keys (repeat for several).")
]
CursorQuery = Annotated[str | None, Query(max_length=4096)]
TimelineQuery = Annotated[
    str | None,
    Query(pattern=ID_PATTERN, description="The time cursor's timeline (with `at`)."),
]
AtQuery = Annotated[
    str | None,
    Query(
        pattern=AT_PATTERN,
        max_length=1000,
        description="The time cursor: a moment, or `present` (the timeline's dimension's).",
    ),
]


def _service(
    vault: OpenVault,
    session: Session,
    registry: ModuleRegistry,
    policy: VisibilityPolicy = AUTHOR,
) -> EntityService:
    return EntityService(VaultContext(vault, session, registry), policy)


def _queries(
    vault: OpenVault,
    session: Session,
    registry: ModuleRegistry,
    policy: VisibilityPolicy,
    existence: ExistenceOf | None = None,
) -> EntityQueries:
    return EntityQueries(_service(vault, session, registry, policy), existence)


def _existence(
    vault: OpenVault,
    session: Session,
    registry: ModuleRegistry,
    policy: VisibilityPolicy,
    *,
    timeline: str | None,
    at: str | None,
    dimension: str | None,
) -> ExistenceOf | None:
    context = VaultContext(vault, session, registry)
    return existence_of(context, policy, timeline_id=timeline, at=at, dimension_id=dimension)


# Static paths first: "/field-values" must not be taken for an entity id.


@router.get("", name="list")
def list_entities(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    kinds: KindsQuery = None,
    dimension: IdQuery = None,
    include_multiversal: bool = True,
    parent: IdQuery = None,
    tags: Annotated[
        list[str] | None, Query(alias="tag", description="Tag ids; entities need all of them.")
    ] = None,
    q: Annotated[
        str | None, Query(max_length=500, description="Name or alias prefix (until search).")
    ] = None,
    include_trashed: bool = False,
    sort: ListSort = "name",
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> EntityPage:
    """Entities of enabled kinds. ``dimension`` includes multiversal entities unless
    ``include_multiversal=false``. ``name`` sorts ignoring case and accents, numbers by value.
    With ``at`` (and ``timeline``, default: the prime timeline of ``dimension``), entities that
    don't exist then are left out; a page may then be short and still have a ``next_cursor``."""
    existence = _existence(
        vault, session, registry, policy, timeline=timeline, at=at, dimension=dimension
    )
    return _queries(vault, session, registry, policy, existence).list_entities(
        kinds=kinds,
        dimension=dimension,
        include_multiversal=include_multiversal,
        parent=parent,
        tags=tags,
        q=q,
        include_trashed=include_trashed,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.get("/field-values", name="field_values")
def list_field_values(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    kind: Annotated[str, Query(max_length=100)],
    field: Annotated[str, Query(max_length=200)],
    q: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FieldValueList:
    """Distinct values of a text field for autocomplete, most used first."""
    return _queries(vault, session, registry, policy).field_values(
        kind=kind, field=field, q=q, limit=limit
    )


@tree_router.get("/tree", name="get")
def get_tree(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: IdQuery = None,
    parent: IdQuery = None,
    kinds: KindsQuery = None,
    group_by: Annotated[
        str | None,
        Query(max_length=200, description="A text field of the one kind: each node's `group`."),
    ] = None,
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> TreePage:
    """One level of the navigation tree: the roots (entities without a shown parent), or the
    children of ``parent``. Manually ordered entities (``sort_key``) first, then by name. ``at``
    filters by existence as in entity lists (child counts don't)."""
    existence = _existence(
        vault, session, registry, policy, timeline=timeline, at=at, dimension=dimension
    )
    return _queries(vault, session, registry, policy, existence).tree(
        dimension=dimension,
        parent=parent,
        kinds=kinds,
        group_by=group_by,
        cursor=cursor,
        limit=limit,
    )


@tags_router.get("/tags", name="list")
def list_tags(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    q: Annotated[str | None, Query(max_length=200, description="A name prefix.")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> TagList:
    """Tags in use on the entities the request sees (not in the trash), by name, with how many
    use each (for filters)."""
    return _queries(vault, session, registry, policy).tags(q=q, limit=limit)


@trash_router.get("/trash", name="list")
def list_trash(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> TrashPage:
    """Trashed entities, most recently trashed first, with their orphaned children count."""
    return _queries(vault, session, registry, policy).trash(cursor=cursor, limit=limit)


@router.post("", name="create", status_code=201)
def create_entity(
    body: EntityCreate, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> EntityWriteResult:
    """Create an entity of any kind, with its aliases, tags and kind extension data."""
    return _service(vault, session, registry).create(body)


@router.get("/{entity_id}", name="get")
def get_entity(
    *,
    entity_id: EntityIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> EntityOut:
    """The full entity (for the author also when it is in the trash; ``deleted_at`` is then
    set). With ``at``, its ``state`` then, as ``GET …/state`` returns it."""
    service = _service(vault, session, registry, policy)
    out = service.get(entity_id)
    if at is not None:
        states = EntityStates(VaultContext(vault, session, registry), policy)
        out.state = states.of_entity(entity_id, timeline_id=timeline, at=at)
    return out


@router.get("/{entity_id}/state", name="state")
def get_entity_state(
    *,
    entity_id: EntityIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    timeline: TimelineQuery = None,
    at: Annotated[
        str,
        Query(
            pattern=AT_PATTERN,
            max_length=1000,
            description="A moment, or `present` (the timeline's dimension's present).",
        ),
    ],
) -> EntityStateOut:
    """What was true of the entity at ``at`` in ``timeline`` (default: its dimension's prime
    timeline; required for multiversal entities): existence, name and temporal fields, with
    certainty (``time-model.md`` §10.5)."""
    states = EntityStates(VaultContext(vault, session, registry), policy)
    return states.of_entity(entity_id, timeline_id=timeline, at=at)


@router.get("/{entity_id}/children", name="children")
def list_children(
    *,
    entity_id: EntityIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    kinds: KindsQuery = None,
    cursor: CursorQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    timeline: TimelineQuery = None,
    at: AtQuery = None,
) -> TreePage:
    """Children of every kind and dimension (not in the trash), sorted like the tree. ``at``
    (with ``timeline``) filters by existence as in entity lists."""
    existence = _existence(
        vault, session, registry, policy, timeline=timeline, at=at, dimension=None
    )
    return _queries(vault, session, registry, policy, existence).children(
        entity_id, kinds=kinds, cursor=cursor, limit=limit
    )


@router.patch("/{entity_id}", name="update")
def update_entity(
    entity_id: EntityIdPath,
    body: EntityUpdate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> EntityWriteResult:
    """Change the members sent. ``409 revision_conflict`` (with ``context.current``) when
    ``revision`` isn't the current one; ``409 conflict`` while the entity is in the trash."""
    return _service(vault, session, registry).update(entity_id, body)


@router.delete("/{entity_id}", name="delete")
def delete_entity(
    *,
    entity_id: EntityIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    purge: Annotated[
        bool, Query(description="Delete permanently (only entities already in the trash).")
    ] = False,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> EntityDeleteResult:
    """Move to the trash, or purge from it (``409 conflict`` while the entity isn't trashed, has
    children or is still referenced)."""
    request_suppress(session, suppress.suppress if suppress else None)
    service = _service(vault, session, registry)
    return service.purge(entity_id) if purge else service.trash(entity_id)


@router.post("/{entity_id}/restore", name="restore")
def restore_entity(
    entity_id: EntityIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> EntityWriteResult:
    """Take the entity out of the trash."""
    request_suppress(session, suppress.suppress if suppress else None)
    return _service(vault, session, registry).restore(entity_id)
