"""Reset derived V14B graph outputs before a clean Step2-Step9 rerun."""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from echelon.v14b.config import CHECKPOINT_DIR, DB_V14
from echelon.v14b.db_schema import init_v14b_db
from echelon.v14b.utils import setup_logging

logger = logging.getLogger("echelon.v14b.step0_reset_pilot")

DERIVED_TABLES = [
    "main_path_edges",
    "main_path_cycle_audit",
    "main_path_edge_audit",
    "subgraph_nodes",
    "subgraph_edges",
    "limitation_atoms",
    "limitation_resolutions",
    "predicted_future_edges",
    "future_directions",
    "v14b_run_meta",
]


def reset_pilot(db_v14: Path = DB_V14, *, clear_checkpoints: bool = True) -> dict:
    conn = init_v14b_db(db_v14)
    counts = {}
    for table in DERIVED_TABLES:
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.Error:
            counts[table] = 0
    conn.commit()
    conn.close()

    removed_checkpoints = 0
    if clear_checkpoints and CHECKPOINT_DIR.exists():
        for path in CHECKPOINT_DIR.glob("step*.done.json"):
            path.unlink()
            removed_checkpoints += 1

    stats = {"cleared_rows": counts, "removed_checkpoints": removed_checkpoints}
    logger.info("Pilot reset done: %s", stats)
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Reset V14B derived pilot outputs")
    parser.add_argument("--db-v14", type=Path, default=DB_V14)
    parser.add_argument("--keep-checkpoints", action="store_true")
    args = parser.parse_args(argv)
    setup_logging("step0_reset_pilot")
    reset_pilot(args.db_v14, clear_checkpoints=not args.keep_checkpoints)


if __name__ == "__main__":
    main()
