"""The ``lore`` command line."""

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from lore.app import create_app
from lore.config import Settings
from lore.core.logging import configure_logging

app = typer.Typer(name="lore", no_args_is_help=True, add_completion=False)


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


def main() -> None:
    app()
