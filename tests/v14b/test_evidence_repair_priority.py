from __future__ import annotations

import json
import sqlite3

from echelon.v14b.evidence_repair_priority import (
    build_evidence_repair_priority,
    run_evidence_repair_priority,
)


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_dbs(tmp_path, *, with_section_embeddings=False):
    main = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(main)
    conn.execute("CREATE TABLE paper_sections (paper_id TEXT)")
    conn.execute("CREATE TABLE section_atoms (atom_id TEXT)")
    conn.execute("CREATE TABLE section_atom_embeddings (atom_id TEXT)")
    conn.execute("CREATE TABLE section_atom_chains (chain_id TEXT)")
    conn.execute("INSERT INTO paper_sections VALUES ('p1')")
    conn.execute("INSERT INTO section_atoms VALUES ('a1')")
    conn.execute("INSERT INTO section_atom_embeddings VALUES ('a1')")
    conn.execute("INSERT INTO section_atom_chains VALUES ('c1')")
    if with_section_embeddings:
        conn.execute("CREATE TABLE section_embeddings (section_key TEXT)")
        conn.execute("INSERT INTO section_embeddings VALUES ('p1:discussion')")
    conn.commit()
    conn.close()

    v14 = tmp_path / "v14.sqlite3"
    conn = sqlite3.connect(v14)
    conn.execute("CREATE TABLE direction_claim_cards (claim_card_id TEXT)")
    conn.commit()
    conn.close()
    return main, v14


def _write_reports(report_dir, *, ready=False):
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "value_delivery_audit.json",
        {
            "summary": {"fail": 0 if ready else 1, "pass": 14, "warn": 0 if ready else 1},
            "gates": [
                {
                    "issue": "Multi-topic Regression",
                    "status": "pass" if ready else "fail",
                    "topic_gap_blocking": not ready,
                    "topic_gap_decision_grade_section_rate": 1.0 if ready else 0.57,
                }
            ],
        },
    )
    _write_json(
        report_dir / "direction_readiness_audit.json",
        {
            "readiness_level": "decision_grade_available" if ready else "actionable_but_not_high_confidence",
            "metrics": {
                "linked_ref_rate": 0.40 if ready else 0.14,
                "openalex_w_rate": 0.80 if ready else 0.64,
            },
        },
    )
    _write_json(
        report_dir / "release_readiness.json",
        {
            "release_status": "decision_grade_release_candidate" if ready else "evidence_gated_not_release_ready",
            "acceptance_ready": ready,
            "checks": {"section_embeddings_materialized": ready},
        },
    )
    _write_json(
        report_dir / "path_challenge_audit.json",
        {"overall_status": "path_aligned" if ready else "redirect_evidence_first"},
    )
    _write_json(
        report_dir / "raw_pdf_store_audit.json",
        {
            "status": "pass",
            "manifest": {
                "status": "ok",
                "success_papers": 5000 if not ready else 0,
                "total_manifest_rows": 55000 if not ready else 0,
                "success_probable_pdf_rate": 1.0,
                "status_counts": {"queued": {"papers": 50000 if not ready else 0}},
            },
            "candidate_queue_coverage": {
                "queue_papers": 78 if not ready else 0,
                "raw_pdf_available_papers": 15 if not ready else 0,
                "raw_pdf_available_rate": 0.19 if not ready else 1.0,
            },
        },
    )
    _write_json(
        report_dir / "topic_gap_repair_execution_plan.json",
        {
            "summary": {
                "contracts": 215 if not ready else 0,
                "open_contracts": 198 if not ready else 0,
                "closed_contracts": 17 if not ready else 0,
                "quick_close_contracts": 12 if not ready else 0,
                "local_raw_pdf_ingest_contracts": 52 if not ready else 0,
                "closure_state_counts": {"open_section_evidence_not_decision_grade": 118}
                if not ready
                else {},
                "action_group_counts": {"targeted_local_raw_pdf_ingest_when_safe": 52}
                if not ready
                else {},
            },
            "action_groups": [],
        },
    )
    _write_json(
        report_dir / "topic_gap_stage_candidate_recall.json",
        {
            "summary": {
                "candidate_tasks": 219 if not ready else 0,
                "same_paper_candidate_hits": 452 if not ready else 0,
                "tasks_with_same_paper_candidates": 150 if not ready else 0,
                "missing_stage_counts": {"local_fix": 57} if not ready else {},
            }
        },
    )
    _write_json(
        report_dir / "cited_work_backfill_queue.json",
        {
            "queue_rows": 2000 if not ready else 0,
            "provider_counts": {"doi": 903, "openalex": 1051} if not ready else {},
        },
    )


def test_evidence_repair_priority_orders_p0_retrieval_and_topic_gap_repairs(tmp_path):
    reports = tmp_path / "reports"
    _write_reports(reports, ready=False)
    main, v14 = _make_dbs(tmp_path, with_section_embeddings=False)

    result = build_evidence_repair_priority(
        db_main=main,
        db_v14=v14,
        report_dir=reports,
        repo_root=tmp_path,
    )

    assert result["overall_status"] == "evidence_first_repair_required"
    assert result["contract"]["section_atomization_layer"]["forbidden_methods"] == [
        "GNN/VGAE atom generation"
    ]
    assert "candidate recall only" in result["contract"]["dual_retrieval_layer"]["fuzzy"]
    action_ids = [item["action_id"] for item in result["priority_items"]]
    assert action_ids[:3] == [
        "topic_gap_evidence_repair",
        "post_frontfill_retrieval_rebuild",
        "typed_stage_candidate_review",
    ]
    top = result["priority_items"][0]
    assert top["priority"] == "P0"
    assert top["requires_db_writer_boundary"] is True
    typed_stage = next(item for item in result["priority_items"] if item["action_id"] == "typed_stage_candidate_review")
    assert typed_stage["can_run_while_broad_ingest_active"] is True
    assert result["safe_boundary_policy"]["current_target_is_read_only"] is True


def test_run_evidence_repair_priority_writes_reports_and_can_be_idle(tmp_path):
    reports = tmp_path / "reports"
    _write_reports(reports, ready=True)
    main, v14 = _make_dbs(tmp_path, with_section_embeddings=True)

    result = run_evidence_repair_priority(
        db_main=main,
        db_v14=v14,
        out_dir=reports,
        repo_root=tmp_path,
    )

    assert result["overall_status"] == "no_blocking_repair"
    assert result["priority_items"] == []
    assert (reports / "evidence_repair_priority.json").exists()
    assert (reports / "evidence_repair_priority.md").exists()
    assert (reports / "evidence_repair_priority.csv").exists()
    md = (reports / "evidence_repair_priority.md").read_text(encoding="utf-8")
    assert "GNN/VGAE may expand or rank candidates only" in md
