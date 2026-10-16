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
from lore.modules.custom_fields.schemas import (
    CustomFieldCreate,
    CustomFieldDeleteResult,
    CustomFieldList,
    CustomFieldOut,
    CustomFieldUpdate,
    CustomFieldWriteResult,
    FieldReorder,
    KindKey,
)
from lore.modules.custom_fields.service import CustomFields

router = APIRouter(tags=["custom_fields"])

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]


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
