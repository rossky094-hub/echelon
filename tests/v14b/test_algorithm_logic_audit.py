from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from echelon.v14b.algorithm_logic_audit import run_algorithm_logic_audit


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_embeddings (paper_id TEXT);
        CREATE TABLE paper_sections (paper_id TEXT, section_name TEXT, section_text TEXT);
        CREATE TABLE section_atoms (
            atom_id TEXT PRIMARY KEY,
            paper_id TEXT,
            evidence_grade TEXT,
            claim_scope TEXT
        );
        CREATE VIRTUAL TABLE section_atoms_fts USING fts5(atom_id UNINDEXED, atom_text);
        CREATE TABLE section_atom_embeddings (
            atom_id TEXT PRIMARY KEY,
            paper_id TEXT,
            embedding_model TEXT,
            embedding_dim INTEGER,
            embedding_json TEXT,
            source_text_hash TEXT,
            claim_scope TEXT,
            search_semantics TEXT
        );
        CREATE TABLE section_atom_chains (
            chain_id TEXT PRIMARY KEY,
            paper_id TEXT,
            typed_chain_complete INTEGER,
            evidence_grade TEXT,
            claim_scope TEXT
        );
        CREATE TABLE corpus_registry (corpus_id TEXT PRIMARY KEY);
        CREATE TABLE corpus_snapshots (snapshot_id TEXT PRIMARY KEY, corpus_id TEXT);
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("",), ("",)])
    conn.executemany("INSERT INTO paper_embeddings VALUES (?)", [("p1",), ("p2",)])
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("section evidence " * 20,))
    conn.execute("INSERT INTO section_atoms VALUES ('sa1', 'p1', 'section_atom_decision_grade', 'retrieval_context_only')")
    conn.execute("INSERT INTO section_atoms_fts VALUES ('sa1', 'section evidence atom')")
    conn.execute(
        """
        INSERT INTO section_atom_embeddings VALUES (
            'sa1', 'p1', 'deterministic_hashing_atom_embedding_v1', 256, '[1.0]',
            'hash', 'retrieval_context_only',
            'candidate recall only; retrieval_context_only; not a Topic Dossier or Claim Card conclusion'
        )
        """
    )
    conn.execute(
        "INSERT INTO section_atom_chains VALUES ('sac1', 'p1', 1, 'typed_section_lineage', 'bottleneck_lineage_evidence')"
    )
    conn.execute("INSERT INTO corpus_registry VALUES ('optics')")
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE main_path_edges (is_main_path INTEGER);
        CREATE TABLE subgraph_nodes (paper_id TEXT);
        CREATE TABLE subgraph_edges (citation_function TEXT);
        CREATE TABLE predicted_future_edges (src_paper_id TEXT, dst_paper_id TEXT);
        CREATE TABLE vgae_calibration_audit (method TEXT);
        CREATE TABLE limitation_atoms (
            paper_id TEXT,
            source_section_name TEXT,
            source_section_atom_id TEXT,
            source_parser_contract_version TEXT,
            source_section_atom_chain_id TEXT,
            evidence_quality TEXT
        );
        CREATE TABLE limitation_resolutions (atom_id INTEGER);
        CREATE TABLE fusion_evidence_audit (run_id TEXT);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        CREATE TABLE visual_nodes (paper_id TEXT);
        CREATE TABLE visual_edges (layer TEXT);
        CREATE TABLE branch_lineages (branch_id TEXT);
        CREATE TABLE mutation_hypotheses (
            hypothesis_id TEXT,
            evidence_grade TEXT,
            claim_scope TEXT,
            uncertainty_reasons_json TEXT,
            falsification_conditions_json TEXT
        );
        CREATE TABLE bottleneck_lineage_triples (
            source_stage TEXT,
            target_stage TEXT,
            metadata_json TEXT
        );
        """
    )
    conn.execute("INSERT INTO main_path_edges VALUES (1)")
    conn.execute("INSERT INTO subgraph_nodes VALUES ('p1')")
    conn.execute("INSERT INTO subgraph_edges VALUES ('background')")
    conn.execute("INSERT INTO predicted_future_edges VALUES ('p1', 'p2')")
    conn.execute("INSERT INTO vgae_calibration_audit VALUES ('rolling')")
    conn.execute(
        "INSERT INTO limitation_atoms VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "discussion",
            "sa1",
            "v14b_section_parser_contract_v3_toc_guard",
            "sac1",
            "section_level",
        ),
    )
    conn.execute("INSERT INTO future_directions VALUES (1)")
    conn.execute(
        "INSERT INTO direction_claim_cards VALUES (?, ?, ?)",
        (
            1,
            0,
            json.dumps(
                {
                    "section_atom_chain_support": {
                        "total": 1,
                        "full_decision_grade": 1,
                    }
                }
            ),
        ),
    )
    conn.execute("INSERT INTO visual_nodes VALUES ('p1')")
    conn.execute("INSERT INTO visual_edges VALUES ('future')")
    conn.execute("INSERT INTO branch_lineages VALUES ('b1')")
    conn.execute(
        "INSERT INTO mutation_hypotheses VALUES (?, ?, ?, ?, ?)",
        (
            "mutation:claim:1",
            "complete_claim_card_pending_high_confidence_evidence",
            "candidate_pool_only",
            json.dumps(["inherits claim card uncertainty"]),
            json.dumps(["falsify if margin fails"]),
        ),
    )
    conn.executemany(
        "INSERT INTO bottleneck_lineage_triples VALUES (?, ?, ?)",
        [
            (
                "constraint_failure",
                "candidate_resolver",
                json.dumps({"typed_chain_completeness": "resolution_candidate_partial"}),
            ),
            (
                "constraint_failure",
                "validated_resolver",
                json.dumps({"typed_chain_completeness": "full", "typed_chain_complete": True}),
            ),
        ],
    )
    conn.commit()
    conn.close()


def test_algorithm_logic_audit_writes_stepwise_contracts(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    reports = tmp_path / "reports"
    _make_main(main)
    _make_v14(v14)
    reports.mkdir()
    (reports / "topic_gap_no_target_inspection.json").write_text(
        json.dumps(
            {
                "summary": {
                    "status": "pass",
                    "inspected_papers": 2,
                    "classification_counts": {"sectionless_or_non_target_heading_format": 2},
                    "parser_target_signal_papers": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_algorithm_logic_audit(
        db_main=main,
        db_v14=v14,
        report_dir=reports,
        repo_root=tmp_path,
    )
    md = (reports / "algorithm_logic_audit.md").read_text(encoding="utf-8")

    assert Path(result["report"]).exists()
    assert "Step5b calibrated future candidate generator" in md
    assert "never produce conclusions directly" in md
    assert "Step5s section evidence" in md
    assert "Step5s-a section atom search" in md
    assert "Step5s-b section atom typed chains" in md
    assert "GNN/VGAE must not atomize sections" in md
    assert "fuzzy candidate recall" in md
    assert "Do not loosen parser" in md
    assert "resolution_candidate_partial" in md
    payload = json.loads((reports / "algorithm_logic_audit.json").read_text(encoding="utf-8"))
    step5c = next(step for step in payload["steps"] if step["step"] == "Step5c limitation / resolution extraction")
    assert step5c["algorithm_fit"] == "aligned"
    assert "current_contract_typed_chain_atoms=1" in step5c["challenge"]
    step7 = next(step for step in payload["steps"] if step["step"] == "Step7 mutation")
    assert step7["algorithm_fit"] == "aligned"
    assert "mutation_hypotheses=1" in step7["challenge"]
    assert payload["metrics"]["lineage_completeness_counts"]["resolution_candidate_partial"] == 1
    assert payload["metrics"]["complete_typed_lineage_triples"] == 1
    assert payload["metrics"]["section_atoms"] == 1
    assert payload["metrics"]["section_atom_decision_grade"] == 1
    assert payload["metrics"]["section_atoms_fts"] == 1
    assert payload["metrics"]["section_atom_embeddings"] == 1
    assert payload["metrics"]["section_atom_embeddings_retrieval_only"] == 1
    assert payload["metrics"]["section_atom_chains"] == 1
    assert payload["metrics"]["section_atom_chain_full"] == 1
    assert payload["metrics"]["section_atom_chain_decision_grade"] == 1
    assert payload["metrics"]["claim_cards_with_section_atom_chain_support"] == 1
    assert payload["metrics"]["complete_claim_cards_with_section_atom_chain_support"] == 1
    assert payload["metrics"]["claim_cards_with_full_decision_grade_chain"] == 1
    assert payload["metrics"]["limitation_section_atom_bridge_atoms"] == 1
    assert payload["metrics"]["limitation_current_contract_atoms"] == 1
    assert payload["metrics"]["limitation_typed_chain_atoms"] == 1
    assert payload["metrics"]["limitation_current_contract_typed_chain_atoms"] == 1
    assert payload["metrics"]["limitation_abstract_atoms"] == 0
    assert payload["metrics"]["mutation_hypotheses"] == 1
    assert payload["metrics"]["mutation_hypotheses_with_falsification"] == 1
    assert payload["metrics"]["mutation_hypotheses_with_evidence_contract"] == 1
    assert result["status_counts"]["readiness"]["fail"] >= 1
