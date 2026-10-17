"""The Markdown / Obsidian export (``docs/architecture/markdown-export.md``): a vault as a folder
of Markdown notes, one per entity, with ``[[wikilinks]]``, YAML properties and dates in every
calendar, for Obsidian or any other Markdown tool. One-way: nothing reads it back.

Everything is read through the services with the export's ``VisibilityPolicy``, so the readers'
export holds exactly what a reader may see (``READER``: private entities, fields, blocks, aliases,
facts and links left out, links to hidden entities kept as plain text), and the author's holds
everything (private blocks become ``[!private]`` callouts). Modules add their part through
``ModuleSpec.markdown_contributors`` (media copies files and renders images).

Layout: ``<dimension>/<dimension>.md`` and ``<dimension>/<kind plural>/<name>.md``, multiversal
entities under ``Multiverse/<kind plural>/``, media under ``_media/``, and ``lore-export.json``
(the manifest). Note names are unique in the whole export (Obsidian resolves ``[[name]]`` by file
name): a name used twice gets the kind, then a number.
"""

import json
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Any, Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select

from lore import __version__
from lore.chronology.schema import SlotRef, TimePoint
from lore.core.entities.models import Entity
from lore.core.entities.schemas import EntityOut
from lore.core.entities.service import EntityService
from lore.core.errors import ConflictError, LoreError, NotFoundError
from lore.core.facts.schemas import FactOut
from lore.core.facts.service import Facts
from lore.core.links.service import LinkService
from lore.core.markdown.render import (
    Inline,
    NodeRenderer,
    escape,
    file_name,
    frontmatter,
    tag_name,
    to_markdown,
    wikilink,
)
from lore.core.modules.service import enabled_modules
from lore.core.modules.spec import VaultContext
from lore.core.registry.types import FieldDef
from lore.core.richtext.handlers import Node
from lore.core.time.batch import Lens, display
from lore.core.time.calendars import AbsoluteLens, lens
from lore.core.time.dimensions import DIMENSION
from lore.core.time.events import EVENT
from lore.core.time.fields import ENTITY_FIELD
from lore.core.time.models import Calendar, Dimension, Timeline
from lore.core.time.resolve import Resolution, Resolver
from lore.core.time.specs import ABSOLUTE_CALENDAR_ID
from lore.core.visibility import AUTHOR, READER, VisibilityPolicy

if TYPE_CHECKING:
    from lore.core.vaults.manager import VaultManager

FORMAT_VERSION = 1
MANIFEST_NAME = "lore-export.json"
MEDIA_FOLDER = "_media"
MULTIVERSE = "Multiverse"
ABSOLUTE_NAME = "Absolute"
NOTE = ".md"

type Audience = Literal["readers", "author"]
# A field value of a module's type as a property (the media module's ``media`` fields).
type FieldRenderer = Callable[[Any], Any]


class MarkdownExportError(LoreError):
    code = "markdown_export_failed"
    status = 409
    title = "Markdown export failed"


def policy_for(audience: Audience) -> VisibilityPolicy:
    return READER if audience == "readers" else AUTHOR


# --- where the files go -------------------------------------------------------------------------


class ExportSink(Protocol):
    def write(self, path: str, data: bytes) -> None: ...

    def copy(self, path: str, source: Path) -> None: ...


@dataclass
class FolderSink:
    """Files written into a folder (created; refused unless empty or missing)."""

    root: Path

    def __post_init__(self) -> None:
        if self.root.exists() and (not self.root.is_dir() or any(self.root.iterdir())):
            raise MarkdownExportError(f"{self.root} is not an empty folder")
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, path: str) -> Path:
        target = self.root.joinpath(*PurePosixPath(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write(self, path: str, data: bytes) -> None:
        self._target(path).write_bytes(data)

    def copy(self, path: str, source: Path) -> None:
        self._target(path).write_bytes(source.read_bytes())


@dataclass
class ZipSink:
    """Files written into a zip archive (``file``: an open binary file)."""

    file: IO[bytes]
    archive: zipfile.ZipFile = field(init=False)

    def __post_init__(self) -> None:
        self.archive = zipfile.ZipFile(self.file, "w", compression=zipfile.ZIP_DEFLATED)

    def write(self, path: str, data: bytes) -> None:
        self.archive.writestr(path, data)

    def copy(self, path: str, source: Path) -> None:
        self.archive.write(source, path)

    def close(self) -> None:
        self.archive.close()


# --- what modules plug in -----------------------------------------------------------------------


@dataclass
class MarkdownExport:
    """What a module's ``markdown_contributors`` get, before any note is written: the vault
    (``context``) read with the export's ``policy``, the ``sink`` to add files to (``claim`` a
    path first), and registries for how the module's content renders: rich-text ``nodes`` by
    node type, ``field_values`` by field type (as a property), and ``cover`` (an entity's cover
    media id as the Markdown shown above its body, or None)."""

    context: VaultContext
    policy: VisibilityPolicy
    sink: ExportSink
    nodes: dict[str, NodeRenderer] = field(default_factory=dict)
    field_values: dict[str, FieldRenderer] = field(default_factory=dict)
    cover: Callable[[str], str | None] | None = None
    claimed: set[str] = field(default_factory=set)

    def claim(self, folder: str, name: str) -> str:
        """A free path ``<folder>/<name>`` (names compared ignoring case: some file systems do),
        the stem numbered when taken."""
        stem, dot, suffix = name.rpartition(".")
        if not dot or not stem:
            stem, suffix = name, ""
        candidate, n = name, 1
        while f"{folder}/{candidate}".casefold() in self.claimed:
            n += 1
            candidate = f"{stem} ({n}).{suffix}" if suffix else f"{stem} ({n})"
        path = f"{folder}/{candidate}"
        self.claimed.add(path.casefold())
        return path


@dataclass(frozen=True)
class MarkdownExportInfo:
    vault_id: str
    audience: Audience
    notes: int
    files: int


# --- dates --------------------------------------------------------------------------------------


@dataclass
class _Dates:
    """Moments shown in every calendar of their dimension the policy sees: the primary one first
    (the one chosen for the dimension, else its default calendar, else Absolute), then the others
    by name, Absolute last."""

    context: VaultContext
    policy: VisibilityPolicy
    chosen: Sequence[str]
    _lenses: dict[str, list[tuple[str, Lens]]] = field(default_factory=dict)
    _stored: dict[str, Resolver] = field(default_factory=dict)
    _visible: dict[str, Resolver] = field(default_factory=dict)

    def lenses(self, dimension_id: str) -> list[tuple[str, Lens]]:
        if dimension_id in self._lenses:
            return self._lenses[dimension_id]
        session = self.context.session
        rows = session.execute(
            select(Calendar.entity_id, Entity.name)
            .join(Entity, Entity.id == Calendar.entity_id)
            .where(
                Calendar.dimension_id == dimension_id,
                Entity.deleted_at.is_(None),
                *self.policy.entities(Entity),
            )
            .order_by(Entity.sort_name, Entity.id)
        ).all()
        compiled: dict[str, tuple[str, Lens]] = {}
        for calendar_id, name in rows:
            try:
                compiled[calendar_id] = (name, lens(self.context, dimension_id, calendar_id))
            except ConflictError, NotFoundError:  # it doesn't compile
                continue
        default = session.scalar(
            select(Dimension.default_calendar_id).where(Dimension.entity_id == dimension_id)
        )
        primary = next((c for c in self.chosen if c in compiled), None)
        if primary is None and default in compiled:
            primary = default
        ordered = [compiled[primary]] if primary is not None else []
        ordered += [found for key, found in compiled.items() if key != primary]
        absolute = (ABSOLUTE_NAME, lens(self.context, dimension_id, ABSOLUTE_CALENDAR_ID))
        found = [absolute, *ordered] if primary is None else [*ordered, absolute]
        self._lenses[dimension_id] = found
        return found

    def _resolver(self, dimension_id: str, *, stored: bool) -> Resolver:
        # Stored moments are shown to anyone who sees their record (only specs are redacted, as
        # in ``EventTimes``); a date in rich text resolves through what the policy sees.
        cache = self._stored if stored else self._visible
        if dimension_id not in cache:
            policy = AUTHOR if stored else self.policy
            cache[dimension_id] = Resolver(self.context, dimension_id, policy=policy)
        return cache[dimension_id]

    def shown(self, dimension_id: str, resolution: Resolution) -> dict[str, str]:
        """A resolution in each calendar (name -> text), primary first; empty without a moment."""
        if resolution.t is None:
            return {}
        out: dict[str, str] = {}
        for name, calendar in self.lenses(dimension_id):
            text = display(calendar, resolution)
            if text is not None:
                out.setdefault(name, text)
        return out

    def slot(
        self, dimension_id: str | None, record_type: str, record_id: str, slot: str
    ) -> dict[str, str]:
        if dimension_id is None:
            return {}
        resolver = self._resolver(dimension_id, stored=True)
        return self.shown(dimension_id, resolver.slot(record_type, record_id, slot))

    def time_ref(self, dimension_id: str | None, attrs: Mapping[str, Any]) -> str:
        """A ``timeRef`` (already filtered for the policy) in the primary calendar."""
        if dimension_id is None or attrs.get("hidden_ref"):
            return "a date"
        resolver = self._resolver(dimension_id, stored=False)
        try:
            if attrs.get("ref") is not None:
                ref = SlotRef.model_validate(attrs["ref"])
                resolution = resolver.slot(ref.type, ref.id, ref.slot)
            else:
                resolution = resolver.resolve(TimePoint.model_validate(attrs.get("timePoint")))
        except ValidationError, LoreError, KeyError:
            return "a date"
        return next(iter(self.shown(dimension_id, resolution).values()), "a date")


def _primary(dates: Mapping[str, str]) -> str | None:
    return next(iter(dates.values()), None)


def _duration(value: Any, base_plural: str | None) -> str:
    if not isinstance(value, Mapping):
        return str(value)
    if value.get("kind") == "base":
        return f"{value.get('units')} {base_plural or 'base units'}"
    amounts = value.get("amounts") or {}
    sign = "-" if value.get("sign") == -1 else ""
    return sign + ", ".join(f"{n} {level}" for level, n in amounts.items())


# --- the export ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Note:
    entity_id: str
    path: str  # "<folder>/<name>.md"

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).stem


class _Exporter:
    def __init__(
        self,
        context: VaultContext,
        policy: VisibilityPolicy,
        sink: ExportSink,
        calendars: Sequence[str],
    ) -> None:
        self.context = context
        self.session = context.session
        self.policy = policy
        self.sink = sink
        self.entities = EntityService(context, policy)
        self.links = LinkService(self.session, context.registry, policy, context.vault)
        self.facts = Facts(context, policy)
        self.dates = _Dates(context, policy, calendars)
        self.export = MarkdownExport(context, policy, sink)
        self.notes: dict[str, _Note] = {}
        self._timelines: dict[str, tuple[str, bool]] = {}

    # --- setup ----------------------------------------------------------------------------------

    def contribute(self) -> None:
        enabled = enabled_modules(self.session, self.context.registry)
        for module in self.context.registry.modules:
            if module.id in enabled:
                for contributor in module.markdown_contributors:
                    contributor(self.export)

    def place(self) -> list[Entity]:
        """Every entity the policy shows (of a kind an enabled module offers), with its note's
        path; returned in export order."""
        rows = list(
            self.session.scalars(
                select(Entity)
                .where(
                    Entity.deleted_at.is_(None),
                    Entity.kind.in_(self.entities.kinds),
                    *self.policy.entities(Entity),
                )
                .order_by(Entity.sort_name, Entity.id)
            )
        )
        dimensions = [row for row in rows if row.kind == DIMENSION]
        folders: dict[str | None, str] = {}
        taken = {MEDIA_FOLDER.casefold()}
        for owner, name in [(None, MULTIVERSE), *((d.id, d.name) for d in dimensions)]:
            folder, n = file_name(name), 1
            while folder.casefold() in taken:
                n += 1
                folder = f"{file_name(name)} ({n})"
            taken.add(folder.casefold())
            folders[owner] = folder
        names: dict[str, int] = {}
        for row in rows:
            key = file_name(row.name).casefold()
            names[key] = names.get(key, 0) + 1
        used: set[str] = set()
        for row in rows:
            kind = self.entities.kinds[row.kind]
            base = file_name(row.name)
            name = base if names[base.casefold()] == 1 else f"{base} ({kind.definition.label})"
            n = 1
            while name.casefold() in used:
                n += 1
                name = f"{base} ({kind.definition.label} {n})"
            used.add(name.casefold())
            if row.kind == DIMENSION:
                folder = folders[row.id]
            else:
                home = folders.get(row.dimension_id, folders[None])
                folder = f"{home}/{file_name(kind.definition.plural)}"
            self.notes[row.id] = _Note(row.id, f"{folder}/{name}{NOTE}")
        return rows

    # --- one note -------------------------------------------------------------------------------

    def link_to(self, entity_id: str | None, label: str | None = None) -> str | None:
        note = self.notes.get(entity_id or "")
        return None if note is None else wikilink(note.name, label)

    def inline(self, dimension_id: str | None) -> Inline:
        handlers = self.entities.richtext

        def fallback(node: Node) -> str:
            handler = handlers.get(str(node.get("type")))
            return handler.extract_text(node) if handler else ""

        return Inline(
            entity_link=self.link_to,
            time_ref=lambda attrs: self.dates.time_ref(dimension_id, attrs),
            nodes=self.export.nodes,
            fallback_text=fallback,
        )

    def timeline(self, timeline_id: str) -> tuple[str, bool]:
        """A timeline's name and whether it is its dimension's prime timeline."""
        if timeline_id not in self._timelines:
            row = self.session.execute(
                select(Entity.name, Timeline.is_prime)
                .join(Timeline, Timeline.entity_id == Entity.id)
                .where(Entity.id == timeline_id)
            ).one_or_none()
            self._timelines[timeline_id] = ("", True) if row is None else (row[0], row[1])
        return self._timelines[timeline_id]

    def _header(self, out: EntityOut, label: str) -> dict[str, Any]:
        """The properties every note has: id, kind, dimension, parent, aliases, tags, summary."""
        properties: dict[str, Any] = {"lore_id": out.id, "kind": label}
        if (dimension := self.link_to(out.dimension_id)) is not None:
            properties["dimension"] = dimension
        if (parent := self.link_to(out.parent_id)) is not None:
            properties["parent"] = parent
        if aliases := [alias.alias for alias in out.aliases]:
            properties["aliases"] = aliases
        if tags := [tag for t in out.tags if (tag := tag_name(t.name)) is not None]:
            properties["tags"] = list(dict.fromkeys(tags))
        if out.summary:
            properties["summary"] = out.summary
        if out.visibility != "public":
            properties["visibility"] = out.visibility
        return properties

    def write(self, entity: Entity) -> None:
        out = self.entities.to_out(entity)
        kind = self.entities.kinds[entity.kind]
        active = self.entities.kind_fields(kind).active
        properties = self._header(out, kind.definition.label)
        all_dates: dict[str, dict[str, str]] = {}
        if entity.kind == EVENT:
            self._event(entity, out, properties, all_dates)
        sections: list[str] = []
        for key, value in out.fields.items():
            definition = active.get(key)
            if definition is None or value is None or value in ("", []):
                continue
            if definition.type == "rich_text":
                text = to_markdown(value, self.inline(entity.dimension_id))
                if text:
                    sections.append(f"## {escape(definition.label)}\n\n{text}")
                continue
            properties[key] = self._value(entity, definition, value, all_dates)
        if all_dates and entity.dimension_id and len(self.dates.lenses(entity.dimension_id)) > 1:
            properties["dates"] = all_dates
        parts = [frontmatter(properties).rstrip("\n")]
        if out.cover_media_id is not None and self.export.cover is not None:
            cover = self.export.cover(out.cover_media_id)
            if cover:
                parts.append(cover)
        body = to_markdown(out.body, self.inline(entity.dimension_id))
        if body:
            parts.append(body)
        parts.extend(sections)
        facts = self._facts(entity, out, active)
        if facts:
            parts.append("## Facts\n\n" + "\n".join(facts))
        links = self._links(entity)
        if links:
            parts.append("## Links\n\n" + "\n".join(links))
        text = "\n\n".join(parts) + "\n"
        self.sink.write(self.notes[entity.id].path, text.encode("utf-8"))

    def _event(
        self,
        entity: Entity,
        out: EntityOut,
        properties: dict[str, Any],
        all_dates: dict[str, dict[str, str]],
    ) -> None:
        ext = out.ext or {}
        for slot in ("start", "end"):
            if slot == "end" and (ext.get("end") or {}).get("kind") == "unknown":
                properties["end"] = "?"
                continue
            shown = self.dates.slot(entity.dimension_id, EVENT, entity.id, slot)
            if shown:
                properties[slot] = _primary(shown)
                all_dates[slot] = shown
        for key in ("importance", "category"):
            if ext.get(key) is not None:
                properties[key] = ext[key]
        if ext.get("recurrence") is not None:
            properties["recurring"] = True

    def _value(
        self,
        entity: Entity,
        definition: FieldDef,
        value: Any,
        all_dates: dict[str, dict[str, str]],
    ) -> Any:
        if definition.multiple and isinstance(value, list):
            if definition.type == "time_point":
                shown = []
                for index, _item in enumerate(value):
                    slot = f"{definition.key}.{index}"
                    dates = self.dates.slot(entity.dimension_id, ENTITY_FIELD, entity.id, slot)
                    if dates:
                        shown.append(_primary(dates))
                        all_dates[slot] = dates
                return shown
            return [self._one(entity.dimension_id, definition, item) for item in value]
        if definition.type == "time_point":
            dates = self.dates.slot(entity.dimension_id, ENTITY_FIELD, entity.id, definition.key)
            if dates:
                all_dates[definition.key] = dates
            return _primary(dates)
        return self._one(entity.dimension_id, definition, value)

    def _one(  # noqa: PLR0911 (one case per field type)
        self,
        dimension_id: str | None,
        definition: FieldDef,
        value: Any,
    ) -> Any:
        """A (non-time-point) field value as a property."""
        match definition.type:
            case "boolean":
                return bool(value)
            case "integer":
                number = int(value)
                return number if abs(number) < 2**53 else str(number)
            case "enum":
                return self._option(definition, value)
            case "multi_enum":
                return [self._option(definition, v) for v in value or ()]
            case "measurement" if isinstance(value, Mapping):
                return f"{value.get('value')} {value.get('unit')}".strip()
            case "duration":
                return _duration(value, self._base_plural(dimension_id))
            case _:
                renderer = self.export.field_values.get(definition.type)
                if renderer is not None:
                    return renderer(value)
                if isinstance(value, str | int | float | bool):
                    return value
                return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _option(definition: FieldDef, key: Any) -> str:
        return next((o.label for o in definition.options if o.key == key), str(key))

    def _base_plural(self, dimension_id: str | None) -> str | None:
        if dimension_id is None:
            return None
        found = lens(self.context, dimension_id, ABSOLUTE_CALENDAR_ID)
        return found.base_unit.plural if isinstance(found, AbsoluteLens) else None

    def _facts(self, entity: Entity, out: EntityOut, active: Mapping[str, FieldDef]) -> list[str]:
        lines = []
        for fact in self.facts.of_entity(entity.id).items:
            timeline_dimension = self.session.scalar(
                select(Timeline.dimension_id).where(Timeline.entity_id == fact.timeline_id)
            )
            if fact.field_key == "core.exists":
                what = "**Exists**"
            elif fact.field_key == "core.name":
                what = f"**Name**: {escape(str(fact.value))}"
            else:
                definition = active.get(fact.field_key)
                if definition is None:
                    continue
                value = self._fact_value(fact, definition, timeline_dimension)
                what = f"**{escape(definition.label)}**: {value}"
            when = self._period(timeline_dimension, "fact", fact.id)
            name, prime = self.timeline(fact.timeline_id)
            extra = [] if prime else [f"in {escape(name)}"]
            if (source := self.link_to(fact.source_event_id)) is not None:
                extra.append(f"caused by {source}")
            if fact.note:
                extra.append(escape(fact.note))
            lines.append(f"- {what}" + "".join(f" · {part}" for part in [when, *extra] if part))
        return lines

    def _fact_value(self, fact: FactOut, definition: FieldDef, dimension_id: str | None) -> str:
        if definition.type == "time_point":
            dates = self.dates.slot(dimension_id, ENTITY_FIELD, fact.entity_id, f"fact:{fact.id}")
            return escape(_primary(dates) or "a date")
        if definition.type == "rich_text":
            return to_markdown(fact.value, self.inline(dimension_id)).replace("\n", " ")
        value = self._one(dimension_id, definition, fact.value)
        if isinstance(value, list):
            return escape(", ".join(str(v) for v in value))
        if isinstance(value, bool):
            return "yes" if value else "no"
        return escape(str(value))

    def _period(self, dimension_id: str | None, record_type: str, record_id: str) -> str:
        start = _primary(self.dates.slot(dimension_id, record_type, record_id, "valid_from"))
        end = _primary(self.dates.slot(dimension_id, record_type, record_id, "valid_to"))
        if start is None and end is None:
            return ""
        if end is None:
            return f"from {escape(start or '')}"
        if start is None:
            return f"until {escape(end)}"
        return f"from {escape(start)} until {escape(end)}"

    def _links(self, entity: Entity) -> list[str]:
        lines = []
        for item in self.links.entity_links(entity.id).items:
            other = self.link_to(item.other.id)
            if other is None:
                continue
            line = f"- **{escape(item.label)}**: {other}"
            if item.link.role:
                line += f" ({escape(item.link.role)})"
            if item.link.timeline_id is not None:
                dimension_id = self.session.scalar(
                    select(Timeline.dimension_id).where(Timeline.entity_id == item.link.timeline_id)
                )
                period = self._period(dimension_id, "link", item.link.id)
                name, prime = self.timeline(item.link.timeline_id)
                if period:
                    line += f" · {period}"
                if not prime:
                    line += f" · in {escape(name)}"
            lines.append(line)
        return lines


def export_markdown(
    context: VaultContext,
    sink: ExportSink,
    *,
    audience: Audience = "readers",
    calendars: Sequence[str] = (),
    now: datetime | None = None,
) -> MarkdownExportInfo:
    """Export the vault of ``context`` (its session: a read transaction) into ``sink``, as the
    audience sees it. ``calendars``: ids of the calendars to show dates in first (the first one of
    each dimension; by default its default calendar)."""
    exporter = _Exporter(context, policy_for(audience), sink, calendars)
    exporter.contribute()
    entities = exporter.place()
    for entity in entities:
        exporter.write(entity)
    info = context.vault.info
    manifest = {
        "format": FORMAT_VERSION,
        "vault_id": info.id,
        "vault_name": info.name,
        "audience": audience,
        "app_version": __version__,
        "exported_at": (now or datetime.now(UTC)).isoformat(),
        "notes": len(entities),
    }
    sink.write(MANIFEST_NAME, (json.dumps(manifest, indent=2) + "\n").encode())
    return MarkdownExportInfo(
        vault_id=info.id,
        audience=audience,
        notes=len(entities),
        files=len(entities) + 1 + len(exporter.export.claimed),
    )


def export_vault_markdown(
    manager: VaultManager,
    vault_id: str,
    sink: ExportSink,
    *,
    audience: Audience = "readers",
    calendars: Sequence[str] = (),
) -> MarkdownExportInfo:
    """``export_markdown`` of a vault of ``manager`` (the CLI's way in: a read-only manager
    neither locks the vault nor writes to it, and opens published snapshots too)."""
    assert manager.module_registry is not None
    opened = manager.open(vault_id)
    with opened.sessions() as session:
        context = VaultContext(opened, session, manager.module_registry)
        return export_markdown(context, sink, audience=audience, calendars=calendars)
