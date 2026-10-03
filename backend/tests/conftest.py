import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import settings as hypothesis_settings

from lore.app import create_app
from lore.config import Settings
from tests.migration_harness import MigrationHarness

hypothesis_settings.register_profile("dev", max_examples=50, derandomize=True)
hypothesis_settings.register_profile("ci", max_examples=500, derandomize=True)
# PROPERTY_PROFILE selects the profile for both engines (fast-check reads it too).
hypothesis_settings.load_profile(
    os.environ.get("PROPERTY_PROFILE") or os.environ.get("HYPOTHESIS_PROFILE", "dev")
)


@pytest.fixture(autouse=True)
def _clean_lore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's ``LORE_*`` environment."""
    for name in list(os.environ):
        if name.startswith("LORE_"):
            monkeypatch.delenv(name)


type AppFactory = Callable[..., FastAPI]

BASE_URL = "http://localhost"


def local_client(app: FastAPI, **kwargs: Any) -> TestClient:
    """A TestClient whose requests carry an allowed Host (``localhost``)."""
    return TestClient(app, base_url=BASE_URL, **kwargs)


@pytest.fixture
def make_app() -> AppFactory:
    def factory(**overrides: object) -> FastAPI:
        return create_app(Settings.model_validate(overrides))

    return factory


@pytest.fixture
def client(make_app: AppFactory) -> Iterator[TestClient]:
    with local_client(make_app()) as test_client:
        yield test_client


@pytest.fixture
def migrations(tmp_path: Path) -> MigrationHarness:
    """An empty database and the real migrations (``tests/migration_harness.py``)."""
    return MigrationHarness(tmp_path / "migrations.db")
