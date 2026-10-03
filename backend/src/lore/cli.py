"""The ``lore`` command line."""

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import uvicorn

from lore.app import create_app
from lore.chronology.schema_export import export_schemas
from lore.config import Settings
from lore.core.db.migrate import Migrator
from lore.core.errors import LoreError
from lore.core.logging import configure_logging
from lore.core.vaults import VaultManager
from lore.modules import load_metadata

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
    # configured above (log_config=None), and the access log comes from lore.access.
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
