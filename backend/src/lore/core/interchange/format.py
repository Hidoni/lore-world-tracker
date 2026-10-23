"""The interchange format (``docs/architecture/interchange.md``): the document, its envelope
upgraders, the column codec and the archive.

A document holds rows of the vault's authored tables in the schema of ``schema_revision``,
column by column: JSON columns as JSON, moments (``SortableBigInt``) as decimal strings,
booleans as booleans, everything else as SQLite stores it. ``format_version`` covers the
envelope; ``UPGRADERS[n]`` turns a version ``n`` document into version ``n + 1`` (frozen once
released). Rows from an older schema are brought to this app's head by its migrations
(``lore.core.interchange.importer``).
"""

import hashlib
import io
import json
import re
import stat
import zipfile
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import JSON, Boolean, Column, Table
from sqlalchemy.types import TypeDecorator

from lore.chronology.numbers import NumberError, from_sortable_key, sortable_key
from lore.core.db.types import SortableBigInt
from lore.core.errors import ConflictError, InvalidInputError

FORMAT: Final = "lore-interchange"
FORMAT_VERSION: Final = 1
DOCUMENT_NAME: Final = "lore-interchange.json"
FILES_DIR: Final = "files"
ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FILE_NAME = re.compile(r"^files/[a-z][a-z0-9_]*/[0-9A-Za-z._-]{1,200}$")
_MOMENT = re.compile(r"^(0|[1-9][0-9]*)$")
_CHUNK = 1 << 20

UPGRADERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

type Audience = Literal["author", "readers"]
type IdMode = Literal["remap", "keep"]
type ConflictMode = Literal["fail", "overwrite"]


class InvalidInterchangeError(InvalidInputError):
    """The file isn't a usable interchange document (or is unsafe to extract)."""

    code = "invalid_interchange"
    title = "Invalid interchange file"


class InterchangeNewerError(ConflictError):
    code = "interchange_newer_than_app"
    title = "Written by a newer app"


class InterchangeConflictError(ConflictError):
    """Rows of the document clash with the vault's (``context.conflicts``)."""

    code = "interchange_conflict"
    title = "Import conflicts"


class InterchangeModulesError(ConflictError):
    """The document holds records of modules the vault doesn't have enabled
    (``context.modules``)."""

    code = "interchange_modules_disabled"
    title = "Modules not enabled"


# --- the document ---------------------------------------------------------------------------------


class Source(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    vault_id: str
    name: str


class Scope(BaseModel):
    """``vault``: the whole vault; ``dimension``: one dimension (``dimension_id``, its
    ``name``), multiversal entities it refers to listed in ``references``."""

    model_config = ConfigDict(extra="allow", frozen=True)

    kind: Literal["vault", "dimension"]
    dimension_id: str | None = Field(default=None, pattern=ID_PATTERN)
    name: str | None = None


class Reference(BaseModel):
    """An entity the document refers to without holding it (a multiversal entity of a
    dimension export): matched in the target vault by id, else by kind and name."""

    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(pattern=ID_PATTERN)
    kind: str
    name: str


class InterchangeDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    format: Literal["lore-interchange"]
    format_version: Literal[1]
    app_version: str
    schema_revision: str
    exported_at: datetime
    source: Source
    audience: Audience
    scope: Scope
    modules: list[str] = Field(description="The modules enabled in the source vault.")
    references: list[Reference] = Field(default_factory=list)
    tables: dict[str, list[dict[str, Any]]]
    files: dict[str, str] = Field(
        default_factory=dict, description="sha256 (hex) of every file next to the document."
    )


def upgrade_document(raw: Any) -> InterchangeDocument:
    """A parsed document at this app's format version (``InvalidInterchangeError`` if it can't
    be read, ``InterchangeNewerError`` if a newer app wrote it)."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise InvalidInterchangeError("The file isn't a Lore interchange document.")
    version = raw.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise InvalidInterchangeError("The document has no valid format_version.")
    if version > FORMAT_VERSION:
        raise InterchangeNewerError(
            f"The document's format {version} is newer than this app's ({FORMAT_VERSION}).",
            context={"format_version": version},
        )
    while version < FORMAT_VERSION:
        raw = UPGRADERS[version](raw)
        version += 1
    try:
        return InterchangeDocument.model_validate(raw)
    except ValidationError as exc:
        raise InvalidInterchangeError(
            "The document doesn't match the interchange format.",
            errors=[
                {
                    "path": "/" + "/".join(str(part) for part in error["loc"]),
                    "code": error["type"],
                    "message": error["msg"],
                }
                for error in exc.errors()[:20]
            ],
        ) from exc


# --- the column codec -----------------------------------------------------------------------------

type Codec = Literal["json", "moment", "bool", "plain"]


def codec(column: Column[Any]) -> Codec:
    """How a column's raw stored value is written in a document."""
    kind = column.type
    if isinstance(kind, SortableBigInt):
        return "moment"
    implementation = kind.impl_instance if isinstance(kind, TypeDecorator) else kind
    if isinstance(kind, JSON) or isinstance(implementation, JSON):
        return "json"
    if isinstance(kind, Boolean):
        return "bool"
    return "plain"


def encode_value(kind: Codec, raw: Any) -> Any:
    """A raw stored value as a document holds it."""
    if raw is None:
        return None
    if kind == "json":
        return json.loads(raw) if isinstance(raw, str) else raw
    if kind == "moment":
        return str(from_sortable_key(raw))
    if kind == "bool":
        return bool(raw)
    return raw


def encode_row(table: Table, raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: encode_value(codec(table.c[name]), value) if name in table.c else value
        for name, value in raw.items()
    }


def decode_value(column: Column[Any], value: Any, where: str) -> Any:
    """A document's value as SQLite stores it; ``where`` names it in errors."""
    kind = codec(column)
    if kind == "json":
        if value is None:
            return None if column.nullable else "null"
        return json.dumps(value)
    if value is None:
        return None
    if kind == "moment":
        if not isinstance(value, str) or not _MOMENT.match(value):
            raise InvalidInterchangeError(f"{where} must be a decimal string.")
        try:
            return sortable_key(int(value))
        except (NumberError, ValueError) as exc:
            raise InvalidInterchangeError(f"{where} can't be stored: {exc}") from exc
    if kind == "bool":
        if not isinstance(value, bool):
            raise InvalidInterchangeError(f"{where} must be a boolean.")
        return int(value)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InvalidInterchangeError(f"{where} must be a string or a number.")
    return value


def decode_row(
    table: Table,
    row: Mapping[str, Any],
    where: str,
    codecs: Mapping[str, Column[Any]] | None = None,
) -> dict[str, Any]:
    """A document's row as SQLite stores it. Every column of ``table`` must be there, and
    nothing else; ``codecs``: the columns whose types decode them, by name (default:
    ``table``'s own)."""
    if not isinstance(row, Mapping):
        raise InvalidInterchangeError(f"{where} must be an object.")
    names = list(table.c.keys())
    if set(row) != set(names):
        missing, unknown = sorted(set(names) - set(row)), sorted(set(row) - set(names))
        raise InvalidInterchangeError(
            f"{where} doesn't have the columns of {table.name}.",
            context={"missing": missing, "unknown": unknown},
        )
    columns = codecs if codecs is not None else table.c
    return {name: decode_value(columns[name], row[name], f"{where}.{name}") for name in names}


# --- the archive ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Limits:
    """Caps applied while reading an archive (zip bombs, file-count exhaustion)."""

    max_files: int = 200_000
    max_bytes: int = 64 * 1024**3


DEFAULT_LIMITS = Limits()


@dataclass
class Archive:
    """A read archive: the document and its files, extracted (archive name → path)."""

    document: InterchangeDocument
    files: dict[str, Path] = field(default_factory=dict)


def file_name(table: str, row_id: str) -> str:
    return f"{FILES_DIR}/{table}/{row_id}"


def write_archive(out: IO[bytes], document: Mapping[str, Any], files: Mapping[str, Path]) -> None:
    """A zip with the document and its files (whose checksums the document lists)."""
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open(DOCUMENT_NAME, "w", force_zip64=True) as entry:
            text = io.TextIOWrapper(entry, encoding="utf-8")
            json.dump(document, text, ensure_ascii=False, separators=(",", ":"))
            text.flush()
            text.detach()
        for name, path in sorted(files.items()):
            archive.write(path, name)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def read_archive(source: IO[bytes], staging: Path, limits: Limits = DEFAULT_LIMITS) -> Archive:
    """Read an interchange zip (its files are extracted into ``staging``, which must exist), or
    a bare document (JSON, no files). Raises ``InvalidInterchangeError``; the caller removes
    ``staging``."""
    source.seek(0)
    if not zipfile.is_zipfile(source):
        source.seek(0)
        document = _parse(_read_limited(source, limits.max_bytes))
        if document.files:
            raise InvalidInterchangeError(
                "The document lists files: import the zip it came in.",
                context={"missing": sorted(document.files)[:20]},
            )
        return Archive(document)
    source.seek(0)
    try:
        with zipfile.ZipFile(source) as archive:
            return _extract(archive, staging, limits)
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise InvalidInterchangeError("The file isn't a valid zip (or is damaged).") from exc


def _read_limited(file: IO[bytes], limit: int) -> bytes:
    data = file.read(limit + 1)
    if len(data) > limit:
        raise InvalidInterchangeError(f"The document is larger than {limit} bytes.")
    return data


def _parse(data: bytes) -> InterchangeDocument:
    try:
        raw = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidInterchangeError("The document isn't valid JSON.") from exc
    return upgrade_document(raw)


def _extract(archive: zipfile.ZipFile, staging: Path, limits: Limits) -> Archive:
    entries = archive.infolist()
    if len(entries) > limits.max_files:
        raise InvalidInterchangeError(f"The zip holds more than {limits.max_files} files.")
    try:
        with archive.open(DOCUMENT_NAME) as stream:
            document = _parse(_read_limited(stream, limits.max_bytes))
    except KeyError as exc:
        raise InvalidInterchangeError(f"The zip has no {DOCUMENT_NAME}.") from exc
    expected = dict(document.files)
    for name in expected:
        if not _FILE_NAME.match(name):
            raise InvalidInterchangeError(f"Unsafe file name in the document: {name!r}.")
    files: dict[str, Path] = {}
    total = 0
    for entry in entries:
        if entry.is_dir() or entry.filename == DOCUMENT_NAME:
            continue
        _check_entry(entry, expected, files)
        target = staging / f"{len(files) + 1}"
        total += _copy(archive, entry, target, expected[entry.filename], limits.max_bytes - total)
        files[entry.filename] = target
    missing = sorted(set(expected) - set(files))
    if missing:
        raise InvalidInterchangeError(
            "Files listed in the document are missing.", context={"missing": missing[:20]}
        )
    return Archive(document, files)


def _check_entry(
    entry: zipfile.ZipInfo, expected: Mapping[str, str], seen: Mapping[str, Path]
) -> None:
    name = entry.filename
    if stat.S_ISLNK(entry.external_attr >> 16):
        raise InvalidInterchangeError(f"Symbolic link in the zip: {name!r}.")
    if name not in expected:
        raise InvalidInterchangeError(f"Unexpected file in the zip: {name!r}.")
    if name in seen:
        raise InvalidInterchangeError(f"Duplicate entry in the zip: {name!r}.")


def _copy(
    archive: zipfile.ZipFile, entry: zipfile.ZipInfo, target: Path, checksum: str, budget: int
) -> int:
    """Extract one file of at most ``budget`` bytes (counted as written: declared sizes can
    lie), checking its checksum; returns its size."""
    digest = hashlib.sha256()
    total = 0
    with archive.open(entry) as data, target.open("wb") as out:
        while chunk := data.read(_CHUNK):
            total += len(chunk)
            if total > budget:
                raise InvalidInterchangeError("The archive expands to more bytes than allowed.")
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != checksum:
        raise InvalidInterchangeError(
            f"Checksum mismatch for {entry.filename!r}: the file is corrupt."
        )
    return total
