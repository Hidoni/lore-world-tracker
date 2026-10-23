"""The ``lore`` command line."""

import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import uvicorn

from lore.app import create_app
from lore.chronology.schema_export import export_schemas
from lore.config import Settings
from lore.core.db.migrate import Migrator
from lore.core.errors import LoreError
from lore.core.interchange.export import export_interchange
from lore.core.interchange.importer import import_interchange
from lore.core.logging import configure_logging
from lore.core.maintenance import (
    DERIVED_DATA,
    check_vault,
    compact_vault_history,
    optimize_vault,
    refine_dimension_base_unit,
    reindex_vault,
)
from lore.core.markdown.export import Audience, FolderSink, export_vault_markdown
from lore.core.models import load_metadata as load_core_metadata
from lore.core.modules import ModuleRegistry
from lore.core.vaults import VaultManager
from lore.core.vaults.publish import publish_vault
from lore.modules import ALL_MODULES, load_metadata
from lore.static_export import export_static

app = typer.Typer(name="lore", no_args_is_help=True, add_completion=False)
chronology_app = typer.Typer(no_args_is_help=True, help="Chronology engine assets.")
app.add_typer(chronology_app, name="chronology")
vault_app = typer.Typer(no_args_is_help=True, help="Vault administration.")
app.add_typer(vault_app, name="vault")
db_app = typer.Typer(no_args_is_help=True, help="Migration tooling (developers).")
app.add_typer(db_app, name="db")

VaultArgument = Annotated[str, typer.Argument(help="Vault id or folder name.")]


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address (default: LORE_HOST).")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default: LORE_PORT).")] = None,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (development).")] = False,
) -> None:
    """Serve the API (and the SPA when LORE_STATIC_DIR is set) with a single worker."""
    settings = Settings()
    bind_host = host or settings.host
    bind_port = port if port is not None else settings.port
    configure_logging(settings.log_level, settings.log_format)
    # Per-vault engines and caches live in-process: never more than one worker. Logging is
    # configured above (log_config=None), and the access log comes from lore.access. Idle
    # connections stay open longer than clients and proxies keep them (deployment.md §1): with
    # uvicorn's 5 s default, a client could reuse a connection just as the server closed it.
    if reload:
        uvicorn.run(
            "lore.app:create_app_from_env",
            factory=True,
            reload=True,
            host=bind_host,
            port=bind_port,
            log_level=settings.log_level,
            log_config=None,
            access_log=False,
            timeout_keep_alive=settings.keep_alive,
            workers=1,
        )
    else:
        uvicorn.run(
            create_app(settings),
            host=bind_host,
            port=bind_port,
            log_level=settings.log_level,
            log_config=None,
            access_log=False,
            timeout_keep_alive=settings.keep_alive,
            workers=1,
        )


@app.command()
def openapi(
    out: Annotated[Path | None, typer.Option(help="Write to this file instead of stdout.")] = None,
) -> None:
    """Print the OpenAPI document (the API contract)."""
    document = json.dumps(create_app(Settings()).openapi(), indent=2, ensure_ascii=False) + "\n"
    if out is None:
        typer.echo(document, nl=False)
    else:
        out.write_text(document, encoding="utf-8")


def _vault_manager() -> VaultManager:
    settings = Settings()
    return VaultManager(
        settings.data_dir,
        read_only=settings.read_only,
        exposed_vaults=settings.exposed_vaults,
        auto_migrate=settings.auto_migrate,
        module_registry=ModuleRegistry(ALL_MODULES, core_metadata=load_core_metadata()),
    )


def _fail(exc: Exception) -> NoReturn:
    typer.echo(f"error: {exc}", err=True)
    raise typer.Exit(1) from exc


@vault_app.command("list")
def vault_list() -> None:
    """List the vaults in LORE_DATA_DIR (id, folder, name), then folders that can't be opened."""
    registry = _vault_manager().registry()
    for info in registry.sorted_vaults():
        typer.echo(f"{info.id}  {info.folder}  {info.name}")
    for problem in registry.problems:
        typer.echo(f"problem: {problem.folder}: {problem.code}: {problem.detail}", err=True)


@vault_app.command("create")
def vault_create(name: Annotated[str, typer.Argument(help="Display name.")]) -> None:
    """Create a vault in LORE_DATA_DIR and print its id and folder."""
    try:
        info = _vault_manager().create(name)
    except (LoreError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"{info.id}  {info.folder}  {info.name}")


@vault_app.command("status")
def vault_status(vault: VaultArgument) -> None:
    """Show a vault's folder, name and schema state (revision vs. this app's head)."""
    manager = _vault_manager()
    try:
        info = manager.resolve(vault)
    except LoreError as exc:
        _fail(exc)
    schema = manager.schema_status(info)
    typer.echo(f"id:        {info.id}")
    typer.echo(f"folder:    {info.folder}")
    typer.echo(f"name:      {info.name}")
    typer.echo(f"schema:    {schema.state}")
    typer.echo(f"revision:  {schema.revision or '(none)'}")
    typer.echo(f"head:      {schema.head}")


@vault_app.command("migrate")
def vault_migrate(
    vault: VaultArgument,
    to: Annotated[str, typer.Option(help="Target revision (default: head).")] = "head",
) -> None:
    """Upgrade a vault's database (after a pre-migration backup)."""
    manager = _vault_manager()
    try:
        result = manager.migrate(manager.resolve(vault).id, to)
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    if result.backup is None:
        typer.echo(f"already at {result.to_revision}")
    else:
        typer.echo(f"migrated {result.from_revision or 'base'} -> {result.to_revision}")
        typer.echo(f"backup: {result.backup}")


@vault_app.command("backup")
def vault_backup(
    vault: VaultArgument,
    media: Annotated[bool, typer.Option(help="Include the media folder.")] = True,
) -> None:
    """Write a backup zip into the vault's backups/manual/ (it contains private data)."""
    manager = _vault_manager()
    try:
        info = manager.backup(manager.resolve(vault).id, include_media=media)
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    typer.echo(f"{info.id}  {info.size} bytes")
    typer.echo(f"backup: {info.path}")


@vault_app.command("restore")
def vault_restore(
    backup: Annotated[Path, typer.Argument(help="Backup zip.", exists=True, dir_okay=False)],
) -> None:
    """Restore a backup zip into a new vault (never overwrites an existing one)."""
    manager = _vault_manager()
    try:
        info = manager.restore(backup)
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    typer.echo(f"{info.id}  {info.folder}  {info.name}")


@vault_app.command("publish")
def vault_publish(
    vault: VaultArgument,
    out: Annotated[
        Path | None,
        typer.Option(
            help="Data directory of the read-only server (default: LORE_PUBLISH_DIR); the "
            "snapshot goes to <out>/vaults/<folder>/, replacing an earlier one."
        ),
    ] = None,
) -> None:
    """Publish a sanitized snapshot of a vault: private data removed, for a read-only server.
    Fails (writing nothing) when the leak gate finds private data in the snapshot."""
    target = out or Settings().publish_dir
    if target is None:
        _fail(ValueError("give --out or set LORE_PUBLISH_DIR"))
    manager = _vault_manager()
    try:
        info = publish_vault(manager, manager.resolve(vault).id, target)
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    typer.echo(f"published: {info.path}")


@vault_app.command("export-static")
def vault_export_static(
    vault: Annotated[str, typer.Argument(help="Published snapshot: vault id or folder name.")],
    out: Annotated[Path, typer.Option(help="Folder to write (created; must be empty).")],
    data_dir: Annotated[
        Path | None,
        typer.Option(help="Data directory holding the snapshot (default: LORE_PUBLISH_DIR)."),
    ] = None,
    spa: Annotated[
        Path | None, typer.Option(help="The built SPA (default: LORE_STATIC_DIR).")
    ] = None,
) -> None:
    """Export a published snapshot as a static site: the SPA and the data readers see, as plain
    files any static HTTP server can host (visibility-and-sharing.md §8)."""
    settings = Settings()
    source = data_dir or settings.publish_dir
    spa_dir = spa or settings.static_dir
    if source is None:
        _fail(ValueError("give --data-dir or set LORE_PUBLISH_DIR"))
    if spa_dir is None:
        _fail(ValueError("give --spa or set LORE_STATIC_DIR"))
    try:
        info = export_static(source, vault, out, spa_dir)
    except LoreError as exc:
        _fail(exc)
    typer.echo(f"exported: {info.path} ({info.files} data files)")


@vault_app.command("export-markdown")
def vault_export_markdown(
    vault: VaultArgument,
    out: Annotated[Path, typer.Option(help="Folder to write (created; must be empty).")],
    audience: Annotated[
        str,
        typer.Option(
            help="readers: what readers see (no private data); author: everything, private "
            "content included."
        ),
    ] = "readers",
    calendar: Annotated[
        list[str] | None,
        typer.Option(help="A calendar id to show dates in first (repeat for several dimensions)."),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option(help="Data directory holding the vault (default: LORE_DATA_DIR)."),
    ] = None,
) -> None:
    """Export a vault as Markdown notes for Obsidian and other Markdown tools: one note per
    entity with wikilinks, properties, dates in every calendar, facts, links and media
    (markdown-export.md). Reads the vault without locking it, also a published snapshot."""
    if audience not in ("readers", "author"):
        _fail(ValueError("--audience must be readers or author"))
    manager = VaultManager(
        data_dir or Settings().data_dir,
        read_only=True,
        module_registry=ModuleRegistry(ALL_MODULES, core_metadata=load_core_metadata()),
    )
    try:
        sink = FolderSink(out)
        chosen: Audience = "readers" if audience == "readers" else "author"
        info = export_vault_markdown(
            manager, manager.resolve(vault).id, sink, audience=chosen, calendars=calendar or ()
        )
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    typer.echo(f"exported: {out} ({info.notes} notes, {info.files} files)")


@vault_app.command("export-json")
def vault_export_json(
    vault: VaultArgument,
    out: Annotated[Path, typer.Option(help="Zip file to write (must not exist).")],
    audience: Annotated[
        str,
        typer.Option(
            help="readers: what readers see (no private data); author: everything, private "
            "content included."
        ),
    ] = "readers",
    dimension: Annotated[
        str | None,
        typer.Option(help="Export one dimension (id or exact name) instead of the whole vault."),
    ] = None,
) -> None:
    """Export a vault (or one dimension) as an interchange zip: a versioned JSON document of its
    records and their media files, for `lore vault import-json` in this app or a later one
    (interchange.md). Reads a copy of the database: runs next to a server."""
    if audience not in ("readers", "author"):
        _fail(ValueError("--audience must be readers or author"))
    if out.exists():
        _fail(ValueError(f"{out} exists"))
    manager = _vault_manager()
    try:
        with out.open("xb") as file:
            info = export_interchange(
                manager,
                manager.resolve(vault).id,
                file,
                audience="readers" if audience == "readers" else "author",
                dimension=dimension,
            )
    except LoreError as exc:
        out.unlink(missing_ok=True)
        _fail(exc)
    finally:
        manager.close()
    typer.echo(
        f"exported: {out} ({info.entities} entities, {info.rows} records, {info.files} files, "
        f"{info.references} references)"
    )


@vault_app.command("import-json")
def vault_import_json(
    vault: VaultArgument,
    file: Annotated[
        Path, typer.Argument(help="Interchange zip or JSON document.", exists=True, dir_okay=False)
    ],
    keep_ids: Annotated[
        bool,
        typer.Option(help="Keep the file's ids (default: fresh ids, so importing twice copies)."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            help="Replace the vault's records that clash with the file's (after a backup) "
            "instead of refusing the import."
        ),
    ] = False,
) -> None:
    """Import an interchange zip into an existing vault, as one changeset (undoable). Refuses
    the whole import, listing the conflicts, when records clash (unless --overwrite)."""
    manager = _vault_manager()
    try:
        with file.open("rb") as source:
            report = import_interchange(
                manager,
                manager.resolve(vault).id,
                source,
                ids="keep" if keep_ids else "remap",
                on_conflict="overwrite" if overwrite else "fail",
            )
    except LoreError as exc:
        for conflict in (exc.context or {}).get("conflicts", []):
            typer.echo(f"conflict: {conflict['table']} {conflict['id']}", err=True)
        _fail(exc)
    finally:
        manager.close()
    created = sum(report.created.values())
    typer.echo(
        f"imported: {len(report.entities)} entities ({created} records created, "
        f"{sum(report.updated.values())} updated, {sum(report.reused.values())} reused, "
        f"{sum(report.dropped.values())} dropped, {report.files} files)"
    )
    for reference in report.references_unmatched:
        typer.echo(f"unmatched reference: {reference.kind} “{reference.name}”", err=True)


@vault_app.command("check")
def vault_check(
    vault: VaultArgument,
    as_json: Annotated[bool, typer.Option("--json", help="Print a JSON report.")] = False,
) -> None:
    """Check a vault's health: schema state, SQLite integrity, foreign keys and derived data
    (search index, mentions). Never changes the vault: the checks run on a temporary copy of its
    database (needs that much free space in the temp folder). Exits with 1 when problems are
    found (`lore vault reindex` fixes derived data)."""
    manager = _vault_manager()
    try:
        vault_id = manager.resolve(vault).id
        report = check_vault(manager, vault_id)
    except LoreError as exc:
        _fail(exc)
    if as_json:
        document = {
            "vault": vault_id,
            "ok": report.ok,
            "checks": list(report.checks),
            "problems": [asdict(problem) for problem in report.problems],
        }
        typer.echo(json.dumps(document, indent=2, ensure_ascii=False))
    else:
        for problem in report.problems:
            typer.echo(f"{problem.check}: {problem.code}: {problem.message}")
        if report.ok:
            typer.echo(f"ok ({', '.join(report.checks)})")
        else:
            typer.echo(f"{len(report.problems)} problem(s) found", err=True)
    if not report.ok:
        raise typer.Exit(1)


@vault_app.command("reindex")
def vault_reindex(vault: VaultArgument) -> None:
    """Rebuild a vault's derived data (search index, mentions) from its content."""
    manager = _vault_manager()
    try:
        opened = manager.open(manager.resolve(vault).id)
        assert manager.module_registry is not None
        counts = reindex_vault(opened, manager.module_registry)
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    for check in DERIVED_DATA:
        typer.echo(f"{check.id}: rebuilt {counts[check.id]} {check.unit}")
    modules = manager.module_registry.modules if manager.module_registry else []
    for check in (c for module in modules for c in module.derived_checks):
        if check.id in counts:  # the enabled modules' checks
            typer.echo(f"{check.id}: rebuilt {counts[check.id]} {check.unit}")


@vault_app.command("compact-history")
def vault_compact_history(
    vault: VaultArgument,
    older_than: Annotated[
        int, typer.Option(min=1, help="Compact the changes saved more than this many days ago.")
    ],
    dry_run: Annotated[
        bool, typer.Option(help="Only report what would be compacted; change nothing.")
    ] = False,
) -> None:
    """Replace a vault's history older than N days with one snapshot per entity (its net
    change over that period), to bound storage. Compacted changes can't be undone or looked at
    one by one any more, so make a backup first (`lore vault backup`). `lore vault optimize
    --vacuum` then shrinks the file."""
    manager = _vault_manager()
    try:
        opened = manager.open(manager.resolve(vault).id)
        report = compact_vault_history(opened, timedelta(days=older_than), dry_run=dry_run)
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    verb = "would compact" if dry_run else "compacted"
    typer.echo(
        f"{verb} {report.changesets} changesets ({report.changes} changes) older than "
        f"{older_than} days into {report.snapshots} snapshots ({report.snapshot_changes} changes)"
    )


@vault_app.command("refine-base-unit")
def vault_refine_base_unit(
    vault: VaultArgument,
    dimension: Annotated[str, typer.Option(help="The dimension, by id or exact name.")],
    factor: Annotated[
        int, typer.Option(min=2, help="New base units per old one (seconds → ms: 1000).")
    ],
    unit: Annotated[
        str | None,
        typer.Option(
            help="The new unit's names, 'singular,plural,abbr' (e.g. 'millisecond,"
            "milliseconds,ms'); default: the names stay."
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Only report what would change; change nothing.")
    ] = False,
) -> None:
    """Refine a dimension's base unit: multiply every moment, base duration, interval and the
    calendars' finest units by FACTOR, so dates stay the same and finer moments fit between
    them. A backup is taken first; the change, and the changes saved before it, can't be undone
    (restore the backup instead)."""
    names = None
    if unit is not None:
        parts = [part.strip() for part in unit.split(",")]
        if len(parts) != 3 or not all(parts):  # noqa: PLR2004 (singular, plural, abbr)
            typer.echo("--unit takes 'singular,plural,abbr'.", err=True)
            raise typer.Exit(2)
        names = dict(zip(("singular", "plural", "abbr"), parts, strict=True))
    manager = _vault_manager()
    try:
        found = refine_dimension_base_unit(
            manager, manager.resolve(vault).id, dimension, factor, names, dry_run=dry_run
        )
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    report = found.report
    verb = "would rewrite" if dry_run else "rewrote"
    tables = ", ".join(f"{count} {table}" for table, count in sorted(report.rewritten.items()))
    typer.echo(f"{verb} {tables or 'nothing'}; D is now {report.duration}")
    typer.echo(
        f"resolved {report.slots} slots again; event slots that don't resolve: "
        f"{report.problems_before} before, {report.problems_after} after"
    )
    if found.backup_id is not None:
        typer.echo(f"backup taken before: {found.backup_id}")


@vault_app.command("optimize")
def vault_optimize(
    vault: VaultArgument,
    vacuum: Annotated[
        bool, typer.Option(help="Also VACUUM (rewrites the file; needs that much free space).")
    ] = False,
) -> None:
    """Run PRAGMA optimize on a vault's database (and optionally VACUUM it)."""
    manager = _vault_manager()
    try:
        opened = manager.open(manager.resolve(vault).id)
        before = opened.info.database_path.stat().st_size
        optimize_vault(opened, vacuum_database=vacuum)
        after = opened.info.database_path.stat().st_size
    except LoreError as exc:
        _fail(exc)
    finally:
        manager.close()
    if vacuum:
        typer.echo(f"optimized and vacuumed ({before} -> {after} bytes)")
    else:
        typer.echo("optimized")


@db_app.command("revision")
def db_revision(
    message: Annotated[str, typer.Option("-m", "--message", help="What the migration does.")],
    autogenerate: Annotated[
        bool, typer.Option(help="Diff the models against a scratch database at head.")
    ] = False,
) -> None:
    """Write a new migration into src/lore/migrations/versions/."""
    try:
        path = Migrator(metadata=load_metadata).revision(message, autogenerate=autogenerate)
    except LoreError as exc:
        _fail(exc)
    typer.echo(f"wrote {path}")
    typer.echo("Edit the docstring owner ([core], [core:time] or [module: <id>]) and review it.")


@db_app.command("check")
def db_check() -> None:
    """Fail unless the history has exactly one head and the models match the migrations."""
    problems = Migrator(metadata=load_metadata).check()
    for problem in problems:
        typer.echo(problem, err=True)
    if problems:
        raise typer.Exit(1)
    typer.echo("migrations are clean (one head, no model/migration differences)")


@chronology_app.command("export-schemas")
def export_chronology_schemas(
    out: Annotated[
        Path | None,
        typer.Option(help="Target directory (default: <LORE_SPEC_DIR>/chronology/schema)."),
    ] = None,
    check: Annotated[
        bool, typer.Option(help="Write nothing; fail if the committed files are stale.")
    ] = False,
) -> None:
    """Export the chronology JSON Schemas (spec/chronology/schema/*.json)."""
    if out is None:
        spec_dir = Settings().spec_dir
        if spec_dir is None:
            typer.echo("no spec directory found: pass --out or set LORE_SPEC_DIR", err=True)
            raise typer.Exit(2)
        out = spec_dir / "chronology" / "schema"
    files = export_schemas()
    existing = {path.name for path in out.glob("*.json")} if out.is_dir() else set()
    if check:
        stale = sorted(
            name
            for name, text in files.items()
            if not (out / name).is_file() or (out / name).read_text(encoding="utf-8") != text
        )
        extra = sorted(existing - files.keys())
        if stale or extra:
            for name in stale:
                typer.echo(f"stale: {out / name}", err=True)
            for name in extra:
                typer.echo(f"not generated: {out / name}", err=True)
            typer.echo("Run `make gen` and commit the result.", err=True)
            raise typer.Exit(1)
        typer.echo(f"{out} is up to date.")
        return
    out.mkdir(parents=True, exist_ok=True)
    for name in existing - files.keys():
        (out / name).unlink()
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    typer.echo(f"wrote {len(files)} schemas to {out}")


def main() -> None:
    app()
