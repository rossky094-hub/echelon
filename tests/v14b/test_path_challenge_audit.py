import json
import sqlite3

from echelon.v14b.path_challenge_audit import build_path_challenge_audit, run_path_challenge_audit


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_dbs(tmp_path, *, section_embeddings=False, high_confidence_cards=0):
    main = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(main)
    conn.execute("CREATE TABLE section_atoms (atom_id TEXT)")
    conn.execute("CREATE TABLE section_atom_embeddings (atom_id TEXT)")
    conn.execute("INSERT INTO section_atoms VALUES ('a1')")
    conn.execute("INSERT INTO section_atom_embeddings VALUES ('a1')")
    if section_embeddings:
        conn.execute("CREATE TABLE section_embeddings (section_id TEXT)")
        conn.execute("INSERT INTO section_embeddings VALUES ('s1')")
    conn.commit()
    conn.close()

    v14 = tmp_path / "v14.sqlite3"
    conn = sqlite3.connect(v14)
    conn.execute("CREATE TABLE direction_claim_cards (claim_card_id TEXT)")
    for idx in range(high_confidence_cards):
        conn.execute("INSERT INTO direction_claim_cards VALUES (?)", (f"cc{idx}",))
    conn.commit()
    conn.close()
    return main, v14


def _write_reports(report_dir, *, ready=False):
    report_dir.mkdir()
    _write_json(
        report_dir / "value_delivery_audit.json",
        {
            "summary": {"fail": 0 if ready else 1, "pass": 15 if ready else 13, "warn": 0 if ready else 1},
            "gates": [
                {"issue": "Evidence Bone", "status": "pass" if ready else "warn"},
                {
                    "issue": "Multi-topic Regression",
                    "status": "pass" if ready else "fail",
                    "topic_gap_blocking": not ready,
                    "topic_gap_decision_grade_section_rate": 1.0 if ready else 0.5,
                },
            ],
        },
    )
    _write_json(
        report_dir / "direction_readiness_audit.json",
        {
            "metrics": {
                "linked_ref_rate": 0.45 if ready else 0.14,
                "openalex_w_rate": 0.80 if ready else 0.64,
                "high_confidence_claim_cards": 1 if ready else 0,
            }
        },
    )
    _write_json(report_dir / "algorithm_logic_audit.json", {"status_counts": {"algorithm_fit": {"aligned": 22}}})
    _write_json(report_dir / "release_readiness.json", {"release_status": "decision_grade_release_candidate" if ready else "evidence_gated_not_release_ready", "acceptance_ready": ready, "checks": {"section_embeddings_materialized": ready}})
    _write_json(report_dir / "multi_topic_regression.json", [{"overall_status": "pass" if ready else "fail"}])
    _write_json(report_dir / "raw_pdf_store_audit.json", {"status": "pass"})


def test_path_challenge_redirects_when_evidence_path_is_not_ready(tmp_path):
    main, v14 = _make_dbs(tmp_path, section_embeddings=False)
    reports = tmp_path / "reports"
    _write_reports(reports, ready=False)

    result = build_path_challenge_audit(db_main=main, db_v14=v14, report_dir=reports)

    assert result["overall_status"] == "redirect_evidence_first"
    verdicts = {row["area"]: row["verdict"] for row in result["challenges"]}
    assert verdicts["evidence_acquisition_strategy"] == "redirect"
    assert verdicts["retrieval_substrate"] == "hold"
    assert verdicts["future_to_radar"] == "hold"
    assert "green tests" not in result["policy"].lower()
    better_paths = " ".join(row["better_path"] for row in result["challenges"])
    assert "topic-gap-repair" in better_paths
    assert "post-frontfill-chain" in better_paths


def test_path_challenge_can_be_aligned_when_gates_are_closed(tmp_path):
    main, v14 = _make_dbs(tmp_path, section_embeddings=True, high_confidence_cards=1)
    reports = tmp_path / "reports"
    _write_reports(reports, ready=True)

    result = run_path_challenge_audit(db_main=main, db_v14=v14, out_dir=reports)

    assert result["overall_status"] == "path_aligned"
    assert result["verdict_counts"] == {"aligned": 6}
    assert (reports / "path_challenge_audit.json").exists()
    md = (reports / "path_challenge_audit.md").read_text(encoding="utf-8")
    assert "First-Principles Path Challenge" in md
    assert "Better path" in md
