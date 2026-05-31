from __future__ import annotations

import json
import sqlite3

from echelon.v14b.section_atom_chains import assemble_chains_for_section, build_section_atom_chains


def _atom(
    idx: int,
    atom_type: str,
    text: str,
    *,
    grade: str = "section_atom_decision_grade",
    contract: str = "v14b_section_parser_contract_v3_toc_guard",
    repair_contracts: list[dict] | None = None,
) -> dict:
    return {
        "atom_id": f"sa_{idx}",
        "paper_id": "p1",
        "section_name": "discussion",
        "section_key": "discussion",
        "atom_index": idx,
        "atom_type": atom_type,
        "atom_text": text,
        "title": "Test paper",
        "page_start": 4,
        "page_end": 5,
        "source_url": "https://example.test/p1.pdf",
        "source_storage_uri": "/raw/p1.pdf",
        "parser_contract_version": contract,
        "source_delivery": "local_raw_pdf_cache",
        "extractor_method": "deterministic_section_atomizer_v1",
        "evidence_grade": grade,
        "claim_scope": "retrieval_context_only",
        "uncertainty_reasons_json": "[]",
        "features_json": "{}",
        "repair_contracts_json": json.dumps(repair_contracts or []),
        "created_at": "2026-05-31T00:00:00Z",
    }


def test_assemble_chains_for_section_can_create_full_typed_chain():
    chain = assemble_chains_for_section(
        [
            _atom(
                1,
                "constraint",
                "Wafer-scale fabrication tolerance is the root constraint.",
                repair_contracts=[
                    {
                        "repair_id": "repair-p1",
                        "source_contract": "topic_dossier_evidence_repair_plan",
                        "claim_scope": "evidence_repair_queue_only",
                    }
                ],
            ),
            _atom(2, "failure_mechanism", "Overlay mismatch creates phase errors and loss."),
            _atom(3, "attempted_path", "The authors used inverse design and calibration."),
            _atom(4, "local_fix", "The calibration mitigates mismatch in the prototype."),
            _atom(5, "new_constraint", "However packaging drift remains unresolved."),
        ]
    )[0]

    assert chain["typed_chain_complete"] == 1
    assert chain["typed_chain_completeness"] == "full"
    assert chain["evidence_grade"] == "typed_section_lineage"
    assert chain["claim_scope"] == "bottleneck_lineage_evidence"
    edges = json.loads(chain["relation_edges_json"])
    assert edges[0]["relation_type"] == "constraint_causes_failure"
    objects = json.loads(chain["evidence_objects_json"])
    assert [obj["role"] for obj in objects] == [
        "constraint",
        "failure_mechanism",
        "attempted_path",
        "local_fix",
        "new_constraint",
    ]
    assert json.loads(chain["repair_contracts_json"])[0]["repair_id"] == "repair-p1"
    assert objects[0]["repair_contracts"][0]["source_contract"] == "topic_dossier_evidence_repair_plan"


def test_assemble_chains_for_section_marks_partial_chains_as_exploratory():
    chain = assemble_chains_for_section(
        [
            _atom(1, "constraint", "Device efficiency remains limited."),
            _atom(2, "failure_mechanism", "Coupling loss dominates the measured output."),
            _atom(3, "attempted_path", "The paper uses a new grating coupler."),
        ]
    )[0]

    assert chain["typed_chain_complete"] == 0
    assert chain["typed_chain_completeness"] == "attempted_path_partial"
    assert chain["evidence_grade"] == "partial_typed_section_lineage"
    assert chain["claim_scope"] == "exploratory_bottleneck_lineage"
    assert json.loads(chain["missing_stages_json"]) == ["local_fix", "new_constraint"]
    assert any("typed lineage is partial" in reason for reason in json.loads(chain["uncertainty_reasons_json"]))


def test_assemble_chains_for_section_keeps_weak_contract_uncertainty():
    chain = assemble_chains_for_section(
        [
            _atom(1, "constraint", "Loss limits scaling.", grade="section_atom_weak", contract="legacy_unknown_contract"),
            _atom(2, "failure_mechanism", "Thermal instability creates drift.", grade="section_atom_weak"),
        ]
    )[0]

    assert chain["evidence_grade"] == "weak_partial_typed_section_lineage"
    reasons = json.loads(chain["uncertainty_reasons_json"])
    assert "one or more atoms have weak section provenance" in reasons
    assert "one or more atoms come from legacy or unknown parser contract" in reasons


def test_build_section_atom_chains_from_sqlite(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE section_atoms (
            atom_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_key TEXT NOT NULL,
            atom_index INTEGER NOT NULL,
            atom_type TEXT NOT NULL,
            atom_text TEXT NOT NULL,
            title TEXT,
            page_start INTEGER,
            page_end INTEGER,
            source_url TEXT,
            source_storage_uri TEXT,
            parser_contract_version TEXT,
            source_delivery TEXT,
            extractor_method TEXT NOT NULL,
            evidence_grade TEXT NOT NULL,
            claim_scope TEXT NOT NULL,
            uncertainty_reasons_json TEXT NOT NULL,
            features_json TEXT NOT NULL,
            repair_contracts_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    atoms = [
        _atom(1, "constraint", "Fabrication tolerance is the root constraint."),
        _atom(2, "failure_mechanism", "Mismatch creates optical loss."),
        _atom(3, "attempted_path", "A calibration design is attempted."),
        _atom(4, "local_fix", "Calibration mitigates mismatch."),
        _atom(5, "new_constraint", "Packaging stability remains open."),
    ]
    conn.executemany(
        """
        INSERT INTO section_atoms VALUES (
            :atom_id, :paper_id, :section_name, :section_key, :atom_index,
            :atom_type, :atom_text, :title, :page_start, :page_end,
            :source_url, :source_storage_uri, :parser_contract_version,
            :source_delivery, :extractor_method, :evidence_grade,
            :claim_scope, :uncertainty_reasons_json, :features_json, :repair_contracts_json, :created_at
        )
        """,
        atoms,
    )
    conn.commit()
    conn.close()

    stats = build_section_atom_chains(db)
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT typed_chain_completeness, evidence_grade, claim_scope, repair_contracts_json FROM section_atom_chains"
    ).fetchone()
    conn.close()

    assert stats["chains_written"] == 1
    assert stats["by_completeness"]["full"] == 1
    assert row[:3] == ("full", "typed_section_lineage", "bottleneck_lineage_evidence")
    assert json.loads(row[3]) == []
