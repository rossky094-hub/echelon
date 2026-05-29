"""Recover Step5b calibration audit from a trusted Step5b checkpoint.

This is intentionally conservative: it only materializes
`vgae_calibration_audit` when the checkpoint contains a real rolling
held-out-year backtest and the current `predicted_future_edges` table is
consistent with that checkpoint.  It does not invent calibration evidence.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from echelon.v14b.step5b_vgae import ensure_calibration_audit_schema


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exercised via CLI error path
        raise ValueError(f"cannot read checkpoint JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"checkpoint is not a JSON object: {path}")
    return value


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
            (table,),
        ).fetchone()
    )


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _validate_checkpoint(
    conn: sqlite3.Connection,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    if checkpoint.get("step") != "step5b_vgae":
        raise ValueError("checkpoint step is not step5b_vgae")
    calibration = checkpoint.get("calibration")
    rolling = checkpoint.get("rolling_backtest")
    if not isinstance(calibration, dict) or not calibration.get("method"):
        raise ValueError("checkpoint missing calibration.method")
    if not isinstance(rolling, dict) or not rolling.get("years"):
        raise ValueError("checkpoint missing rolling_backtest.years")
    avg_auc = float(rolling.get("avg_calibrated_auc") or 0.0)
    if avg_auc <= 0.0:
        raise ValueError("checkpoint rolling_backtest avg_calibrated_auc is empty")
    if not _table_exists(conn, "predicted_future_edges"):
        raise ValueError("predicted_future_edges table is missing")
    predicted_cols = _columns(conn, "predicted_future_edges")
    if "calibration_label" not in predicted_cols:
        raise ValueError("predicted_future_edges.calibration_label is missing")
    current_edges = int(_scalar(conn, "SELECT COUNT(*) FROM predicted_future_edges") or 0)
    checkpoint_edges = int(checkpoint.get("predicted_edges") or checkpoint.get("records_n") or 0)
    if checkpoint_edges <= 0:
        raise ValueError("checkpoint missing predicted_edges/records_n")
    if current_edges != checkpoint_edges:
        raise ValueError(
            f"predicted_future_edges count mismatch: current={current_edges} checkpoint={checkpoint_edges}"
        )
    label = str(calibration.get("label") or "")
    if label:
        current_label_count = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*) FROM predicted_future_edges
                WHERE calibration_label = ?
                """,
                (label,),
            )
            or 0
        )
        if current_label_count == 0:
            raise ValueError(f"checkpoint calibration label {label!r} not present on current edges")
    return {
        "current_edges": current_edges,
        "checkpoint_edges": checkpoint_edges,
        "avg_calibrated_auc": avg_auc,
        "label": label,
    }


def recover_calibration_audit(
    *,
    db_v14: Path,
    checkpoint_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    checkpoint = _load_json(checkpoint_path)
    conn = sqlite3.connect(str(db_v14))
    conn.row_factory = sqlite3.Row
    try:
        existing = (
            int(_scalar(conn, "SELECT COUNT(*) FROM vgae_calibration_audit") or 0)
            if _table_exists(conn, "vgae_calibration_audit")
            else 0
        )
        if existing and not force:
            return {
                "status": "skipped_existing_audit",
                "existing_rows": existing,
                "db_v14": str(db_v14),
            }
        validation = _validate_checkpoint(conn, checkpoint)
        calibration = checkpoint["calibration"]
        rolling = checkpoint["rolling_backtest"]
        ensure_calibration_audit_schema(conn)
        run_id = str(checkpoint.get("finished_at") or "step5b_checkpoint_recovered").replace(":", "").replace("-", "")
        summary = dict(calibration)
        summary.update(
            {
                "source": "recovered_from_step5b_checkpoint",
                "source_checkpoint": str(checkpoint_path),
                "prediction_confidence_avg": checkpoint.get("prediction_confidence_avg"),
                "val_auc": checkpoint.get("val_auc"),
                "test_auc": checkpoint.get("test_auc"),
                "validation": validation,
            }
        )
        conn.execute("DELETE FROM vgae_calibration_audit")
        conn.execute(
            """
            INSERT INTO vgae_calibration_audit
                (run_id, method, label, support, base_rate, avg_raw_auc, avg_calibrated_auc,
                 summary_json, rolling_backtest_json, curve_json)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                calibration.get("method"),
                calibration.get("label"),
                int(calibration.get("support") or 0),
                float(calibration.get("base_rate") or 0.0),
                float(rolling.get("avg_raw_auc") or 0.0),
                float(rolling.get("avg_calibrated_auc") or 0.0),
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
                json.dumps(rolling, ensure_ascii=False, sort_keys=True),
                json.dumps(checkpoint.get("calibration_curve") or [], ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
        return {
            "status": "recovered",
            "db_v14": str(db_v14),
            "checkpoint": str(checkpoint_path),
            "method": calibration.get("method"),
            "label": calibration.get("label"),
            "support": int(calibration.get("support") or 0),
            "avg_calibrated_auc": float(rolling.get("avg_calibrated_auc") or 0.0),
            "validation": validation,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover vgae_calibration_audit from Step5b checkpoint.")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument(
        "--checkpoint",
        default="reports/v14b_pilot/checkpoints/step5b_vgae.done.json",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = recover_calibration_audit(
        db_v14=Path(args.db_v14),
        checkpoint_path=Path(args.checkpoint),
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
