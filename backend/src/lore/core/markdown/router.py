"""The Markdown export download (``docs/architecture/api.md`` §2, Vaults & settings;
``markdown-export.md``).

Author-only: readers (including ``?as_reader=true``) get ``404``. ``audience=readers`` exports what
readers see, ``audience=author`` everything (private content included)."""

import re
import tempfile
from collections.abc import Iterator
from typing import IO, Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from lore.core.api.deps import ModuleRegistryDep, PolicyDep, SessionDep, VaultDep
from lore.core.markdown.export import Audience, ZipSink, export_markdown
from lore.core.modules.spec import VaultContext

router = APIRouter(prefix="/vaults/{vault_id}", tags=["export"])

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
    "/export/markdown",
    name="markdown_export",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {"schema": _ZIP}}}},
)
def markdown_export(
    *,
    vault: VaultDep,
    session: SessionDep,
    registry: ModuleRegistryDep,
    policy: PolicyDep,
    audience: Annotated[
        Audience,
        Query(description="`readers`: what readers see (no private data); `author`: everything."),
    ] = "readers",
    calendar: Annotated[
        list[str] | None,
        Query(
            max_length=100,
            description="Calendars to show dates in first (per dimension, the first of its "
            "calendars listed; by default its default calendar).",
        ),
    ] = None,
) -> StreamingResponse:
    """The vault as a zip of Markdown notes for Obsidian and other Markdown tools: one note per
    entity with wikilinks, properties (fields, aliases, tags, dates in every calendar), facts,
    links and media files."""
    policy.require_author("The Markdown export isn't available to readers.")
    file = tempfile.SpooledTemporaryFile(max_size=16 * _CHUNK)  # noqa: SIM115 (closed by _chunks)
    try:
        sink = ZipSink(file)
        context = VaultContext(vault, session, registry)
        export_markdown(context, sink, audience=audience, calendars=calendar or ())
        sink.close()
    except BaseException:
        file.close()
        raise
    name = _UNSAFE.sub("-", vault.info.folder).strip("-") or "vault"
    suffix = "" if audience == "readers" else "-private"
    return StreamingResponse(
        _chunks(file),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}-markdown{suffix}.zip"'},
    )
