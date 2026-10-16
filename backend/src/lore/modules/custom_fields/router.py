"""Routes of the custom_fields module, mounted at ``/api/v1/vaults/{vault_id}/m/custom_fields``
(``docs/modules/custom_fields.md``, API). Definitions are the author's tools: readers get 404
(what they may see of the fields comes with ``GET /registry`` and the entities)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep, WritableVaultDep
from lore.core.consistency.schemas import request_suppress
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.core.visibility import VisibilityPolicy
from lore.modules.custom_fields.kinds import CustomKinds
from lore.modules.custom_fields.schemas import (
    ConvertKind,
    ConvertKindResult,
    CustomFieldCreate,
    CustomFieldDeleteResult,
    CustomFieldList,
    CustomFieldOut,
    CustomFieldUpdate,
    CustomFieldWriteResult,
    CustomKindCreate,
    CustomKindDeleteResult,
    CustomKindList,
    CustomKindOut,
    CustomKindUpdate,
    CustomKindWriteResult,
    FieldReorder,
    KindKey,
)
from lore.modules.custom_fields.service import CustomFields

router = APIRouter(tags=["custom_fields"])

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]
KindPath = Annotated[
    str, Path(pattern=r"^custom\.[a-z][a-z0-9_]{0,59}$", description="`custom.<slug>`.")
]


def _author_only(policy: VisibilityPolicy) -> None:
    policy.require_author("Field definitions aren't available to readers.")


@router.get("/fields", name="list")
def list_fields(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    kind: Annotated[
        KindKey | None,
        Query(description="The fields of this kind: its own and those of every kind (`*`)."),
    ] = None,
) -> CustomFieldList:
    """The custom fields (archived ones too), by kind then order, with how many live entities
    have a value."""
    _author_only(policy)
    return CustomFields(VaultContext(vault, session, registry)).list_fields(kind)


@router.post("/fields", name="create", status_code=201)
def create_field(
    body: CustomFieldCreate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> CustomFieldWriteResult:  # fmt: skip
    """A field of a kind (`*`: of every kind but the system ones), keyed `custom.<key>`."""
    request_suppress(session, body.suppress)
    return CustomFields(VaultContext(vault, session, registry)).create(body)


@router.post("/fields/reorder", name="reorder")
def reorder_fields(
    body: FieldReorder, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> CustomFieldList:  # fmt: skip
    """The kind's custom fields in this order (each once)."""
    return CustomFields(VaultContext(vault, session, registry)).reorder(body)


@router.get("/fields/{field_id}", name="get")
def get_field(
    *, field_id: IdPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> CustomFieldOut:  # fmt: skip
    _author_only(policy)
    return CustomFields(VaultContext(vault, session, registry)).get(field_id)


@router.patch("/fields/{field_id}", name="update")
def update_field(
    field_id: IdPath, body: CustomFieldUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> CustomFieldWriteResult:  # fmt: skip
    """Change the field. Type changes follow the safe conversions (text ↔ long_text,
    enum → multi_enum, text → enum with `value_map`, integer → decimal) and migrate the values
    in the same changeset; options in use can't be removed; turning `temporal` off with facts
    needs `facts` (`drop` moves them to the trash, `keep` leaves them, hidden)."""
    request_suppress(session, body.suppress)
    return CustomFields(VaultContext(vault, session, registry)).update(field_id, body)


@router.delete("/fields/{field_id}", name="delete")
def delete_field(
    field_id: IdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    delete_values: Annotated[
        bool, Query(description="Delete the values too (409 `conflict` otherwise, if any).")
    ] = False,
) -> CustomFieldDeleteResult:
    """Delete the field (archiving keeps the values). Its values go in the same changeset, so
    undo brings everything back."""
    return CustomFields(VaultContext(vault, session, registry)).delete(
        field_id, delete_values=delete_values
    )


# --- kinds ---------------------------------------------------------------------------------------


@router.get("/kinds", name="list_kinds")
def list_kinds(
    *, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep, policy: PolicyDep
) -> CustomKindList:
    """The custom kinds (archived ones too), with how many entities have each."""
    _author_only(policy)
    return CustomKinds(VaultContext(vault, session, registry)).list_kinds()


@router.post("/kinds", name="create_kind", status_code=201)
def create_kind(
    body: CustomKindCreate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> CustomKindWriteResult:  # fmt: skip
    """A kind keyed `custom.<key>`: its entities work like any other kind's."""
    request_suppress(session, body.suppress)
    return CustomKinds(VaultContext(vault, session, registry)).create(body)


@router.get("/kinds/{kind_key}", name="get_kind")
def get_kind(
    *, kind_key: KindPath, vault: VaultDep, session: SessionDep, registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> CustomKindOut:  # fmt: skip
    _author_only(policy)
    return CustomKinds(VaultContext(vault, session, registry)).get(kind_key)


@router.patch("/kinds/{kind_key}", name="update_kind")
def update_kind(
    kind_key: KindPath, body: CustomKindUpdate, vault: WritableVaultDep, session: SessionDep,
    registry: ModuleRegistryDep,
) -> CustomKindWriteResult:  # fmt: skip
    """Change the kind; `archived` hides it and its entities (nothing is deleted)."""
    request_suppress(session, body.suppress)
    return CustomKinds(VaultContext(vault, session, registry)).update(kind_key, body)


@router.delete("/kinds/{kind_key}", name="delete_kind")
def delete_kind(
    kind_key: KindPath, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> CustomKindDeleteResult:
    """Delete a kind no entity has (the trash included; `409 conflict` otherwise), with its
    custom fields."""
    return CustomKinds(VaultContext(vault, session, registry)).delete(kind_key)


@router.post("/convert-kind", name="convert_kind")
def convert_kind(
    body: ConvertKind, vault: WritableVaultDep, session: SessionDep, registry: ModuleRegistryDep
) -> ConvertKindResult:
    """Give entities another kind (built-in ↔ custom), in one changeset: `field_mapping` moves
    values, facts and visibility overrides to the new kind's fields (`null` drops them);
    unmapped values stay stored. Kinds with data of their own (events, dimensions, timelines,
    calendars, languages) can't be converted."""
    request_suppress(session, body.suppress)
    return CustomKinds(VaultContext(vault, session, registry)).convert(body)
