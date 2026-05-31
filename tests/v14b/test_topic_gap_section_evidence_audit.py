from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.topic_gap_section_evidence_audit import (
    load_topic_gap_section_triage_state,
    run_topic_gap_section_evidence_audit,
)


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            publication_year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            openalex_id TEXT,
            s2_paper_id TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            parser_name TEXT,
            source_url TEXT,
            section_meta_json TEXT
        );
        CREATE TABLE section_ingest_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT,
            attempt_ts TEXT,
            outcome TEXT,
            source_url TEXT,
            detail TEXT,
            inserted_sections INTEGER,
            primary_sections INTEGER,
            candidate_file TEXT,
            parser_name TEXT,
            parser_contract_version TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("p_decision", "Decision grade paper", 2020, "2001.00001", "10/a", "W1", "S1"),
            ("p_weak", "Weak current paper", 2021, "2001.00002", "10/b", "W2", "S2"),
            ("p_stale", "Stale parser paper", 2019, "2001.00003", "10/c", "W3", "S3"),
            ("p_notarget", "No target section paper", 2018, "2001.00004", "10/d", "W4", "S4"),
            ("p_unattempted", "Unattempted PDF paper", 2022, "2001.00005", "10/e", "W5", "S5"),
        ],
    )
    current_explicit = json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["explicit_heading"],
        }
    )
    current_weak = json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["loose_inline_heading"],
        }
    )
    legacy_explicit = json.dumps({"extraction_strategies": ["explicit_heading"]})
    conn.executemany(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                "p_decision",
                "discussion",
                "decision-grade section evidence " * 10,
                "v14b_section_ingest_v3",
                "https://arxiv.org/pdf/2001.00001.pdf",
                current_explicit,
            ),
            (
                "p_weak",
                "discussion",
                "weak current parser evidence " * 10,
                "v14b_section_ingest_v3",
                "https://arxiv.org/pdf/2001.00002.pdf",
                current_weak,
            ),
            (
                "p_stale",
                "conclusion",
                "legacy parser evidence " * 10,
                "v14b_section_ingest_v2",
                "https://arxiv.org/pdf/2001.00003.pdf",
                legacy_explicit,
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO section_ingest_attempts
            (paper_id, attempt_ts, outcome, source_url, detail, inserted_sections,
             primary_sections, candidate_file, parser_name, parser_contract_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "p_notarget",
                "2026-05-31T00:00:00Z",
                "no_target_sections",
                "https://arxiv.org/pdf/2001.00004.pdf",
                "PDF parsed, but no target evidence sections were detected.",
                0,
                0,
                "data/v14b/topic_evidence_gap_delta_queue.csv",
                "v14b_section_ingest_v3",
                SECTION_PARSER_CONTRACT_VERSION,
            )
        ],
    )
    conn.commit()
    conn.close()


def _write_queue(path: Path) -> None:
    fieldnames = [
        "paper_id",
        "priority_score",
        "reasons",
        "eligible_pdf",
        "source_url",
        "title",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for idx, pid in enumerate(
            ["p_decision", "p_weak", "p_stale", "p_notarget", "p_unattempted"],
            start=1,
        ):
            writer.writerow(
                {
                    "paper_id": pid,
                    "priority_score": 100 - idx,
                    "reasons": "topic:metalens|topic_gap:metalens:key_turning_paper_missing_primary_section",
                    "eligible_pdf": "True",
                    "source_url": f"https://arxiv.org/pdf/2001.0000{idx}.pdf",
                    "title": pid,
                }
            )


def test_topic_gap_section_audit_classifies_repair_buckets(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)
    _write_queue(queue)

    result = run_topic_gap_section_evidence_audit(
        db_main=db,
        topic_gap_queue=queue,
        out_dir=out_dir,
    )

    counts = result["summary"]["failure_mode_counts"]
    assert result["summary"]["status"] == "fail"
    assert result["summary"]["decision_grade_current_contract_papers"] == 1
    assert result["summary"]["promotion_ready_papers"] == 1
    assert counts["decision_grade_current_contract"] == 1
    assert counts["current_contract_weak"] == 1
    assert counts["stale_parser_contract"] == 1
    assert counts["no_target_sections_after_current_parser"] == 1
    assert counts["unattempted_pdf_available"] == 1
    assert result["summary"]["topic_summary"]["metalens"]["papers"] == 5
    assert (out_dir / "topic_gap_section_evidence_audit.md").exists()
    assert (out_dir / "topic_gap_section_evidence_audit.csv").exists()


def test_topic_gap_section_audit_ignores_local_cache_miss_when_parser_attempt_exists(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)
    _write_queue(queue)

    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        INSERT INTO section_ingest_attempts
            (paper_id, attempt_ts, outcome, source_url, detail, inserted_sections,
             primary_sections, candidate_file, parser_name, parser_contract_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "p_notarget",
            "2026-05-31T01:00:00Z",
            "no_local_raw_pdf",
            "",
            "Local raw PDF only mode is enabled and no reusable cache hit was found.",
            0,
            0,
            "reports/v14b_pilot/multi_topic_evidence_gap_queue.csv",
            "v14b_section_ingest_v3",
            SECTION_PARSER_CONTRACT_VERSION,
        ),
    )
    conn.commit()
    conn.close()

    result = run_topic_gap_section_evidence_audit(
        db_main=db,
        topic_gap_queue=queue,
        out_dir=out_dir,
    )

    row = next(item for item in result["rows"] if item["paper_id"] == "p_notarget")
    assert row["latest_attempt_outcome"] == "no_target_sections"
    assert row["failure_mode"] == "no_target_sections_after_current_parser"


def test_topic_gap_section_audit_triages_lineage_atom_chain_blockers(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "multi_topic_evidence_gap_queue.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)
    conn = sqlite3.connect(str(db))
    current_explicit = json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["explicit_heading"],
        }
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("p_atomized", "Atomized paper", 2020, "2001.10001", "10/f", "W6", "S6"),
            ("p_partial", "Partial chain paper", 2020, "2001.10002", "10/g", "W7", "S7"),
            ("p_full", "Full chain mismatch paper", 2020, "2001.10003", "10/h", "W8", "S8"),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                pid,
                "discussion",
                "decision-grade section evidence " * 10,
                "v14b_section_ingest_v3",
                f"https://arxiv.org/pdf/{arxiv}.pdf",
                current_explicit,
            )
            for pid, arxiv in (
                ("p_atomized", "2001.10001"),
                ("p_partial", "2001.10002"),
                ("p_full", "2001.10003"),
            )
        ],
    )
    conn.executescript(
        """
        CREATE TABLE section_atoms (
            paper_id TEXT,
            atom_type TEXT,
            evidence_grade TEXT
        );
        CREATE TABLE section_atom_chains (
            paper_id TEXT,
            chain_id TEXT,
            typed_chain_complete INTEGER,
            typed_chain_completeness TEXT,
            missing_stages_json TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO section_atoms VALUES (?, ?, ?)",
        [
            ("p_atomized", "constraint", "section_atom_decision_grade"),
            ("p_partial", "constraint", "section_atom_decision_grade"),
            ("p_partial", "failure_mechanism", "section_atom_decision_grade"),
            ("p_full", "constraint", "section_atom_decision_grade"),
            ("p_full", "failure_mechanism", "section_atom_decision_grade"),
        ],
    )
    conn.executemany(
        "INSERT INTO section_atom_chains VALUES (?, ?, ?, ?, ?)",
        [
            (
                "p_partial",
                "sac_partial",
                0,
                "constraint_failure_only",
                json.dumps(["attempted_path", "local_fix", "new_constraint"]),
            ),
            ("p_full", "sac_full", 1, "full", "[]"),
        ],
    )
    conn.commit()
    conn.close()
    queue.write_text(
        "\n".join(
            [
                "topic,gap_type,bottleneck,priority,candidate_paper_ids,frontfill_query,required_sections,why,source_contract,repair_id,target_pipeline_steps,claim_scope,evidence_grade",
                (
                    "metalens,bottleneck_lineage_missing_topic_specific_typed_chain,efficiency,97,"
                    "p_decision;p_atomized;p_partial;p_full,metalens efficiency,limitation,chain,"
                    "topic_dossier_evidence_repair_plan,repair-lineage,section-atom-chains,"
                    "evidence_repair_queue_only,frontfill_target"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_topic_gap_section_evidence_audit(
        db_main=db,
        topic_gap_queue=queue,
        out_dir=out_dir,
    )

    by_pid = {row["paper_id"]: row for row in result["rows"]}
    assert by_pid["p_decision"]["failure_mode"] == "lineage_atoms_missing_after_section_evidence"
    assert by_pid["p_atomized"]["failure_mode"] == "lineage_chains_missing_after_atoms"
    assert by_pid["p_partial"]["failure_mode"] == "lineage_full_chain_missing"
    assert by_pid["p_partial"]["section_atom_chain_missing_stages"] == {
        "attempted_path": 1,
        "local_fix": 1,
        "new_constraint": 1,
    }
    assert by_pid["p_partial"]["section_atom_chain_missing_stage_examples"][0]["chain_id"] == "sac_partial"
    assert "attempted_path:1" in by_pid["p_partial"]["next_action"]
    assert by_pid["p_full"]["failure_mode"] == "topic_specific_lineage_chain_mismatch"
    assert by_pid["p_full"]["repair_contract_ids"] == ["repair-lineage"]
    assert by_pid["p_full"]["repair_closure_states"] == ["open_topic_chain_mismatch"]
    assert result["summary"]["decision_grade_current_contract_papers"] == 4
    assert result["summary"]["promotion_ready_papers"] == 0
    assert result["summary"]["promotion_policy_counts"]["candidate_pool_only"] == 4
    assert result["summary"]["lineage_failure_mode_counts"]["lineage_full_chain_missing"] == 1
    assert result["summary"]["lineage_missing_stage_counts"] == {
        "attempted_path": 1,
        "local_fix": 1,
        "new_constraint": 1,
    }


def test_topic_gap_section_audit_reports_repair_contract_closure(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "repair_queue.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)

    conn = sqlite3.connect(str(db))
    current_explicit = json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["explicit_heading"],
        }
    )
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("p_chain", "Chain paper", 2024, "2001.20001", "10/chain", "W9", "S9"),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p_chain",
            "discussion",
            "decision-grade section evidence " * 10,
            "v14b_section_ingest_v3",
            "https://arxiv.org/pdf/2001.20001.pdf",
            current_explicit,
        ),
    )
    conn.executescript(
        """
        CREATE TABLE section_atoms (
            paper_id TEXT,
            atom_type TEXT,
            evidence_grade TEXT
        );
        CREATE TABLE section_atom_chains (
            paper_id TEXT,
            typed_chain_complete INTEGER,
            typed_chain_completeness TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO section_atoms VALUES (?, ?, ?)",
        [
            ("p_decision", "constraint", "section_atom_decision_grade"),
            ("p_chain", "constraint", "section_atom_decision_grade"),
            ("p_chain", "failure_mechanism", "section_atom_decision_grade"),
        ],
    )
    conn.execute("INSERT INTO section_atom_chains VALUES (?, ?, ?)", ("p_chain", 1, "full"))
    conn.commit()
    conn.close()

    queue.write_text(
        "\n".join(
            [
                "paper_id,priority_score,reasons,eligible_pdf,source_url,title,source_contract,repair_id,target_pipeline_steps,claim_scope,evidence_grade",
                "p_decision,100,topic:metalens|topic_gap:metalens:missing_bottleneck_section_evidence,True,https://arxiv.org/pdf/2001.00001.pdf,p_decision,topic_dossier_evidence_repair_plan,repair-atoms,section-atoms,evidence_repair_queue_only,frontfill_target",
                "p_chain,99,topic:metalens|topic_gap:metalens:missing_bottleneck_section_evidence,True,https://arxiv.org/pdf/2001.20001.pdf,p_chain,topic_dossier_evidence_repair_plan,repair-chain,section-atom-chains,evidence_repair_queue_only,frontfill_target",
                "p_stale,98,topic:metalens|topic_gap:metalens:missing_bottleneck_section_evidence,True,https://arxiv.org/pdf/2001.00003.pdf,p_stale,topic_dossier_evidence_repair_plan,repair-stale,section-atoms,evidence_repair_queue_only,frontfill_target",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_topic_gap_section_evidence_audit(
        db_main=db,
        topic_gap_queue=queue,
        out_dir=out_dir,
    )

    closure = result["summary"]["repair_contract_closure"]
    assert closure["contracts"] == 3
    assert closure["closed_contracts"] == 2
    assert closure["closure_state_counts"]["closed_section_atoms_available"] == 1
    assert closure["closure_state_counts"]["closed_typed_chain_available"] == 1
    assert closure["closure_state_counts"]["open_section_evidence_not_decision_grade"] == 1
    by_pid = {row["paper_id"]: row for row in result["rows"]}
    assert by_pid["p_chain"]["repair_closure_states"] == ["closed_typed_chain_available"]
    assert by_pid["p_stale"]["repair_contract_ids"] == ["repair-stale"]
    state = load_topic_gap_section_triage_state(out_dir / "topic_gap_section_evidence_audit.json")
    assert state["repair_contract_closure"]["closed_contracts"] == 2


def test_topic_gap_section_triage_loader_exposes_summary(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)
    _write_queue(queue)
    run_topic_gap_section_evidence_audit(db_main=db, topic_gap_queue=queue, out_dir=out_dir)

    state = load_topic_gap_section_triage_state(
        out_dir / "topic_gap_section_evidence_audit.json"
    )

    assert state["available"] is True
    assert state["queue_papers"] == 5
    assert state["failure_mode_counts"]["no_target_sections_after_current_parser"] == 1
    assert "before high-confidence promotion" in state["next_action"]
