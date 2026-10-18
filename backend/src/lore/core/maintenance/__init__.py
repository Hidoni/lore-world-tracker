"""Vault maintenance: health checks, derived-data rebuilds, history compaction and database
optimization (``persistence-and-migrations.md`` §2, §3.4; the ``lore vault check``, ``reindex``,
``compact-history`` and ``optimize`` commands).
"""

from lore.core.maintenance.checks import DERIVED_DATA, DerivedDataCheck, Problem
from lore.core.maintenance.service import (
    CheckReport,
    check_vault,
    compact_vault_history,
    optimize_vault,
    reindex_vault,
    run_checks,
)

__all__ = [
    "DERIVED_DATA",
    "CheckReport",
    "DerivedDataCheck",
    "Problem",
    "check_vault",
    "compact_vault_history",
    "optimize_vault",
    "reindex_vault",
    "run_checks",
]
