from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.direction_readiness_audit import (
    _public_latest_fusion_audit,
    classify_blockers,
    collect_metrics,
    load_openalex_frontfill_state,
    load_section_frontfill_state,
    primary_section_strategy_quality,
    readiness_level,
    render_markdown,
    run_audit,
    select_section_frontfill_state,
)


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (paper_id TEXT, section_name TEXT, section_text TEXT);
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("",), ("",)])
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("evidence " * 20,))
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (src_paper_id TEXT, dst_paper_id TEXT);
        CREATE TABLE limitation_atoms (paper_id TEXT);
        CREATE TABLE limitation_resolutions (atom_id INTEGER);
        CREATE TABLE fusion_evidence_audit (run_id TEXT, output_directions INTEGER);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER
        );
        CREATE TABLE visual_edges (layer TEXT);
        CREATE TABLE branch_lineages (branch_id TEXT);
        """
    )
    conn.execute("INSERT INTO predicted_future_edges VALUES ('p1', 'p2')")
    conn.execute("INSERT INTO limitation_atoms VALUES ('p1')")
    conn.execute("INSERT INTO visual_edges VALUES ('future')")
    conn.execute("INSERT INTO branch_lineages VALUES ('B1')")
    conn.commit()
    conn.close()


def test_direction_readiness_blocks_raw_gnn_promotion(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)

    metrics = collect_metrics(main, v14)
    blockers = classify_blockers(metrics)

    assert metrics["future_candidate_edges"] == 1
    assert "predicted_future_edges" not in metrics
    assert readiness_level(metrics, blockers) == "candidate_generator_only"
    assert any(b["gate"] == "fusion_materialization" for b in blockers)


def test_direction_readiness_flags_multi_topic_evidence_gap_queue(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    queue = tmp_path / "topic_evidence_gap_delta_queue.csv"
    _make_main(main)
    _make_v14(v14)
    queue.write_text(
        "paper_id,priority_score,reasons\n"
        "p1,100,topic_gap_key_turning_section\n"
        "p2,90,topic_gap_claim_card_inputs\n",
        encoding="utf-8",
    )

    metrics = collect_metrics(main, v14, topic_gap_queue=queue)
    blockers = classify_blockers(metrics)

    assert metrics["topic_gap_queue_papers"] == 2
    assert metrics["topic_gap_primary_section_papers"] == 1
    assert metrics["topic_gap_decision_grade_section_papers"] == 0
    assert any(
        b["gate"] == "multi_topic_evidence_gap"
        and "decision-grade section evidence" in b["why"]
        for b in blockers
    )


def test_direction_readiness_reads_regression_candidate_gap_queue(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    queue = tmp_path / "multi_topic_evidence_gap_queue.csv"
    _make_main(main)
    _make_v14(v14)
    queue.write_text(
        "topic,gap_type,candidate_paper_ids\n"
        "metalens,key_turning,p1;p2\n",
        encoding="utf-8",
    )

    metrics = collect_metrics(main, v14, topic_gap_queue=queue)

    assert metrics["topic_gap_queue_papers"] == 2
    assert metrics["topic_gap_primary_section_papers"] == 1
    assert metrics["topic_gap_decision_grade_section_papers"] == 0


def test_direction_readiness_counts_only_current_contract_gap_sections(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    queue = tmp_path / "topic_evidence_gap_delta_queue.csv"
    conn = sqlite3.connect(str(main))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            parser_name TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "W2")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("p2",)])
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p1', 'discussion', ?, ?, ?)",
        (
            "current contract evidence " * 20,
            "v14b_section_ingest_v3",
            json.dumps(
                {
                    "extraction_strategies": ["explicit_heading"],
                    "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p2', 'discussion', ?, ?, ?)",
        (
            "legacy weak evidence " * 20,
            "v14b_section_ingest_v2",
            json.dumps({"extraction_strategies": ["loose_inline_heading"]}),
        ),
    )
    conn.commit()
    conn.close()
    _make_v14(v14)
    queue.write_text(
        "paper_id,priority_score,reasons\n"
        "p1,100,topic_gap_key_turning_section\n"
        "p2,90,topic_gap_claim_card_inputs\n",
        encoding="utf-8",
    )

    metrics = collect_metrics(main, v14, topic_gap_queue=queue)

    assert metrics["topic_gap_primary_section_papers"] == 2
    assert metrics["topic_gap_decision_grade_section_papers"] == 1
    assert metrics["topic_gap_decision_grade_section_rate"] == 0.5


def test_direction_readiness_tracks_section_parser_provenance(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    conn = sqlite3.connect(str(main))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            parser_name TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "W2")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("p2",)])
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p1', 'discussion', ?, ?, ?)",
        (
            "strong evidence " * 20,
            "v14b_section_ingest_v3",
            '{"extraction_strategies":["explicit_heading"],"parser_contract_version":"v14b_section_parser_contract_v3_toc_guard"}',
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p2', 'conclusion', ?, ?, ?)",
        (
            "weak evidence " * 20,
            "v14b_section_ingest_v2",
            '{"extraction_strategies":["loose_inline_heading"]}',
        ),
    )
    conn.commit()
    conn.close()
    _make_v14(v14)

    quality = primary_section_strategy_quality(sqlite3.connect(str(main)))
    metrics = collect_metrics(main, v14)
    blockers = classify_blockers(metrics)

    assert quality["paper_quality_counts"]["strong"] == 1
    assert quality["paper_quality_counts"]["weak"] == 1
    assert quality["parser_name_counts"]["v14b_section_ingest_v3"] == 1
    assert quality["parser_contract_version_counts"]["v14b_section_parser_contract_v3_toc_guard"] == 1
    assert quality["parser_contract_version_counts"]["legacy_unknown_contract"] == 1
    assert quality["current_contract_papers"] == 1
    assert quality["current_contract_rate"] == 0.5
    assert quality["decision_grade_papers"] == 1
    assert quality["decision_grade_rate"] == 0.5
    assert metrics["section_evidence_quality"]["weak_only_rate"] == 0.5
    assert any(b["gate"] == "section_evidence_provenance" for b in blockers)
    assert any(b["gate"] == "section_parser_contract_coverage" for b in blockers)


def test_direction_readiness_flags_section_frontfill_soft_stall(tmp_path):
    state = tmp_path / "watchdog_state.json"
    state.write_text(
        """
        {
          "done": 1200,
          "total": 12000,
          "rows": 1241,
          "papers": 690,
          "primary_section_papers": 690,
          "current_contract_primary_section_papers": 0,
          "no_evidence_done_delta": 240,
          "no_evidence_elapsed_s": 7200,
          "low_yield_intervals": 2,
          "no_current_contract_done_delta": 240,
          "no_current_contract_elapsed_s": 7200,
          "current_contract_low_yield_intervals": 2,
          "parser_contract_version": "v14b_section_parser_contract_v3_toc_guard"
        }
        """,
        encoding="utf-8",
    )

    metrics = {
        "linked_ref_rate": 0.31,
        "primary_section_papers": 9000,
        "future_candidate_edges": 0,
        "future_directions": 0,
        "direction_claim_cards": 0,
        "complete_claim_cards": 0,
        "openalex_w_rate": 0.72,
        "section_frontfill_state": load_section_frontfill_state(state),
    }
    blockers = classify_blockers(metrics)

    assert metrics["section_frontfill_state"]["status"] == "soft_stall"
    assert metrics["section_frontfill_state"]["current_contract_status"] == "soft_stall"
    assert any(b["gate"] == "section_frontfill_efficiency" for b in blockers)
    assert any(b["gate"] == "section_frontfill_contract_efficiency" for b in blockers)


def test_direction_readiness_infers_soft_stall_from_watchdog_log(tmp_path):
    state = tmp_path / "section_top12000_watchdog_state.json"
    state.write_text(
        '{"done": 1015, "total": 12000, "rows": 1241, "papers": 690, "low_yield_intervals": 0}',
        encoding="utf-8",
    )
    state.with_name("section_top12000_watchdog.log").write_text(
        "[2026-05-29T06:56:02Z] pid=1 status=running rows=1241 papers=690 progress=na\n"
        "[2026-05-29T16:43:54Z] pid=1 status=running rows=1241 papers=690 "
        "done=1015/12000 elapsed_s=33961\n",
        encoding="utf-8",
    )

    loaded = load_section_frontfill_state(state)

    assert loaded["status"] == "soft_stall"
    assert loaded["no_evidence_elapsed_s"] > 9 * 3600


def test_direction_readiness_tracks_openalex_429_cooldown(tmp_path):
    log = tmp_path / "step0_openalex_backfill_20260530_120000.log"
    log.write_text(
        "2026-05-30 12:00:00 [INFO] echelon.v14b.step0_openalex_backfill: OpenAlex backfill targets: 22643\n"
        "2026-05-30 12:30:00 [INFO] echelon.v14b.step0_openalex_backfill: OpenAlex backfill progress: processed=3000/22643 ok=2898 fail=102\n"
        "2026-05-30 12:35:00 [WARNING] echelon.v14b.step0_openalex_backfill: OpenAlex 429, cooldown 7200.0s\n",
        encoding="utf-8",
    )

    loaded = load_openalex_frontfill_state(log, now=datetime(2026, 5, 30, 13, 0, 0))

    assert loaded["status"] == "cooling_down_or_stopped"
    assert loaded["processed"] == 3000
    assert loaded["ok"] == 2898
    assert loaded["cooldown_remaining_s"] == 5700


def test_direction_readiness_uses_latest_openalex_backfill_run(tmp_path):
    log = tmp_path / "openalex_backfill_current.log"
    log.write_text(
        "2026-05-29 10:00:00 [INFO] echelon.v14b.step0_openalex_backfill: OpenAlex backfill targets: 10\n"
        "2026-05-29 10:05:00 [INFO] echelon.v14b.step0_openalex_backfill: OpenAlex backfill done: {'records_n': 8, 'failed': 2}\n"
        "2026-05-30 12:00:00 [INFO] echelon.v14b.step0_openalex_backfill: OpenAlex backfill targets: 22643\n"
        "2026-05-30 12:30:00 [INFO] echelon.v14b.step0_openalex_backfill: OpenAlex backfill progress: processed=3000/22643 ok=2898 fail=102\n"
        "2026-05-30 12:35:00 [WARNING] echelon.v14b.step0_openalex_backfill: OpenAlex 429, cooldown 7200.0s\n",
        encoding="utf-8",
    )

    loaded = load_openalex_frontfill_state(log, now=datetime(2026, 5, 30, 13, 0, 0))

    assert loaded["status"] == "cooling_down_or_stopped"
    assert loaded["targets"] == 22643
    assert loaded["processed"] == 3000


def test_direction_readiness_flags_openalex_frontfill_after_cooldown(tmp_path):
    metrics = {
        "linked_ref_rate": 0.31,
        "primary_section_papers": 9000,
        "future_candidate_edges": 0,
        "future_directions": 0,
        "direction_claim_cards": 0,
        "complete_claim_cards": 0,
        "openalex_w_rate": 0.64,
        "openalex_frontfill_state": {
            "status": "stalled_after_cooldown",
            "processed": 3000,
            "total": 22643,
            "cooldown_remaining_s": 0,
        },
    }

    blockers = classify_blockers(metrics)

    assert any(b["gate"] == "openalex_topic_coverage" for b in blockers)
    health = next(b for b in blockers if b["gate"] == "openalex_frontfill_health")
    assert health["severity"] == "high"


def test_direction_readiness_prefers_active_delta_watchdog_state(tmp_path):
    log_dir = tmp_path / "logs" / "v14b"
    log_dir.mkdir(parents=True)
    (log_dir / "section_top12000_watchdog_state.json").write_text(
        '{"done": 1000, "total": 12000, "rows": 100, "papers": 90}',
        encoding="utf-8",
    )
    (log_dir / "section_delta_watchdog_state.json").write_text(
        '{"done": 20, "total": 12227, "rows": 200, "papers": 190}',
        encoding="utf-8",
    )

    loaded = select_section_frontfill_state(tmp_path)

    assert loaded["source"] == "section_delta"
    assert loaded["done"] == 20


def test_direction_readiness_uses_live_section_progress_log(tmp_path):
    log_dir = tmp_path / "logs" / "v14b"
    log_dir.mkdir(parents=True)
    (log_dir / "section_delta_watchdog_state.json").write_text(
        '{"done": 20, "total": 6603, "rows": 200, "papers": 190}',
        encoding="utf-8",
    )
    (log_dir / "step5s_section_delta.log").write_text(
        "\rStep5s sections:  13%| | 877/6603 [7:42:25<7:04:04,  4.44s/it, parsed=357]\n",
        encoding="utf-8",
    )

    loaded = select_section_frontfill_state(tmp_path)

    assert loaded["source"] == "section_delta"
    assert loaded["state_done"] == 20
    assert loaded["done"] == 877
    assert loaded["progress_latest_done"] == 877
    assert loaded["progress_log"].endswith("step5s_section_delta.log")


def test_latest_fusion_audit_renders_candidate_score_labels():
    public = _public_latest_fusion_audit(
        {
            "run_id": "r1",
            "n_vgae_preds_top": 500,
            "n_vgae_preds_total": 1000,
            "n_cross_field_total": 60,
            "n_unresolved": 50,
            "n_candidates": 5,
            "n_directions": 2,
            "calibration_json": (
                '{"prediction_confidence_avg": 0.83, "min_vgae_confidence": 0.55, '
                '"vgae_top_n": 500, "labels": {"calibrated_temporal_holdout": 2}}'
            ),
        }
    )

    assert public["candidate_edges_used"] == 500
    assert public["future_candidate_edges_total"] == 1000
    assert public["calibration_summary"]["candidate_ranking_score_avg"] == 0.83
    assert public["calibration_summary"]["min_candidate_score_threshold"] == 0.55
    assert "prediction_confidence_avg" not in str(public)
    assert "min_vgae_confidence" not in str(public)


def test_direction_readiness_report_hides_legacy_prediction_confidence_copy():
    metrics = {
        "linked_refs": 30,
        "refs": 100,
        "linked_ref_rate": 0.3,
        "openalex_w": 70,
        "openalex_w_rate": 0.7,
        "section_rows": 100,
        "section_papers": 50,
        "primary_section_papers": 40,
        "primary_section_rate": 0.4,
        "section_evidence_quality": {"strong_or_moderate_papers": 30, "weak_only_rate": 0.25},
        "topic_gap_primary_section_papers": 0,
        "topic_gap_queue_papers": 0,
        "topic_gap_primary_section_rate": 0.0,
        "future_candidate_edges": 1000,
        "future_visual_edges": 1000,
        "future_directions": 2,
        "direction_claim_cards": 2,
        "complete_claim_cards": 1,
        "high_confidence_claim_cards": 0,
        "latest_fusion": {
            "run_id": "r1",
            "n_vgae_preds_top": 500,
            "n_vgae_preds_total": 1000,
            "calibration_json": '{"prediction_confidence_avg": 0.83, "min_vgae_confidence": 0.55}',
        },
    }

    md = render_markdown(metrics, [], "actionable_but_not_high_confidence")

    assert "candidate_ranking_score_avg" in md
    assert "min_candidate_score_threshold" in md
    assert "current section parser contract" in md
    assert "prediction_confidence_avg" not in md
    assert "min_vgae_confidence" not in md


def test_direction_readiness_writes_report(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)

    result = run_audit(main, v14, tmp_path / "reports")

    assert result["readiness_level"] == "candidate_generator_only"
    assert (tmp_path / "reports" / "direction_readiness_audit.md").exists()
