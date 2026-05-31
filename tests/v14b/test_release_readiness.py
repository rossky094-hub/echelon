import json
import sqlite3

from echelon.v14b.release_readiness import build_release_readiness, run_release_readiness


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_db(path, *, with_section_embeddings=False, high_confidence_cards=0):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE paper_sections (paper_id TEXT)")
    conn.execute("CREATE TABLE section_atoms (atom_id TEXT)")
    conn.execute("CREATE TABLE section_atom_embeddings (atom_id TEXT)")
    conn.execute("INSERT INTO paper_sections VALUES ('p1')")
    conn.execute("INSERT INTO section_atoms VALUES ('a1')")
    conn.execute("INSERT INTO section_atom_embeddings VALUES ('a1')")
    if with_section_embeddings:
        conn.execute("CREATE TABLE section_embeddings (section_id TEXT)")
        conn.execute("INSERT INTO section_embeddings VALUES ('s1')")
    conn.commit()
    conn.close()

    v14_path = path.with_name("v14.sqlite3")
    conn = sqlite3.connect(v14_path)
    conn.execute("CREATE TABLE direction_claim_cards (claim_card_id TEXT, high_confidence_eligible INTEGER)")
    for idx in range(high_confidence_cards):
        conn.execute("INSERT INTO direction_claim_cards VALUES (?, 1)", (f"cc{idx}",))
    conn.commit()
    conn.close()
    return v14_path


def _write_audit_reports(report_dir, *, all_pass=False):
    report_dir.mkdir(parents=True)
    _write_json(
        report_dir / "value_delivery_audit.json",
        {
            "evidence_policy": "insufficient_evidence" if not all_pass else "decision_grade_available",
            "summary": {"fail": 0 if all_pass else 1, "pass": 15 if all_pass else 13, "warn": 0 if all_pass else 1},
            "metrics": {"section_frontfill_status": "running_or_unknown", "section_frontfill_done": 10, "section_frontfill_total": 100},
            "gates": [
                {
                    "issue": "Legacy Flow Isolation Contract",
                    "status": "pass",
                    "checks": {"post_frontfill_runs_decision_audit": True},
                    "policy": "fixture",
                },
                {
                    "issue": "Evidence Bone",
                    "status": "pass" if all_pass else "warn",
                    "policy": "fixture evidence boundary",
                },
                {
                    "issue": "Multi-topic Regression",
                    "status": "pass" if all_pass else "fail",
                    "topic_gap_blocking": not all_pass,
                    "policy": "fixture multi-topic boundary",
                },
            ],
        },
    )
    _write_json(
        report_dir / "direction_readiness_audit.json",
        {
            "readiness_level": "decision_grade_available" if all_pass else "actionable_but_not_high_confidence",
            "metrics": {"high_confidence_claim_cards": 1 if all_pass else 0},
            "blockers": []
            if all_pass
            else [
                {
                    "gate": "citation_graph_bone",
                    "severity": "high",
                    "why": "linked refs below threshold",
                    "next_action": "exact relink",
                }
            ],
        },
    )
    _write_json(report_dir / "algorithm_logic_audit.json", {"status_counts": {"algorithm_fit": {"aligned": 22}}})
    _write_json(
        report_dir / "path_challenge_audit.json",
        {
            "overall_status": "path_aligned" if all_pass else "redirect_evidence_first",
            "verdict_counts": {"aligned": 1} if all_pass else {"hold": 2, "redirect": 1},
        },
    )
    _write_json(
        report_dir / "evidence_repair_priority.json",
        {
            "overall_status": "no_blocking_repair" if all_pass else "evidence_first_repair_required",
            "summary": {"items": 0 if all_pass else 2, "blocking_p0": 0 if all_pass else 2},
            "priority_items": []
            if all_pass
            else [
                {
                    "rank": 1,
                    "priority": "P0",
                    "action_id": "topic_gap_evidence_repair",
                    "command": "make topic-gap-repair",
                    "requires_db_writer_boundary": True,
                    "can_run_while_broad_ingest_active": False,
                }
            ],
        },
    )
    _write_json(report_dir / "raw_pdf_store_audit.json", {"status": "pass"})
    _write_json(
        report_dir / "multi_topic_regression.json",
        [{"topic": "metalens", "overall_status": "pass" if all_pass else "fail"}],
    )


def test_release_readiness_holds_when_section_embeddings_and_multi_topic_gate_are_open(tmp_path):
    report_dir = tmp_path / "reports"
    _write_audit_reports(report_dir, all_pass=False)
    db_main = tmp_path / "main.sqlite3"
    db_v14 = _make_db(db_main, with_section_embeddings=False)

    result = build_release_readiness(db_main=db_main, db_v14=db_v14, report_dir=report_dir, repo_root=tmp_path)

    assert result["release_status"] == "evidence_gated_not_release_ready"
    assert result["acceptance_ready"] is False
    assert result["checks"]["section_embeddings_materialized"] is False
    assert result["checks"]["multi_topic_regression_passed"] is False
    assert result["checks"]["path_challenge_audit_available"] is True
    assert result["path_challenge_status"] == "redirect_evidence_first"
    assert result["evidence_repair_priority_status"] == "evidence_first_repair_required"
    assert result["evidence_repair_top_actions"][0]["action_id"] == "topic_gap_evidence_repair"
    commands = {item["command"] for item in result["next_actions"]}
    assert "make post-frontfill-chain" in commands
    assert "make topic-gap-repair" in commands


def test_release_readiness_can_be_decision_grade_when_all_current_gates_are_closed(tmp_path):
    report_dir = tmp_path / "reports"
    _write_audit_reports(report_dir, all_pass=True)
    db_main = tmp_path / "main.sqlite3"
    db_v14 = _make_db(db_main, with_section_embeddings=True, high_confidence_cards=1)

    result = run_release_readiness(db_main=db_main, db_v14=db_v14, out_dir=report_dir, repo_root=tmp_path)

    assert result["release_status"] == "decision_grade_release_candidate"
    assert result["acceptance_ready"] is True
    assert result["path_challenge_status"] == "path_aligned"
    assert result["evidence_repair_priority_status"] == "no_blocking_repair"
    assert (report_dir / "release_readiness.json").exists()
    md = (report_dir / "release_readiness.md").read_text(encoding="utf-8")
    assert "Evidence Repair Priority" in md
    assert "Product Boundary" in md
    assert "graph renderability" in md
