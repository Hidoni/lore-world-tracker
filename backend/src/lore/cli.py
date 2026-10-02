"""The ``lore`` command line."""

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from lore.app import create_app
from lore.chronology.schema_export import export_schemas
from lore.config import Settings
from lore.core.logging import configure_logging

app = typer.Typer(name="lore", no_args_is_help=True, add_completion=False)
chronology_app = typer.Typer(no_args_is_help=True, help="Chronology engine assets.")
app.add_typer(chronology_app, name="chronology")


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
