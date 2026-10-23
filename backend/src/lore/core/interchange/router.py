"""The interchange download and upload (``docs/architecture/api.md`` §2, Vaults & settings;
``interchange.md``).

Author-only: readers (including ``?as_reader=true``) get ``404`` for the export, and a read-only
server refuses the import (``403 read_only``). Neither route takes the request's session: the
export reads a copy of the database, the import writes in its own transaction."""

import re
import tempfile
from collections.abc import Iterator
from typing import IO, Annotated

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lore.core.api.deps import PolicyDep, VaultDep, VaultManagerDep, WritableVaultDep
from lore.core.interchange.export import export_interchange
from lore.core.interchange.format import Audience, ConflictMode, IdMode
from lore.core.interchange.importer import ImportReport, import_interchange

router = APIRouter(prefix="/vaults/{vault_id}", tags=["export"])
import_router = APIRouter(prefix="/vaults/{vault_id}", tags=["import"])

_CHUNK = 1 << 20
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_ZIP = {"type": "string", "format": "binary"}


def _chunks(file: IO[bytes]) -> Iterator[bytes]:
    try:
        file.seek(0)
        while chunk := file.read(_CHUNK):
            yield chunk
    finally:
        file.close()


@router.get(
    "/export/interchange",
    name="interchange",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {"schema": _ZIP}}}},
)
def interchange_export(
    *,
    vault: VaultDep,
    manager: VaultManagerDep,
    policy: PolicyDep,
    audience: Annotated[
        Audience,
        Query(description="`readers`: what readers see (no private data); `author`: everything."),
    ] = "readers",
    dimension: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Export one dimension (its id or exact name): its records, and the "
            "multiversal entities they refer to as references. Default: the whole vault.",
        ),
    ] = None,
) -> StreamingResponse:
    """The vault (or one dimension) as an interchange zip: a versioned JSON document of its
    records with their media files, which any vault of this app or a later one imports."""
    policy.require_author("The interchange export isn't available to readers.")
    file = tempfile.SpooledTemporaryFile(max_size=16 * _CHUNK)  # noqa: SIM115 (closed by _chunks)
    try:
        export_interchange(manager, vault.id, file, audience=audience, dimension=dimension)
    except BaseException:
        file.close()
        raise
    name = _UNSAFE.sub("-", vault.info.folder).strip("-") or "vault"
    if dimension is not None:
        name += "-" + (_UNSAFE.sub("-", dimension).strip("-")[:60] or "dimension")
    suffix = "" if audience == "readers" else "-private"
    return StreamingResponse(
        _chunks(file),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}-lore{suffix}.zip"'},
    )


class InterchangeReference(BaseModel):
    id: str
    kind: str
    name: str


class InterchangeImport(BaseModel):
    """What an import did. Counts are by table: ``created`` rows, ``updated`` (overwritten),
    ``reused`` (the vault's own: the same, or matched by a unique key such as a tag's name),
    ``dropped`` (they needed a record the vault doesn't have)."""

    ids: IdMode
    scope: str
    entities: int
    created: dict[str, int]
    updated: dict[str, int]
    reused: dict[str, int]
    dropped: dict[str, int]
    references_matched: int
    references_unmatched: list[InterchangeReference]
    files: int
    changeset_id: str | None

    @classmethod
    def of(cls, report: ImportReport) -> InterchangeImport:
        return cls(
            ids=report.ids,
            scope=report.scope,
            entities=len(report.entities),
            created=report.created,
            updated=report.updated,
            reused=report.reused,
            dropped=report.dropped,
            references_matched=report.references_matched,
            references_unmatched=[
                InterchangeReference(id=r.id, kind=r.kind, name=r.name)
                for r in report.references_unmatched
            ],
            files=report.files,
            changeset_id=report.changeset_id,
        )


@import_router.post("/import/interchange", name="interchange")
def interchange_import(
    *,
    vault: WritableVaultDep,
    manager: VaultManagerDep,
    file: UploadFile,
    ids: Annotated[
        IdMode,
        Query(
            description="`remap`: fresh ids (importing twice gives two copies); `keep`: the "
            "file's ids (to move records between your own vaults)."
        ),
    ] = "remap",
    on_conflict: Annotated[
        ConflictMode,
        Query(
            description="Records whose id or unique key the vault has, but different: `fail` "
            "refuses the import with a report (`409 interchange_conflict`); `overwrite` "
            "replaces the vault's (after a backup)."
        ),
    ] = "fail",
) -> InterchangeImport:
    """Import an interchange zip (or a bare JSON document) into this vault, in one transaction
    recorded as one changeset (undoable) and checked by the consistency engine."""
    report = import_interchange(manager, vault.id, file.file, ids=ids, on_conflict=on_conflict)
    return InterchangeImport.of(report)
