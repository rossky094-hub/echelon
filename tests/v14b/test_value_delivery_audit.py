from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from echelon.v14b.value_delivery_audit import (
    audit_claim_card_high_confidence_evidence_contract,
    audit_evolution_evidence_map_contract,
    audit_future_growth,
    audit_legacy_flow_isolation_contract,
    audit_llm_evidence_boundary,
    audit_main_path_uncertainty_contract,
    audit_multi_topic_regression,
    audit_online_topic_readiness_contract,
    audit_rd_radar_promotion_contract,
    collect_value_gates,
    run_audit,
)


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (paper_id TEXT, section_name TEXT, section_text TEXT);
        CREATE TABLE corpus_registry (corpus_id TEXT PRIMARY KEY);
        CREATE TABLE paper_corpora (paper_id TEXT, corpus_id TEXT);
        CREATE TABLE corpus_runs (run_id TEXT PRIMARY KEY, corpus_id TEXT);
        CREATE TABLE corpus_snapshots (snapshot_id TEXT PRIMARY KEY, corpus_id TEXT);
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "W2")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("p2",), ("",)])
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("section evidence " * 20,))
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (src_paper_id TEXT, dst_paper_id TEXT);
        CREATE TABLE vgae_calibration_audit (method TEXT);
        CREATE TABLE limitation_atoms (
            atom_id INTEGER,
            paper_id TEXT,
            evidence_source TEXT,
            evidence_quality TEXT,
            evidence_weight REAL,
            extractor_method TEXT
        );
        CREATE TABLE limitation_resolutions (atom_id INTEGER);
        CREATE TABLE fusion_evidence_audit (run_id TEXT, output_directions INTEGER);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            direction_id INTEGER,
            direction_name TEXT,
            root_constraint_json TEXT,
            attempts_last_10y_json TEXT,
            enabling_conditions_json TEXT,
            unresolved_bottleneck_json TEXT,
            minimal_validation_experiment_json TEXT,
            evidence_strength_level TEXT,
            claim_scope TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        CREATE TABLE visual_nodes (paper_id TEXT);
        CREATE TABLE visual_edges (layer TEXT);
        CREATE VIRTUAL TABLE visual_search_fts USING fts5(title);
        CREATE TABLE branch_lineages (
            branch_id TEXT,
            parent_branch_id TEXT,
            split_confidence REAL,
            split_evidence_json TEXT
        );
        CREATE TABLE bottleneck_lineage_triples (
            source_stage TEXT,
            target_stage TEXT,
            evidence_quality TEXT,
            evidence_page INTEGER
        );
        """
    )
    conn.execute("INSERT INTO predicted_future_edges VALUES ('p1', 'p2')")
    conn.execute("INSERT INTO vgae_calibration_audit VALUES ('rolling')")
    minimal_experiment = json.dumps(
        {
            "experiment": "Run an A/B validation experiment.",
            "cost_level": "low",
            "cycle_weeks": 2,
            "success_criteria": ["metric improves"],
            "falsification_conditions": ["metric does not improve"],
        }
    )
    conn.execute("INSERT INTO direction_claim_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("cc1", 1, "d", "{}", "[]", "{}", "{}", minimal_experiment, "moderate", "exploratory", 1, 0, "{}"))
    conn.execute("INSERT INTO visual_nodes VALUES ('p1')")
    conn.execute("INSERT INTO visual_edges VALUES ('future')")
    conn.execute(
        "INSERT INTO branch_lineages VALUES ('B1', 'B0', 0.3, ?)",
        (json.dumps({"lineage_status": "evidence_backed_split", "parent_citation_support": 8}),),
    )
    for src, dst in (
        ("constraint", "failure_mechanism"),
        ("failure_mechanism", "attempt_path"),
        ("attempt_path", "local_fix"),
        ("local_fix", "new_constraint"),
    ):
        conn.execute("INSERT INTO bottleneck_lineage_triples VALUES (?, ?, 'section_level', 4)", (src, dst))
    conn.commit()
    conn.close()


def _write_product_sources(root: Path) -> None:
    api = root / "echelon/api"
    api.mkdir(parents=True, exist_ok=True)
    (api / "graph_visual_backend.py").write_text(
        "def _build_topic_branch_splits(branch_dossiers): branch_contract_by_id parent_branch_id lineage_status split_confidence\n"
        "def _branch_lineage_contract(): return claim_scope + evidence_grade + uncertainty_reasons + evidence_objects\n"
        "def get_visual_clusters(): return _branch_lineage_contract\n"
        'def _reading_path_item(): return {"can_explain": can_explain, "cannot_explain": cannot_explain, "note": "Radar promotion without complete Step13 Claim Cards GNN/VGAE is a candidate generator, not a conclusion generator"}\n'
        "def _paper_hit_contract(): return visual_search_hit + retrieval_context_only + claim_scope + evidence_grade + uncertainty_reasons\n"
        "def _hydrate_hits(): return _paper_hit_contract\n"
        "def _story_step_contract(): return timeline_context_only + future_candidate_story_context + evidence_objects\n"
        "def get_visual_story_steps(): return _story_step_contract\n"
        "def _paper_role_contract(): return claim_scope + evidence_grade + uncertainty_reasons + evidence_objects\n"
        "def get_visual_paper_detail(): return {'paper_role': _paper_role_contract()}\n"
        "def _visual_node_role_contract(): return visual_node_role + claim_scope + evidence_grade + uncertainty_reasons\n"
        "def get_visual_nodes(): return _visual_node_role_contract\n"
        "def _limitation_is_resolved(): limitation_resolutions resolved_evidence_count unresolved_evidence_count resolution_status\n"
        "def _limitation_atom_contract(): return weak_bottleneck_hypothesis + section_limitation_context + claim_scope + evidence_grade + uncertainty_reasons\n"
        'def _build_bottleneck_lineage(): return {"can_explain": ["x"], "cannot_explain": ["a proven causal root-cause chain when section-level typed triples are missing", "that a bottleneck is solved without linked resolution atoms"]}\n'
        'def _claim_card_evidence_objects(): minimal_validation_experiment Step13 Claim Card "evidence_objects": item.get("evidence_objects")\n'
        'def _build_validation_directions(): return {"can_explain": ["x"], "cannot_explain": ["that the direction is ready for Radar", "Radar promotion without a complete Claim Card"], "required_evidence": ["x"]}\n'
        "def _apply_future_edge_contracts(): future_candidates candidate_pool_only required_evidence evidence_objects\n"
        "def _visual_edge_contract(): return visual_edge + claim_scope + evidence_grade + uncertainty_reasons\n"
        "def get_visual_edges(): return _visual_edge_contract\n"
        '_build_evidence_map history_main_path_contract recommended_layer_combinations "main_path": { "claim_scope": main_path_contract.get("claim_scope") "evidence_grade": main_path_contract.get("evidence_grade") "evidence_objects": main_path_contract.get("evidence_objects")\n'
        '"branches": [ parent_branch_id lineage_status claim_scope evidence_grade uncertainty_reasons\n'
        '"evidence_map": evidence_map\n'
        '_build_history_main_path_contract history_main_path_contract "history_main_path": {\n'
        "claim_cards incomplete_claim_cards candidate_pool GNN future edges\n"
        "topic_readiness = build_topic_readiness_preflight\n",
        encoding="utf-8",
    )
    web = root / "web/visual-graph"
    web.mkdir(parents=True, exist_ok=True)
    (web / "app.js").write_text(
        "function renderTopicReadiness() { return topic_readiness; }\n"
        "function renderPaperList() { return paper.claim_scope + paper.evidence_grade + paper.uncertainty_reasons + paper.required_evidence + renderEvidenceObjects(paper.evidence_objects); }\n"
        "function renderLimitations() { return lim.claim_scope + lim.evidence_grade + lim.uncertainty_reasons + renderEvidenceObjects(lim.evidence_objects); }\n"
        "function renderLocalEdges() { return edge.claim_scope + edge.evidence_grade + edge.uncertainty_reasons + renderEvidenceObjects(edge.evidence_objects); }\n"
        "function renderClusters() { return lineage.claim_scope + lineage.evidence_grade + lineage.uncertainty_reasons + renderEvidenceObjects(lineage.evidence_objects); }\n"
        "function renderStory() { return step.claim_scope + step.evidence_grade + step.uncertainty_reasons + renderEvidenceObjects(step.evidence_objects); }\n"
        "function renderPaper() { return paperRole.claim_scope + paperRole.evidence_grade + paperRole.uncertainty_reasons + renderEvidenceObjects(paperRole.evidence_objects); }\n"
        "function renderHover() { els.hover.innerHTML = node.claim_scope + node.evidence_grade + node.uncertainty_reasons; }\n"
        "function renderBottleneckLineage() { return c.can_explain + c.cannot_explain + '不能说明'; }\n"
        "function buildSearchFallbackTopicLens() { return 'ui_search_fallback_readiness insufficient_evidence retrieval_context_only No branch lineage, bottleneck lineage, main-path, Step6 fusion, or Step13 Claim Card'; }\n"
        "function renderTopicDossier() { return readingPath + item.can_explain + item.cannot_explain + '不能说明' + split.lineage_status + split.parent_branch_id + split.claim_scope + split.evidence_grade + split.uncertainty_reasons + b.resolution_status + b.unresolved_evidence_count + b.resolved_evidence_count + d.minimal_validation_experiment + d.can_explain + d.cannot_explain + d.required_evidence + '进入 Radar 还需要' + renderEvidenceObjects(d.evidence_objects); }\n"
        "function renderEvidenceMapSummary() { const mainPath = evidence.main_path; return 'Main-path evidence boundary' + renderComboContract(mainPath) + renderEvidenceObjects(mainPath.evidence_objects) + renderComboContract('Fusion value'); }\n"
        "function renderFutureEdges() { return 'Future edge uncertainty' + edge.claim_scope + edge.evidence_grade + edge.required_evidence + edge.uncertainty_reasons + renderEvidenceObjects(edge.evidence_objects); }\n"
        "function renderDossierRadar() { return item.evidence_grade + item.uncertainty_reasons + item.required_evidence + renderEvidenceObjects(item.evidence_objects) + experiment.falsification_conditions + 'Claim Card uncertainty Success criteria Falsification No complete Claim Cards yet Future candidate generator pool'; }\n"
        "function renderRadar() { els.radarPane.innerHTML = renderDossierRadar(rd_radar); }\n"
        "const mainPathCopy = 'Main-path uncertainty history.claim_scope history.evidence_grade';\n",
        encoding="utf-8",
    )
    (web / "index.html").write_text(
        '<label><input type="checkbox" data-layer="fusion_value" checked />Fusion value</label>\n',
        encoding="utf-8",
    )
    v14 = root / "echelon/v14b"
    v14.mkdir(parents=True, exist_ok=True)
    (v14 / "topic_regression.py").write_text(
        'BENCHMARK_TOPICS = {}\n'
        'def configure_parser(parser): parser.add_argument("--topic", default="all")\n'
        "def run_topic_readiness_preflight():\n    return build_topic_readiness_preflight\n",
        encoding="utf-8",
    )
    (v14 / "topic_readiness.py").write_text(
        "NO_LLM_PREFLIGHT_POLICY = 'LLM may audit/name/explain only after evidence exists'\n",
        encoding="utf-8",
    )
    (v14 / "config.py").write_text(
        'V14B_LIMITATION_USE_LLM", "false"\n'
        'V14B_SCIBERT_LLM_FALLBACK", "false"\n'
        'V14B_FUSION_USE_LLM_NAMING", "false"\n',
        encoding="utf-8",
    )
    (v14 / "step5c_limitation.py").write_text(
        "extractor_method LIMITATION_USE_LLM else None _limitation_evidence_common\n",
        encoding="utf-8",
    )
    (v14 / "step5a_scibert.py").write_text(
        "--use-llm SCIBERT_LLM_FALLBACK citation_function_evidence_level\n",
        encoding="utf-8",
    )
    (v14 / "step6_fusion.py").write_text(
        "FUSION_USE_LLM_NAMING Optional LLM naming\n",
        encoding="utf-8",
    )
    (v14 / "step11_llm_edge_audit.py").write_text(
        "Stratified LLM edge audit Default execution is capped\n",
        encoding="utf-8",
    )
    (v14 / "step13_first_principles_history.py").write_text(
        "默认不调用外部 LLM 已入库证据可重跑 section_evidence_strong section_provenance_ready missing_high_confidence_gates success_criteria falsification_conditions minimal validation experiment with success and falsification criteria\n",
        encoding="utf-8",
    )
    (v14 / "step9_report.py").write_text(
        "make product-chain make post-frontfill-chain legacy compatibility "
        "claim_scope evidence_grade uncertainty_reasons candidate_pool_only\n",
        encoding="utf-8",
    )
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run_after_frontfill_product_chain.py").write_text(
        "V14B_TOPIC_GAP_FRONTFILL_CMD make topic-gap-repair\n",
        encoding="utf-8",
    )
    (scripts / "guard_topic_gap_repair.py").write_text(
        "active broad section ingest detected\n"
        "V14B_ALLOW_CONCURRENT_TOPIC_GAP_REPAIR\n"
        "watch_step5s_section_ingest.py\n"
        "run_after_frontfill_product_chain.py\n",
        encoding="utf-8",
    )


def _write_makefile_contracts(root: Path) -> None:
    (root / "Makefile").write_text(
        "#   make product-chain\n"
        "#   make post-frontfill-chain\n"
        "# Legacy compatibility:\n"
        "#   make pilot # LEGACY compatibility only; not current V14B decision workflow\n"
        "product-chain-fast: id-repair graph-features\n"
        "product-chain: id-repair graph-prep evidence-prep\n"
        "\t$(MAKE) decision-audit\n"
        "decision-audit:\n"
        "\t$(MAKE) topic-regression\n"
        "\t$(MAKE) section-queue-audit\n"
        "\t$(MAKE) direction-readiness-audit\n"
        "\t$(MAKE) value-delivery-audit\n"
        "topic-gap-repair:\n"
        "\tpython scripts/guard_topic_gap_repair.py\n"
        "\t$(MAKE) topic-regression\n"
        "\t$(MAKE) section-queue-audit\n"
        "\t$(MAKE) section-evidence-topic-gaps\n"
        "\t$(MAKE) topic-regression\n"
        "\t$(MAKE) section-queue-audit\n"
        "\t$(MAKE) direction-readiness-audit\n"
        "\t$(MAKE) value-delivery-audit\n"
        "post-frontfill-chain:\n"
        "\tpython scripts/run_after_frontfill_product_chain.py\n"
        "## LEGACY compatibility: Step 1 OpenAlex enrich; not current V14B decision workflow\n"
        "enrich:\n"
        "\t@echo 'LEGACY compatibility target; not current V14B decision workflow.'\n"
        "## LEGACY compatibility: old pilot graph rerun; not current V14B decision workflow\n"
        "pilot: pilot-graph\n"
        "## LEGACY compatibility: old pilot graph rerun; not current V14B decision workflow\n"
        "pilot-graph: id-repair openalex-backfill\n"
        "## LEGACY compatibility: old pilot visual rerun; not current V14B decision workflow\n"
        "pilot-visual: pilot-graph visual-graph goal-audit\n"
        "## LEGACY compatibility: old enrich + pilot visual full flow; not current V14B decision workflow\n"
        "pilot-full: enrich pilot-visual\n"
        "\t@echo 'LEGACY compatibility target; not current V14B decision workflow.'\n"
        "# LEGACY compatibility: old quick debug pilot; not current V14B decision workflow\n"
        "pilot-debug:\n"
        "\tV14B_LIMIT=100 $(MAKE) pilot-graph\n"
        "quarterly-run:\n"
        "quarterly-run-optics:\n"
        "quarterly-run-cs:\n"
        "quarterly-run-materials:\n"
        "help:\n"
        "\t@echo 'make product-chain'\n"
        "\t@echo 'make post-frontfill-chain'\n"
        "\t@echo 'Legacy compatibility (not current acceptance path):'\n"
        "\t@echo 'make pilot-full # not current V14B decision workflow'\n",
        encoding="utf-8",
    )


def _write_legacy_arxiv_script_contracts(root: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in (
        "diff_arxiv_optics_vs_db.py",
        "fetch_missing_arxiv_optics.sh",
        "monitor_optics_full_pipeline.sh",
        "run_arxiv_optics_harvest.sh",
        "run_arxiv_optics_incremental.sh",
        "run_step1_arxiv_enrich.sh",
    ):
        (scripts / name).write_text(
            "LEGACY compatibility\n"
            "old arXiv gap-first flow is not the current V14B decision workflow\n"
            "V14B_RUN_LEGACY_ARXIV_FLOW\n",
            encoding="utf-8",
        )


def _make_v14_edge_calibrated_without_run_audit(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            calibrated_prob REAL,
            calibration_method TEXT,
            calibration_label TEXT
        );
        CREATE TABLE future_candidate_lifecycle (
            lifecycle_state TEXT,
            radar_eligible INTEGER
        );
        CREATE TABLE direction_claim_cards (
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO predicted_future_edges VALUES ('p1', 'p2', 0.9, 0.8, 'temporal_platt_logistic', 'calibrated_temporal_holdout')"
    )
    conn.execute("INSERT INTO future_candidate_lifecycle VALUES ('future_candidate_unfused', 0)")
    conn.commit()
    conn.close()


def _make_v14_uncalibrated_promoted_direction(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            calibrated_prob REAL,
            calibration_method TEXT,
            calibration_label TEXT
        );
        CREATE TABLE future_directions (
            direction_id INTEGER,
            direction_name TEXT,
            claim_scope TEXT,
            evidence_tier TEXT,
            calibration_label TEXT,
            evidence_json TEXT
        );
        CREATE TABLE direction_claim_cards (
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO predicted_future_edges VALUES ('p1', 'p2', 0.9, 0.8, 'temporal_platt_logistic', 'calibrated_temporal_holdout')"
    )
    conn.execute(
        "INSERT INTO future_directions VALUES (?, ?, ?, ?, ?, ?)",
        (
            1,
            "Promoted without run audit",
            "candidate_direction",
            "triangulated_strong",
            "calibrated_temporal_holdout",
            json.dumps({"calibration_status": "edge_has_calibration_label_but_run_audit_missing"}),
        ),
    )
    conn.commit()
    conn.close()


def test_value_delivery_audit_maps_eight_gates(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    _write_makefile_contracts(tmp_path)
    _write_legacy_arxiv_script_contracts(tmp_path)
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("parser.add_argument('--corpus-id')", encoding="utf-8")
    _write_product_sources(tmp_path)

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps(
            [
                {
                    "topic": "metalens",
                    "overall_status": "pass",
                    "benchmark_topic": True,
                    "benchmark_branch_coverage": 1.0,
                    "benchmark_fixture_contract": {
                        "role": "regression_fixture_not_product_allowlist",
                        "llm_policy": "no_llm_required_for_topic_preflight",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    result = collect_value_gates(main, v14, tmp_path, report_dir)

    assert len(result["gates"]) == 14
    assert any(g["issue"] == "Future Growth Calibration" for g in result["gates"])
    bottleneck_gate = next(g for g in result["gates"] if g["issue"] == "Bottleneck Lineage Graph")
    assert bottleneck_gate["checks"]["api_bottleneck_constraints_carry_limits"] is True
    assert bottleneck_gate["checks"]["ui_renders_bottleneck_lineage_limits"] is True
    branch_gate = next(g for g in result["gates"] if g["issue"] == "Branch Lineage Validity")
    assert branch_gate["checks"]["api_visual_clusters_carry_lineage_contract"] is True
    assert branch_gate["checks"]["ui_cluster_panel_renders_lineage_contract"] is True
    assert any(g["issue"] == "Multi-topic Regression" and g["status"] == "pass" for g in result["gates"])
    multi_gate = next(g for g in result["gates"] if g["issue"] == "Multi-topic Regression")
    assert multi_gate["checks"]["topic_regression_avoids_gold_topic_aliases"] is True
    assert multi_gate["checks"]["topic_regression_cli_defaults_to_suite"] is True
    claim_card_gate = next(g for g in result["gates"] if g["issue"] == "Claim Card Engine")
    assert claim_card_gate["status"] == "pass"
    assert claim_card_gate["checks"]["complete_cards_have_falsifiable_validation_experiment"] is True
    assert claim_card_gate["checks"]["step13_requires_success_and_falsification"] is True
    assert claim_card_gate["checks"]["ui_renders_success_and_falsification"] is True
    topic_gate = next(g for g in result["gates"] if g["issue"] == "Topic Dossier Product Value")
    assert topic_gate["online_readiness_contract"]["status"] == "pass"
    assert topic_gate["online_readiness_contract"]["checks"]["no_llm_preflight"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_branch_splits_inherit_lineage"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_reading_path_items_carry_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_search_hits_carry_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_bottlenecks_use_resolution_evidence"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_limitation_atoms_carry_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_validation_directions_inherit_claim_card_evidence"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_validation_directions_carry_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_search_fallback_is_insufficient_evidence"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_reading_path_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_paper_list_renders_hit_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_topic_dossier_branch_contracts"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_limitation_contracts"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_topic_bottleneck_resolution_counts"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_validation_direction_evidence_objects"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_validation_direction_limits"] is True
    evidence_map_gate = next(g for g in result["gates"] if g["issue"] == "Evolution Evidence Map Contract")
    assert evidence_map_gate["status"] == "pass"
    assert evidence_map_gate["checks"]["fusion_value_is_auditable_layer"] is True
    assert evidence_map_gate["checks"]["evidence_map_main_path_contract_present"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_main_path_carries_contract"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_future_edges_carry_contract"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_branches_carry_contract"] is True
    assert evidence_map_gate["checks"]["api_visual_edges_carry_contract"] is True
    assert evidence_map_gate["checks"]["ui_renders_evidence_map_main_path_contract"] is True
    assert evidence_map_gate["checks"]["ui_renders_future_edge_contracts"] is True
    assert evidence_map_gate["checks"]["ui_renders_local_edge_contracts"] is True
    radar_gate = next(g for g in result["gates"] if g["issue"] == "R&D Radar Promotion Contract")
    assert radar_gate["status"] == "pass"
    assert radar_gate["checks"]["raw_gnn_edges_are_candidate_pool_only"] is True
    main_path_gate = next(g for g in result["gates"] if g["issue"] == "Main Path Uncertainty Contract")
    assert main_path_gate["status"] == "pass"
    assert main_path_gate["checks"]["low_linked_refs_add_uncertainty"] is True
    assert main_path_gate["checks"]["api_visual_story_steps_carry_contract"] is True
    assert main_path_gate["checks"]["ui_story_mode_renders_contract"] is True
    assert main_path_gate["checks"]["api_visual_paper_role_carry_contract"] is True
    assert main_path_gate["checks"]["ui_paper_detail_renders_role_contract"] is True
    assert main_path_gate["checks"]["api_visual_nodes_carry_role_contract"] is True
    assert main_path_gate["checks"]["ui_node_hover_renders_role_contract"] is True
    high_conf_gate = next(g for g in result["gates"] if g["issue"] == "Claim Card High-Confidence Evidence Contract")
    assert high_conf_gate["status"] == "pass"
    assert high_conf_gate["checks"]["no_high_confidence_card_without_section_evidence"] is True
    llm_gate = next(g for g in result["gates"] if g["issue"] == "LLM Evidence Boundary Contract")
    assert llm_gate["status"] == "pass"
    assert llm_gate["checks"]["abstract_llm_atoms_remain_weak"] is True
    legacy_gate = next(g for g in result["gates"] if g["issue"] == "Legacy Flow Isolation Contract")
    assert legacy_gate["status"] == "pass"
    assert legacy_gate["checks"]["product_chains_avoid_legacy_targets"] is True
    assert legacy_gate["checks"]["legacy_arxiv_scripts_require_explicit_opt_in"] is True
    assert legacy_gate["checks"]["topic_gap_repair_refuses_concurrent_section_ingest"] is True
    assert legacy_gate["checks"]["step9_report_avoids_old_pilot_instruction"] is True
    evidence_gate = next(g for g in result["gates"] if g["issue"] == "Evidence Bone")
    assert "section_provenance" in evidence_gate["metrics"]
    assert any("section evidence provenance" in r for r in evidence_gate["uncertainty_reasons"])


def test_online_topic_readiness_contract_is_arbitrary_topic_and_no_llm(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_online_topic_readiness_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["no_llm_preflight"] is True
    assert result["checks"]["arbitrary_topic_not_benchmark_gated"] is True
    assert result["checks"]["api_topic_branch_splits_inherit_lineage"] is True
    assert result["checks"]["api_reading_path_items_carry_limits"] is True
    assert result["checks"]["api_topic_bottlenecks_use_resolution_evidence"] is True
    assert result["checks"]["api_topic_validation_directions_inherit_claim_card_evidence"] is True
    assert result["checks"]["api_validation_directions_carry_limits"] is True
    assert result["checks"]["ui_search_fallback_is_insufficient_evidence"] is True
    assert result["checks"]["ui_renders_reading_path_limits"] is True
    assert result["checks"]["ui_renders_topic_bottleneck_resolution_counts"] is True
    assert result["checks"]["ui_renders_validation_direction_evidence_objects"] is True
    assert result["checks"]["ui_renders_validation_direction_limits"] is True
    assert "turning papers with strong/moderate section provenance" in result["observed_gates"]


def test_evolution_evidence_map_contract_exposes_layer_limits_and_fusion_value(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_evolution_evidence_map_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["required_layers_present"] is True
    assert result["checks"]["combination_contracts_present"] is True
    assert result["checks"]["fusion_value_is_auditable_layer"] is True
    assert result["checks"]["evidence_map_main_path_contract_present"] is True
    assert result["missing_required_combinations"] == []


def test_rd_radar_promotion_contract_keeps_raw_gnn_edges_out_of_main_view(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_rd_radar_promotion_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["complete_cards_only_in_main_radar"] is True
    assert result["checks"]["incomplete_cards_are_candidate_pool_only"] is True
    assert result["checks"]["raw_gnn_edges_are_candidate_pool_only"] is True
    assert result["checks"]["claim_cards_carry_evidence_contract"] is True
    assert result["checks"]["candidate_edges_carry_evidence_contract"] is True
    assert result["checks"]["ui_radar_main_avoids_raw_edge_cards"] is True
    assert result["checks"]["ui_renders_radar_claim_card_evidence_contract"] is True
    assert result["candidate_edges"] == 1


def test_main_path_uncertainty_contract_demotes_low_linked_refs(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_main_path_uncertainty_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["low_linked_refs_add_uncertainty"] is True
    assert result["checks"]["main_path_edges_inherit_uncertainty"] is True
    assert result["claim_scope"] == "main_path_context_low_linked_refs"


def test_legacy_flow_isolation_contract_marks_old_pilot_as_legacy(tmp_path):
    _write_makefile_contracts(tmp_path)
    _write_product_sources(tmp_path)
    _write_legacy_arxiv_script_contracts(tmp_path)

    result = audit_legacy_flow_isolation_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["help_prefers_current_chain"] is True
    assert result["checks"]["product_chain_runs_decision_audit"] is True
    assert result["checks"]["decision_audit_runs_regression_gap_readiness_value"] is True
    assert result["checks"]["topic_gap_repair_refreshes_queue_ingests_and_reaudits"] is True
    assert result["checks"]["topic_gap_repair_refuses_concurrent_section_ingest"] is True
    assert result["checks"]["post_frontfill_uses_topic_gap_repair"] is True
    assert result["checks"]["pilot_full_is_legacy_compatibility_only"] is True
    assert result["checks"]["legacy_arxiv_scripts_require_explicit_opt_in"] is True
    assert result["disallowed_current_deps"] == {}


def test_legacy_flow_isolation_contract_flags_current_chain_using_old_enrich(tmp_path):
    _write_product_sources(tmp_path)
    (tmp_path / "Makefile").write_text(
        "product-chain: enrich pilot-full\n"
        "product-chain-fast: pilot\n"
        "post-frontfill-chain:\n"
        "pilot-full: enrich pilot-visual\n"
        "help:\n"
        "\t@echo 'make pilot-full'\n",
        encoding="utf-8",
    )

    result = audit_legacy_flow_isolation_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["product_chains_avoid_legacy_targets"] is False
    assert result["checks"]["legacy_targets_labeled"] is False
    assert "product-chain" in result["disallowed_current_deps"]


def test_legacy_flow_isolation_contract_flags_unguarded_arxiv_gap_script(tmp_path):
    _write_makefile_contracts(tmp_path)
    _write_product_sources(tmp_path)
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "monitor_optics_full_pipeline.sh").write_text(
        "#!/usr/bin/env bash\nmake pilot-graph\n",
        encoding="utf-8",
    )

    result = audit_legacy_flow_isolation_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["legacy_arxiv_scripts_require_explicit_opt_in"] is False
    assert result["unguarded_legacy_arxiv_scripts"] == ["scripts/monitor_optics_full_pipeline.sh"]


def test_claim_card_high_confidence_requires_section_evidence_and_provenance(tmp_path):
    _write_product_sources(tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO direction_claim_cards VALUES (?, ?, ?)",
        (
            "bad-high",
            1,
            json.dumps(
                {
                    "section_evidence_strength": "weak",
                    "section_provenance": {"strong": 0, "moderate": 0, "weak": 3},
                    "high_confidence_gates": {
                        "section_evidence_strong": False,
                        "section_provenance_ready": False,
                    },
                    "high_confidence_eligible": True,
                }
            ),
        ),
    )

    result = audit_claim_card_high_confidence_evidence_contract(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["invalid_high_confidence_cards"] == 1
    assert "section_evidence_strong" in result["invalid_examples"][0]["missing"]
    assert "section_provenance_ready" in result["invalid_examples"][0]["missing"]
    conn.close()


def test_llm_evidence_boundary_flags_promoted_abstract_llm_atoms(tmp_path):
    _write_product_sources(tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE limitation_atoms (
            atom_id INTEGER,
            paper_id TEXT,
            evidence_source TEXT,
            evidence_quality TEXT,
            evidence_weight REAL,
            extractor_method TEXT
        );
        CREATE TABLE subgraph_edges (
            citing_id TEXT,
            cited_id TEXT,
            citation_function_method TEXT,
            citation_context_available INTEGER,
            citation_function_evidence_level TEXT,
            citation_function_weight REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO limitation_atoms VALUES (1, 'p1', 'abstract', 'section_level', 0.9, 'llm')"
    )
    conn.execute(
        "INSERT INTO subgraph_edges VALUES ('p1', 'p2', 'llm_title_abstract_no_context', 0, 'moderate_citation_context', 0.7)"
    )

    result = audit_llm_evidence_boundary(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["invalid_llm_atoms"] == 1
    assert result["invalid_llm_citation_edges"] == 1
    assert result["checks"]["abstract_llm_atoms_remain_weak"] is False
    assert result["checks"]["llm_citation_without_context_remains_weak"] is False
    conn.close()


def test_llm_evidence_boundary_allows_weak_traced_llm_labels(tmp_path):
    _write_product_sources(tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE limitation_atoms (
            atom_id INTEGER,
            paper_id TEXT,
            evidence_source TEXT,
            evidence_quality TEXT,
            evidence_weight REAL,
            extractor_method TEXT
        );
        CREATE TABLE subgraph_edges (
            citing_id TEXT,
            cited_id TEXT,
            citation_function_method TEXT,
            citation_context_available INTEGER,
            citation_function_evidence_level TEXT,
            citation_function_weight REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO limitation_atoms VALUES (1, 'p1', 'abstract', 'weak_abstract', 0.35, 'llm')"
    )
    conn.execute(
        "INSERT INTO subgraph_edges VALUES ('p1', 'p2', 'llm_title_abstract_no_context', 0, 'weak_paper_metadata', 0.2)"
    )

    result = audit_llm_evidence_boundary(conn, tmp_path)

    assert result["status"] == "pass"
    assert result["llm_limitation_atoms"] == 1
    assert result["invalid_llm_atoms"] == 0
    assert result["invalid_llm_citation_edges"] == 0
    conn.close()


def test_value_delivery_audit_reports_edge_calibration_without_run_audit(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14_edge_calibrated_without_run_audit(v14)

    result = collect_value_gates(main, v14, Path("."))
    future_gate = next(g for g in result["gates"] if g["issue"] == "Future Growth Calibration")

    assert future_gate["status"] == "warn"
    assert future_gate["edge_calibrated_candidates"] == 1
    assert future_gate["calibration_audits"] == 0
    assert "run-level rolling held-out-year audit" in future_gate["calibration_gap"]


def test_future_growth_audit_fails_uncalibrated_direction_claim(tmp_path):
    v14 = tmp_path / "v14.sqlite3"
    _make_v14_uncalibrated_promoted_direction(v14)

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn)
    conn.close()

    assert result["status"] == "fail"
    assert result["uncalibrated_promoted_direction_claims"] == 1
    assert result["checks"]["run_level_calibration_required_for_direction_claims"] is False
    assert result["uncalibrated_promoted_examples"][0]["claim_scope"] == "candidate_direction"


def test_value_delivery_audit_fails_when_live_topic_regression_fails(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    _write_makefile_contracts(tmp_path)
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("--corpus-id", encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps([{"topic": "quantum light source", "overall_status": "fail"}]),
        encoding="utf-8",
    )

    result = collect_value_gates(main, v14, tmp_path, report_dir)
    multi = next(g for g in result["gates"] if g["issue"] == "Multi-topic Regression")

    assert multi["status"] == "fail"
    assert multi["failed_topics"] == ["quantum light source"]


def test_multi_topic_audit_rejects_gold_topic_fixture_outputs(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps(
            [
                {
                    "topic": "metalens",
                    "overall_status": "pass",
                    "benchmark_topic": True,
                    "benchmark_branch_coverage": 1.0,
                    "benchmark_fixture_contract": {
                        "role": "regression_fixture_not_product_allowlist",
                        "llm_policy": "no_llm_required_for_topic_preflight",
                    },
                    "gold_branch_coverage": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = audit_multi_topic_regression(report_dir)

    assert result["status"] == "fail"
    assert result["checks"]["live_results_avoid_gold_topic_fields"] is False
    assert result["checks"]["live_results_have_fixture_contract"] is True


def test_multi_topic_audit_rejects_active_gold_topic_aliases(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps(
            [
                {
                    "topic": "metalens",
                    "overall_status": "pass",
                    "benchmark_topic": True,
                    "benchmark_branch_coverage": 1.0,
                    "benchmark_fixture_contract": {
                        "role": "regression_fixture_not_product_allowlist",
                        "llm_policy": "no_llm_required_for_topic_preflight",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    source_dir = tmp_path / "echelon/v14b"
    source_dir.mkdir(parents=True)
    (source_dir / "topic_regression.py").write_text(
        'BENCHMARK_TOPICS = {}\n'
        'GoldTopic = BenchmarkTopic\n'
        'GOLD_TOPICS = BENCHMARK_TOPICS\n'
        'parser.add_argument("--topic", default="metalens")\n',
        encoding="utf-8",
    )

    result = audit_multi_topic_regression(report_dir, repo_root=tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["live_results_have_fixture_contract"] is True
    assert result["checks"]["topic_regression_avoids_gold_topic_aliases"] is False
    assert result["checks"]["topic_regression_cli_defaults_to_suite"] is False


def test_value_delivery_audit_fails_when_benchmark_topic_gap_sections_missing(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    _write_makefile_contracts(tmp_path)
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("--corpus-id", encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps(
            [
                {
                    "topic": "metalens",
                    "overall_status": "pass",
                    "benchmark_topic": True,
                    "benchmark_branch_coverage": 1.0,
                    "benchmark_fixture_contract": {
                        "role": "regression_fixture_not_product_allowlist",
                        "llm_policy": "no_llm_required_for_topic_preflight",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    queue_dir = tmp_path / "data/v14b"
    queue_dir.mkdir(parents=True)
    (queue_dir / "topic_evidence_gap_delta_queue.csv").write_text(
        "paper_id,priority_score,reasons\n"
        "p1,100,topic_gap_key_turning_section\n"
        "p2,90,topic_gap_claim_card_inputs\n",
        encoding="utf-8",
    )

    result = collect_value_gates(main, v14, tmp_path, report_dir)
    multi = next(g for g in result["gates"] if g["issue"] == "Multi-topic Regression")

    assert multi["status"] == "fail"
    assert multi["topic_gap_blocking"] is True
    assert multi["topic_gap_primary_section_papers"] == 1


def test_value_delivery_audit_writes_report(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    _write_makefile_contracts(tmp_path)
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("--corpus-id", encoding="utf-8")

    out = run_audit(main, v14, tmp_path / "reports", tmp_path)

    assert (tmp_path / "reports" / "value_delivery_audit.md").exists()
    assert "evidence_policy" in out
