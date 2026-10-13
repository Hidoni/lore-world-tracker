"""CSV import and export of a lexicon (``docs/modules/languages.md``, API).

Columns map to fields by header (or an explicit mapping). ``definitions`` holds glosses separated
by ``;``, ``tags`` by ``;`` or ``,``, ``etymology`` its text. An import is all or nothing: any
problem refuses every row, and a dry run only reports.
"""

import csv
import io
from collections.abc import Iterable

from pydantic import ValidationError

from lore.core.entities.models import Entity
from lore.core.search.indexer import SearchIndexer
from lore.core.time.propagate import TimeWriter
from lore.modules.languages.lexicon import DOC_TYPE, Lexicon
from lore.modules.languages.lexicon_schemas import (
    Definition,
    Etymology,
    ImportIn,
    ImportProblem,
    ImportReport,
    LexiconEntryCreate,
)
from lore.modules.languages.models import LexiconEntry

FIELDS = (
    "headword",
    "romanization",
    "pronunciation",
    "part_of_speech",
    "definitions",
    "tags",
    "etymology",
)
MAX_ROWS = 10_000


def _split(value: str, separators: str) -> list[str]:
    parts = [value]
    for separator in separators:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [part.strip() for part in parts if part.strip()]


def _mapping(
    headers: list[str], columns: dict[str, str] | None
) -> tuple[dict[str, str], list[ImportProblem]]:
    problems: list[ImportProblem] = []
    if columns is None:
        mapping = {h: h.strip().lower() for h in headers if h.strip().lower() in FIELDS}
    else:
        mapping = {}
        for header, target in columns.items():
            if header not in headers:
                problems.append(ImportProblem(row=0, column=header, message="No such column."))
            elif target and target not in FIELDS:
                problems.append(
                    ImportProblem(row=0, column=header, message=f"Unknown field {target!r}.")
                )
            elif target:
                mapping[header] = target
    if "headword" not in mapping.values():
        problems.append(ImportProblem(row=0, column=None, message="No column for the headword."))
    return mapping, problems


def import_csv(
    lexicon: Lexicon, language: Entity, data: ImportIn, *, dry_run: bool
) -> ImportReport:
    """Validate every row; unless ``dry_run`` or a problem, create the entries (one write)."""
    reader = csv.DictReader(io.StringIO(data.csv.lstrip("﻿")))
    headers = list(reader.fieldnames or [])
    mapping, problems = _mapping(headers, data.columns)
    entries: list[LexiconEntryCreate] = []
    rows = 0
    if not problems:
        for number, row in enumerate(reader, start=1):
            rows = number
            if number > MAX_ROWS:
                problems.append(
                    ImportProblem(row=number, column=None, message=f"More than {MAX_ROWS} rows.")
                )
                break
            values = {field: (row.get(header) or "").strip() for header, field in mapping.items()}
            if not any(values.values()):
                continue  # a blank line
            try:
                entries.append(
                    LexiconEntryCreate(
                        headword=values.get("headword", ""),
                        romanization=values.get("romanization") or None,
                        pronunciation=values.get("pronunciation") or None,
                        part_of_speech=values.get("part_of_speech") or None,
                        definitions=[
                            Definition(gloss=gloss)
                            for gloss in _split(values.get("definitions", ""), ";")
                        ],
                        tags=_split(values.get("tags", ""), ";,"),
                        etymology=Etymology(text=values.get("etymology") or None),
                    )
                )
            except ValidationError as error:
                for item in error.errors():
                    field = str(item["loc"][0]) if item["loc"] else None
                    header = next((h for h, f in mapping.items() if f == field), field)
                    problems.append(ImportProblem(row=number, column=header, message=item["msg"]))
    report = ImportReport(rows=rows, created=0, columns=mapping, errors=problems)
    if dry_run or problems:
        return report
    created = [lexicon.add(language, entry) for entry in entries]
    if created:
        SearchIndexer(lexicon.context).index_documents(DOC_TYPE, [entry.id for entry in created])
    TimeWriter(lexicon.context).propagate()
    report.created = len(created)
    report.affected = lexicon.affected(created) if created else None
    return report


def export_csv(entries: Iterable[LexiconEntry]) -> str:
    """The entries as CSV, in the import's columns (glosses and tags joined with ``; ``)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(FIELDS)
    for entry in entries:
        writer.writerow(
            [
                entry.headword,
                entry.romanization or "",
                entry.pronunciation or "",
                entry.part_of_speech or "",
                "; ".join(
                    str(d.get("gloss", "")) for d in entry.definitions if isinstance(d, dict)
                ),
                "; ".join(entry.tags),
                (entry.etymology or {}).get("text") or "",
            ]
        )
    return out.getvalue()
