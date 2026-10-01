from pathlib import Path

import pytest
from pydantic import ValidationError

from lore.config import Settings, detect_spec_dir

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults() -> None:
    settings = Settings()
    assert settings.data_dir == Path("./data")
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.read_only is False
    assert settings.exposed_vaults == []
    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]
    assert settings.cors_origins == []
    assert settings.auto_migrate is True
    assert settings.static_dir is None
    assert settings.max_upload_mb == 50
    assert settings.publish_dir is None
    assert settings.log_level == "info"
    assert settings.log_format == "text"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = {
        "LORE_DATA_DIR": str(tmp_path / "data"),
        "LORE_HOST": "0.0.0.0",
        "LORE_PORT": "8080",
        "LORE_READ_ONLY": "true",
        "LORE_EXPOSED_VAULTS": "alpha, beta,,",
        "LORE_ALLOWED_HOSTS": "*",
        "LORE_CORS_ORIGINS": "http://localhost:5173",
        "LORE_AUTO_MIGRATE": "false",
        "LORE_STATIC_DIR": str(tmp_path / "static"),
        "LORE_SPEC_DIR": str(tmp_path / "spec"),
        "LORE_MAX_UPLOAD_MB": "10",
        "LORE_PUBLISH_DIR": str(tmp_path / "published"),
        "LORE_LOG_LEVEL": "DEBUG",
        "LORE_LOG_FORMAT": "json",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert settings.data_dir == tmp_path / "data"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.read_only is True
    assert settings.exposed_vaults == ["alpha", "beta"]
    assert settings.allowed_hosts == ["*"]
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.auto_migrate is False
    assert settings.static_dir == tmp_path / "static"
    assert settings.spec_dir == tmp_path / "spec"
    assert settings.max_upload_mb == 10
    assert settings.publish_dir == tmp_path / "published"
    assert settings.log_level == "debug"
    assert settings.log_format == "json"


def test_empty_values_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LORE_EXPOSED_VAULTS", "LORE_STATIC_DIR", "LORE_PUBLISH_DIR", "LORE_SPEC_DIR"):
        monkeypatch.setenv(name, "")
    settings = Settings()
    assert settings.exposed_vaults == []
    assert settings.static_dir is None
    assert settings.publish_dir is None
    assert settings.spec_dir is None


def test_wildcard_host_requires_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_ALLOWED_HOSTS", "*")
    with pytest.raises(ValidationError, match="LORE_READ_ONLY"):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [("LORE_PORT", "70000"), ("LORE_MAX_UPLOAD_MB", "0"), ("LORE_LOG_FORMAT", "xml")],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_spec_dir_is_detected_from_a_checkout(tmp_path: Path) -> None:
    (tmp_path / "spec" / "chronology").mkdir(parents=True)
    start = tmp_path / "backend" / "src" / "lore" / "config.py"
    assert detect_spec_dir(start) == tmp_path / "spec"


def test_spec_dir_is_none_without_a_spec_tree(tmp_path: Path) -> None:
    assert detect_spec_dir(tmp_path / "somewhere" / "config.py") is None


def test_default_spec_dir_matches_detection() -> None:
    expected = REPO_ROOT / "spec" if (REPO_ROOT / "spec" / "chronology").is_dir() else None
    assert Settings().spec_dir == expected
