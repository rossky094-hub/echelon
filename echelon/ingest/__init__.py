"""
echelon.ingest
==============
Incremental paper ingestion with High-Water Mark persistence.

AUDIT-051: weekly_incremental_ingestion() + ingestion_hwm table.
"""

from echelon.ingest.hwm import (
    DEFAULT_START_DATE,
    HWM_TABLE,
    ensure_hwm_table,
    get_hwm,
    get_max_publication_date,
    list_all_hwm,
    set_hwm,
    weekly_incremental_ingestion,
)

__all__ = [
    # AUDIT-051: HWM persistence
    "ensure_hwm_table",
    "get_hwm",
    "set_hwm",
    "get_max_publication_date",
    "weekly_incremental_ingestion",
    "list_all_hwm",
    # Constants
    "DEFAULT_START_DATE",
    "HWM_TABLE",
]
