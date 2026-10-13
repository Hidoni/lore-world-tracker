"""Routes of the languages module, mounted at ``/api/v1/vaults/{vault_id}/m/languages``."""

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Response

from lore.core.api.deps import (
    ModuleRegistryDep,
    PolicyDep,
    SessionDep,
    VaultDep,
    WritableVaultDep,
)
from lore.core.consistency.schemas import SuppressIn, request_suppress
from lore.core.entities.schemas import ID_PATTERN
from lore.core.modules.spec import VaultContext
from lore.modules.languages.lexicon import Lexicon, entry_out
from lore.modules.languages.lexicon_csv import export_csv, import_csv
from lore.modules.languages.lexicon_schemas import (
    ImportIn,
    ImportReport,
    LexiconEntryCreate,
    LexiconEntryOut,
    LexiconEntryUpdate,
    LexiconPage,
    LexiconSort,
    LexiconWriteResult,
)
from lore.modules.languages.schemas import FamilyTree
from lore.modules.languages.service import Languages

LanguageIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Language id.")]
EntryIdPath = Annotated[str, Path(pattern=ID_PATTERN, description="Lexicon entry id.")]

router = APIRouter(tags=["languages"])


@router.get("/family-tree", name="family_tree")
def get_family_tree(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    dimension: Annotated[
        str | None,
        Query(pattern=ID_PATTERN, description="Languages of a dimension (and multiversal ones)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=2000, description="Languages at most.")] = 500,
) -> FamilyTree:
    """The language family graph: languages the request sees with the `descended_from` and
    `borrowed_from` links between them, and dialect edges to their parent languages."""
    return Languages(VaultContext(vault, session, registry), policy).family_tree(
        dimension=dimension, limit=limit
    )


# --- the lexicon ------------------------------------------------------------------------------


@router.get("/{language_id}/lexicon", name="lexicon_list")
def list_lexicon(
    *,
    language_id: LanguageIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    q: Annotated[
        str | None,
        Query(max_length=200, description="Start of a headword or romanization, or in a gloss."),
    ] = None,
    pos: Annotated[str | None, Query(max_length=100, description="A part of speech.")] = None,
    tag: Annotated[str | None, Query(max_length=100)] = None,
    sort: LexiconSort = "collation",
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> LexiconPage:
    """The language's lexicon, page by page: by its own alphabet (`collation`), by headword, or
    the most recently changed first (`recent`). Entries the request may not see are left out;
    ``404`` for a language it may not see."""
    lexicon = Lexicon(VaultContext(vault, session, registry), policy)
    return lexicon.page(language_id, q=q, pos=pos, tag=tag, sort=sort, cursor=cursor, limit=limit)


@router.post("/{language_id}/lexicon", name="lexicon_create", status_code=201)
def create_lexicon_entry(
    language_id: LanguageIdPath,
    body: LexiconEntryCreate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> LexiconWriteResult:
    """Add an entry (its collation key from the language's `alphabet_order`; an attestation
    period needs `timeline_id`)."""
    request_suppress(session, body.suppress)
    return Lexicon(VaultContext(vault, session, registry)).create(language_id, body)


@router.get("/lexicon/{entry_id}", name="lexicon_get")
def get_lexicon_entry(
    *,
    entry_id: EntryIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> LexiconEntryOut:
    """One entry (`lexiconRef` nodes and the entry drawer). ``404`` when the request may not see
    it or its language, or it is in the trash."""
    lexicon = Lexicon(VaultContext(vault, session, registry), policy)
    return entry_out(lexicon.entry(entry_id))


@router.patch("/lexicon/{entry_id}", name="lexicon_update")
def update_lexicon_entry(
    entry_id: EntryIdPath,
    body: LexiconEntryUpdate,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
) -> LexiconWriteResult:
    """Change an entry (revision required; `409 revision_conflict` when it changed meanwhile)."""
    request_suppress(session, body.suppress)
    return Lexicon(VaultContext(vault, session, registry)).update(entry_id, body)


@router.delete("/lexicon/{entry_id}", name="lexicon_delete")
def delete_lexicon_entry(
    entry_id: EntryIdPath,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    suppress: Annotated[
        SuppressIn | None, Body(description="Save anyway: findings to suppress.")
    ] = None,
) -> LexiconWriteResult:
    """Move an entry to the trash (undo restores it)."""
    request_suppress(session, suppress.suppress if suppress else None)
    return Lexicon(VaultContext(vault, session, registry)).delete(entry_id)


@router.post("/{language_id}/lexicon/import", name="lexicon_import")
def import_lexicon(
    *,
    language_id: LanguageIdPath,
    body: ImportIn,
    vault: WritableVaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    dry_run: Annotated[bool, Query(description="Only validate and report.")] = False,
) -> ImportReport:
    """Import entries from CSV (header row; `definitions` as `gloss1; gloss2`). All or nothing:
    with any problem nothing is created and `errors` lists them (row and column)."""
    lexicon = Lexicon(VaultContext(vault, session, registry))
    return import_csv(lexicon, lexicon.language(language_id), body, dry_run=dry_run)


@router.get(
    "/{language_id}/lexicon/export",
    name="lexicon_export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export_lexicon(
    *,
    language_id: LanguageIdPath,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
) -> Response:
    """The lexicon as CSV (the import's columns), entries the request may see, by alphabet."""
    lexicon = Lexicon(VaultContext(vault, session, registry), policy)
    text = export_csv(lexicon.visible_entries(language_id))
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="lexicon-{language_id}.csv"'},
    )
