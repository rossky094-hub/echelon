from __future__ import annotations

import json
import sqlite3

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.section_atoms import build_section_atom_embeddings, build_section_atoms
from echelon.v14b.topic_gap_stage_candidate_recall import (
    PROMOTION_POLICY,
    build_topic_gap_stage_candidate_recall,
)


def _meta() -> str:
    return json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["explicit_heading"],
            "source_delivery": "local_raw_pdf_cache",
            "source_storage_uri": "/Volumes/LaCie/Echelon_Paper_Raw_Data/pdfs/p_stage.pdf",
        }
    )


def _seed_sections(db_path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            doi TEXT,
            arxiv_id TEXT,
            openalex_id TEXT,
            s2_paper_id TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, '', '', '', '')",
        ("p_stage", "Hybrid photonic crystal cavity mode volume repair"),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p_stage",
            "Discussion",
            (
                "A central constraint is mode-volume drift during packaging. "
                "The coupled cavity approach uses an optimized waveguide architecture. "
                "The calibration mitigates mismatch and reduces coupling loss. "
                "However, placement drift remains a constraint for deployment."
            ),
            "https://example.test/p_stage.pdf",
            json.dumps([4]),
            _meta(),
        ),
    )
    conn.commit()
    conn.close()


def test_topic_gap_stage_candidate_recall_finds_same_paper_missing_stage_atoms(tmp_path):
    db = tmp_path / "library.sqlite3"
    _seed_sections(db)
    build_section_atoms(db_main=db, rebuild=True)
    build_section_atom_embeddings(db_main=db, rebuild=True, embedding_dim=64)

    triage = tmp_path / "topic_gap_section_evidence_audit.json"
    triage.write_text(
        json.dumps(
            {
                "audit_ts": "2026-05-31T00:00:00Z",
                "rows": [
                    {
                        "paper_id": "p_stage",
                        "title": "Hybrid photonic crystal cavity mode volume repair",
                        "priority_score": 0.9,
                        "topics": ["photonic crystal cavity"],
                        "gap_types": ["bottleneck_lineage_missing_topic_specific_typed_chain"],
                        "failure_mode": "lineage_full_chain_missing",
                        "section_atom_chain_missing_stages": {
                            "local_fix": 1,
                            "new_constraint": 1,
                        },
                        "repair_contract_closures": [
                            {
                                "paper_id": "p_stage",
                                "repair_id": "r_stage",
                                "source_contract": "topic_dossier_evidence_repair_plan",
                                "topic": "photonic crystal cavity",
                                "gap_type": "bottleneck_lineage_missing_topic_specific_typed_chain",
                                "bottleneck": "mode volume",
                                "frontfill_query": "photonic crystal cavity mode volume local fix remains constraint",
                                "closure_state": "partial_chain_incomplete",
                                "closed": False,
                                "missing_stages": {
                                    "local_fix": 1,
                                    "new_constraint": 1,
                                },
                                "next_action": "inspect missing typed stages",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "reports"
    report = build_topic_gap_stage_candidate_recall(
        db_main=db,
        triage_json=triage,
        out_dir=out_dir,
        top_k=3,
        embedding_dim=64,
    )

    assert report["status"] == "ready"
    assert report["promotion_policy"] == PROMOTION_POLICY
    assert report["summary"]["candidate_tasks"] == 2
    assert report["summary"]["tasks_with_same_paper_candidates"] == 2
    assert report["search_contract"]["claim_scope"] == "retrieval_context_only"
    assert "GNN/VGAE atom generation" in report["search_contract"]["section_atomization_layer"]["forbidden_methods"]

    by_stage = {row["missing_stage"]: row for row in report["rows"]}
    assert any(hit["atom_type"] == "local_fix" for hit in by_stage["local_fix"]["same_paper_candidate_hits"])
    assert any(
        hit["atom_type"] == "new_constraint"
        for hit in by_stage["new_constraint"]["same_paper_candidate_hits"]
    )
    assert all(
        hit["claim_scope"] == "retrieval_context_only"
        for row in report["rows"]
        for hit in row["same_paper_candidate_hits"]
    )
    assert "embedding_json" not in json.dumps(report)
    assert (out_dir / "topic_gap_stage_candidate_recall.json").exists()
    assert (out_dir / "topic_gap_stage_candidate_recall.md").exists()
    assert (out_dir / "topic_gap_stage_candidate_recall.csv").exists()
