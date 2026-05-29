from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from echelon.v14b.recover_vgae_calibration_audit import recover_calibration_audit


def _make_v14(path: Path, *, rows: int = 2, existing_audit: bool = False) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            calibration_label TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO predicted_future_edges VALUES (?, ?, ?)",
        [(f"p{i}", f"q{i}", "calibrated_temporal_holdout") for i in range(rows)],
    )
    if existing_audit:
        conn.executescript(
            """
            CREATE TABLE vgae_calibration_audit (
                run_id TEXT PRIMARY KEY,
                method TEXT,
                label TEXT,
                support INTEGER,
                base_rate REAL,
                avg_raw_auc REAL,
                avg_calibrated_auc REAL,
                summary_json TEXT,
                rolling_backtest_json TEXT,
                curve_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO vgae_calibration_audit
                (run_id, method, label, support, base_rate, avg_raw_auc, avg_calibrated_auc,
                 summary_json, rolling_backtest_json, curve_json)
            VALUES ('old', 'old_method', 'old_label', 1, 0.0, 0.1, 0.1, '{}', '{}', '[]')
            """
        )
    conn.commit()
    conn.close()


def _write_checkpoint(path: Path, *, predicted_edges: int = 2) -> None:
    path.write_text(
        json.dumps(
            {
                "step": "step5b_vgae",
                "finished_at": "2026-05-28T23:51:02.563603",
                "records_n": predicted_edges,
                "predicted_edges": predicted_edges,
                "val_auc": 0.804,
                "test_auc": 0.837,
                "prediction_confidence_avg": 0.85,
                "calibration": {
                    "method": "temporal_platt_logistic",
                    "label": "calibrated_temporal_holdout",
                    "support": 7198,
                    "base_rate": 0.5,
                },
                "rolling_backtest": {
                    "avg_raw_auc": 0.8367,
                    "avg_calibrated_auc": 0.8367,
                    "years": [{"year": 2024, "calibrated_auc": 0.81}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_recover_calibration_audit_from_valid_checkpoint(tmp_path):
    db = tmp_path / "v14.sqlite3"
    checkpoint = tmp_path / "step5b_vgae.done.json"
    _make_v14(db)
    _write_checkpoint(checkpoint)

    result = recover_calibration_audit(db_v14=db, checkpoint_path=checkpoint, force=False)

    assert result["status"] == "recovered"
    assert result["method"] == "temporal_platt_logistic"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM vgae_calibration_audit").fetchone()
    conn.close()
    assert row["label"] == "calibrated_temporal_holdout"
    assert row["support"] == 7198
    assert json.loads(row["summary_json"])["source"] == "recovered_from_step5b_checkpoint"


def test_recover_calibration_audit_rejects_count_mismatch(tmp_path):
    db = tmp_path / "v14.sqlite3"
    checkpoint = tmp_path / "step5b_vgae.done.json"
    _make_v14(db, rows=1)
    _write_checkpoint(checkpoint, predicted_edges=2)

    with pytest.raises(ValueError, match="count mismatch"):
        recover_calibration_audit(db_v14=db, checkpoint_path=checkpoint)


def test_recover_calibration_audit_skips_existing_without_force(tmp_path):
    db = tmp_path / "v14.sqlite3"
    checkpoint = tmp_path / "step5b_vgae.done.json"
    _make_v14(db, existing_audit=True)
    _write_checkpoint(checkpoint)

    result = recover_calibration_audit(db_v14=db, checkpoint_path=checkpoint, force=False)

    assert result["status"] == "skipped_existing_audit"
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT method FROM vgae_calibration_audit").fetchone()
    conn.close()
    assert row[0] == "old_method"

