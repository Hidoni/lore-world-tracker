"""Vault maintenance: health checks, derived-data rebuilds and database optimization
(``persistence-and-migrations.md`` §2, §3.4; the ``lore vault check|reindex|optimize`` commands).
"""

from lore.core.maintenance.checks import DERIVED_DATA, DerivedDataCheck, Problem
from lore.core.maintenance.service import (
    CheckReport,
    check_vault,
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
    "optimize_vault",
    "reindex_vault",
    "run_checks",
]
