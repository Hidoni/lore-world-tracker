"""Stdlib logging configured from ``LORE_LOG_LEVEL`` / ``LORE_LOG_FORMAT``, with request ids.

Every record carries ``request_id`` (``-`` outside a request), taken from a contextvar that the
request middleware sets. ``json`` emits one JSON object per line (for containers); ``text`` is
for humans.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal, override

request_id_var: ContextVar[str | None] = ContextVar("lore_request_id", default=None)

# LogRecord attributes that are not user-supplied ``extra`` fields (``color_message`` is uvicorn's
# ANSI-colored duplicate of the message).
_RECORD_ATTRIBUTES = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
    | {"message", "asctime", "request_id", "taskName", "color_message"}
)

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s"


class RequestIdFilter(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        payload.update(
            {key: value for key, value in record.__dict__.items() if key not in _RECORD_ATTRIBUTES}
        )
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: str = "info",
    log_format: Literal["text", "json"] = "text",
    stream: Any = None,
) -> None:
    """Replace the root logger's handlers with one stream handler in the chosen format."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if log_format == "json" else logging.Formatter(TEXT_FORMAT)
    )
    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Uvicorn's own access log is replaced by ``lore.access`` (one line per request, with the id).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
