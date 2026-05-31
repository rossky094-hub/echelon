from __future__ import annotations

import json

from echelon.v14b.topic_gap_repair_plan import build_topic_gap_repair_plan


def test_topic_gap_repair_plan_groups_closure_states_into_safe_actions(tmp_path):
    triage = tmp_path / "topic_gap_section_evidence_audit.json"
    out_dir = tmp_path / "reports"
    triage.write_text(
        json.dumps(
            {
                "audit_ts": "2026-05-31T00:00:00Z",
                "summary": {
                    "repair_contract_closure": {
                        "contracts": 4,
                        "closed_contracts": 1,
                    }
                },
                "rows": [
                    {
                        "paper_id": "p_atoms",
                        "title": "Atoms without chains",
                        "priority_score": 0.9,
                        "topics": ["metalens"],
                        "gap_types": ["bottleneck_lineage_missing_topic_specific_typed_chain"],
                        "failure_mode": "lineage_chains_missing_after_atoms",
                        "decision_grade_primary_rows": 1,
                        "section_atoms": 3,
                        "section_atom_chains": 0,
                        "section_atom_full_chains": 0,
                        "repair_contract_closures": [
                            {
                                "paper_id": "p_atoms",
                                "repair_id": "r_atoms",
                                "source_contract": "topic_dossier_evidence_repair_plan",
                                "topic": "metalens",
                                "gap_type": "bottleneck_lineage_missing_topic_specific_typed_chain",
                                "closure_state": "partial_atoms_available_no_chain",
                                "closed": False,
                                "next_action": "run section-atom-chains",
                            }
                        ],
                    },
                    {
                        "paper_id": "p_ingest",
                        "title": "Needs local PDF ingest",
                        "priority_score": 0.8,
                        "topics": ["metasurface holography"],
                        "gap_types": ["section_evidence_missing"],
                        "failure_mode": "unattempted_pdf_available",
                        "eligible_pdf": True,
                        "decision_grade_primary_rows": 0,
                        "section_atoms": 0,
                        "section_atom_chains": 0,
                        "repair_contract_closures": [
                            {
                                "paper_id": "p_ingest",
                                "repair_id": "r_ingest",
                                "source_contract": "multi_topic_evidence_gap_queue",
                                "topic": "metasurface holography",
                                "gap_type": "section_evidence_missing",
                                "closure_state": "open_section_evidence_not_decision_grade",
                                "closed": False,
                                "next_action": "run targeted topic-gap section ingest",
                            }
                        ],
                    },
                    {
                        "paper_id": "p_no_target",
                        "title": "Current parser no target",
                        "priority_score": 0.7,
                        "topics": ["quantum light source"],
                        "gap_types": ["section_evidence_missing"],
                        "failure_mode": "no_target_sections_after_current_parser",
                        "decision_grade_primary_rows": 0,
                        "section_atoms": 0,
                        "section_atom_chains": 0,
                        "repair_contract_closures": [
                            {
                                "paper_id": "p_no_target",
                                "repair_id": "r_no_target",
                                "source_contract": "multi_topic_evidence_gap_queue",
                                "topic": "quantum light source",
                                "gap_type": "section_evidence_missing",
                                "closure_state": "open_section_evidence_not_decision_grade",
                                "closed": False,
                                "next_action": "inspect parser misses",
                            }
                        ],
                    },
                    {
                        "paper_id": "p_partial",
                        "title": "Partial chain stages",
                        "priority_score": 0.65,
                        "topics": ["metalens"],
                        "gap_types": ["bottleneck_lineage_missing_topic_specific_typed_chain"],
                        "failure_mode": "lineage_full_chain_missing",
                        "decision_grade_primary_rows": 1,
                        "section_atoms": 4,
                        "section_atom_chains": 1,
                        "section_atom_full_chains": 0,
                        "section_atom_chain_missing_stages": {
                            "local_fix": 1,
                            "new_constraint": 1,
                        },
                        "repair_contract_closures": [
                            {
                                "paper_id": "p_partial",
                                "repair_id": "r_partial",
                                "source_contract": "topic_dossier_evidence_repair_plan",
                                "topic": "metalens",
                                "gap_type": "bottleneck_lineage_missing_topic_specific_typed_chain",
                                "closure_state": "partial_chain_incomplete",
                                "closed": False,
                                "missing_stages": {
                                    "local_fix": 1,
                                    "new_constraint": 1,
                                },
                                "next_action": "inspect missing typed stages",
                            }
                        ],
                    },
                    {
                        "paper_id": "p_closed",
                        "title": "Closed chain",
                        "priority_score": 0.6,
                        "topics": ["photonic crystal cavity"],
                        "gap_types": ["bottleneck_lineage_missing_topic_specific_typed_chain"],
                        "failure_mode": "decision_grade_current_contract",
                        "decision_grade_primary_rows": 1,
                        "section_atoms": 5,
                        "section_atom_chains": 1,
                        "section_atom_full_chains": 1,
                        "repair_contract_closures": [
                            {
                                "paper_id": "p_closed",
                                "repair_id": "r_closed",
                                "source_contract": "topic_dossier_evidence_repair_plan",
                                "topic": "photonic crystal cavity",
                                "gap_type": "bottleneck_lineage_missing_topic_specific_typed_chain",
                                "closure_state": "closed_typed_chain_available",
                                "closed": True,
                                "next_action": "Step13 gates still control promotion",
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = build_topic_gap_repair_plan(triage_json=triage, out_dir=out_dir, top_k=10)
    groups = {group["group_id"]: group for group in plan["action_groups"]}

    assert plan["status"] == "ready"
    assert plan["summary"]["contracts"] == 5
    assert plan["summary"]["quick_close_contracts"] == 1
    assert plan["summary"]["local_raw_pdf_ingest_contracts"] == 1
    assert "GNN/VGAE atom generation" in plan["execution_contract"]["section_atomization_layer"]["forbidden_methods"]
    assert "fuzzy" in plan["execution_contract"]["dual_retrieval_layer"]["fuzzy"]
    assert "make section-atom-chains" in groups["rebuild_section_atom_chains_quick_close"]["command_sequence"]
    assert "make section-evidence-topic-gaps-local" in groups["targeted_local_raw_pdf_ingest_when_safe"]["command_sequence"]
    assert "make topic-gap-no-target-inspect" in groups["inspect_current_parser_no_target"]["command_sequence"]
    assert "make topic-gap-stage-candidate-recall" in groups["inspect_typed_chain_stage_gaps"]["command_sequence"]
    assert groups["inspect_typed_chain_stage_gaps"]["missing_stage_counts"] == {
        "local_fix": 1,
        "new_constraint": 1,
    }
    assert groups["closed_waiting_step13_gate"]["promotion_policy"] == "no_direct_promotion"
    assert (out_dir / "topic_gap_repair_execution_plan.json").exists()
    assert (out_dir / "topic_gap_repair_execution_plan.md").exists()
    assert (out_dir / "topic_gap_repair_execution_plan.csv").exists()
