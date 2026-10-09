"""Sample worlds for the perf tests (``testing.md`` §4): built once per generator version and
cached, since ``large`` takes hours (#235).

The cache lives in ``LORE_SAMPLE_CACHE`` (default: ``.pytest_cache/d/sample-worlds`` in
``backend/``). An entry is keyed by the size, the seed, and digests of the generator, the app
version and the migrations, so a change to any of them builds a fresh world. Tests get a copy of
the cached data dir (perf tests write: findings, proposals), never the cache itself.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

from scripts import make_sample_vault
from scripts.make_sample_vault import DEFAULT_SEED, SampleWorld, Size

from lore import __version__

BACKEND = Path(__file__).parents[1]
MIGRATIONS = BACKEND / "src" / "lore" / "migrations" / "versions"


def cache_root() -> Path:
    configured = os.environ.get("LORE_SAMPLE_CACHE")
    return Path(configured) if configured else BACKEND / ".pytest_cache" / "d" / "sample-worlds"


def _digest(size: Size, seed: int) -> str:
    parts = [
        size,
        str(seed),
        __version__,
        Path(make_sample_vault.__file__).read_text("utf-8"),
        *sorted(path.name for path in MIGRATIONS.glob("*.py")),
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def cached_world(size: Size, seed: int = DEFAULT_SEED) -> tuple[Path, SampleWorld]:
    """The data dir of a sample world of ``size`` and what was built, generating it on a cache
    miss (stale entries of the size are removed)."""
    root = cache_root()
    target = root / f"{size}-{_digest(size, seed)}"
    manifest = target / "world.json"
    if not manifest.exists():
        for stale in root.glob(f"{size}-*"):
            shutil.rmtree(stale)
        building = root / f"{target.name}.building"
        shutil.rmtree(building, ignore_errors=True)
        building.mkdir(parents=True)
        world = make_sample_vault.generate(building / "data", size, seed=seed, progress=print)
        (building / "world.json").write_text(json.dumps(world.__dict__, indent=2), "utf-8")
        building.rename(target)
    world = SampleWorld(**json.loads(manifest.read_text("utf-8")))
    return target / "data", world


def copy_world(size: Size, data_dir: Path, seed: int = DEFAULT_SEED) -> SampleWorld:
    """A copy of the cached sample world of ``size`` in ``data_dir``."""
    source, world = cached_world(size, seed)
    shutil.copytree(source, data_dir)
    return world
