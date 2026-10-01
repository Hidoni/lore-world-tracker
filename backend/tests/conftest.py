import os
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import settings as hypothesis_settings

from lore.app import create_app
from lore.config import Settings

hypothesis_settings.register_profile("dev", max_examples=50, derandomize=True)
hypothesis_settings.register_profile("ci", max_examples=500, derandomize=True)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def _clean_lore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's ``LORE_*`` environment."""
    for name in list(os.environ):
        if name.startswith("LORE_"):
            monkeypatch.delenv(name)


type AppFactory = Callable[..., FastAPI]


@pytest.fixture
def make_app() -> AppFactory:
    def factory(**overrides: object) -> FastAPI:
        return create_app(Settings.model_validate(overrides))

    return factory


@pytest.fixture
def client(make_app: AppFactory) -> Iterator[TestClient]:
    with TestClient(make_app()) as test_client:
        yield test_client
