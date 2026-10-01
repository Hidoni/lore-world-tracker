import io
import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from lore.core.logging import configure_logging, request_id_var
from tests.conftest import AppFactory, local_client


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = False


@pytest.mark.usefixtures("restore_logging")
def test_json_access_log_line(make_app: AppFactory) -> None:
    stream = io.StringIO()
    configure_logging("info", "json", stream=stream)
    client: TestClient = local_client(make_app())

    client.get("/api/v1/health", headers={"X-Request-Id": "req-42"})

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    [access] = [line for line in lines if line["logger"] == "lore.access"]
    assert access["request_id"] == "req-42"
    assert access["method"] == "GET"
    assert access["path"] == "/api/v1/health"
    assert access["status"] == 200
    assert access["duration_ms"] >= 0
    assert access["level"] == "info"


@pytest.mark.usefixtures("restore_logging")
def test_text_format_and_level() -> None:
    stream = io.StringIO()
    configure_logging("warning", "text", stream=stream)
    logger = logging.getLogger("lore.test")

    logger.info("hidden")
    token = request_id_var.set("rid-7")
    try:
        logger.warning("shown")
    finally:
        request_id_var.reset(token)
    logger.warning("outside")

    output = stream.getvalue()
    assert "hidden" not in output
    assert "[rid-7] shown" in output
    assert "[-] outside" in output
    assert logging.getLogger("uvicorn.access").disabled


@pytest.mark.usefixtures("restore_logging")
def test_json_exceptions_are_logged_with_traceback() -> None:
    stream = io.StringIO()
    configure_logging("info", "json", stream=stream)
    try:
        raise ValueError("kaput")
    except ValueError:
        logging.getLogger("lore.test").exception("failed", extra={"color_message": "\x1b[1mx"})
    record = json.loads(stream.getvalue())
    assert record["message"] == "failed"
    assert "ValueError: kaput" in record["exc_info"]
    assert record["request_id"] == "-"
    assert "color_message" not in record
