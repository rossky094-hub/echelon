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
    audit_openalex_frontfill_guard,
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
            evidence_grade TEXT,
            claim_scope TEXT,
            uncertainty_reasons_json TEXT,
            evidence_objects_json TEXT,
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
    evidence_objects = json.dumps([{"type": "claim_card", "id": "cc1"}])
    conn.execute(
        "INSERT INTO direction_claim_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "cc1",
            1,
            "d",
            "{}",
            "[]",
            "{}",
            "{}",
            minimal_experiment,
            "moderate",
            "complete_claim_card_pending_high_confidence_evidence",
            "exploratory",
            json.dumps(["missing high-confidence gate: fixture"]),
            evidence_objects,
            1,
            0,
            "{}",
        ),
    )
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
        'def _paper_hit_contract(): return visual_search_hit + retrieval_context_only + claim_scope + evidence_grade + uncertainty_reasons + reason.get("claim_scope") + reason.get("evidence_objects")\n'
        "def _hydrate_hits(): return _paper_hit_contract\n"
        "def search_evidence_atoms(): return _connect_main(readonly=True) + section_atoms_fts + section_atom_embeddings + search_section_atoms_hybrid + ensure_schema=False + phrase_query + section_atom_search_contract + retrieval_context_only\n"
        "def _story_step_contract(): return timeline_context_only + future_candidate_story_context + evidence_objects\n"
        "def get_visual_story_steps(): return _story_step_contract\n"
        "def _paper_role_contract(): return claim_scope + evidence_grade + uncertainty_reasons + evidence_objects\n"
        "def get_visual_paper_detail(): return {'paper_role': _paper_role_contract()}\n"
        "def future_plain_language(): return 'generator scores possible bridge'\n"
        "def _visual_node_role_contract(): return visual_node_role + claim_scope + evidence_grade + uncertainty_reasons\n"
        "def get_visual_nodes(): return _visual_node_role_contract\n"
        "def _limitation_is_resolved(): limitation_resolutions resolved_evidence_count unresolved_evidence_count resolution_status\n"
        "def _limitation_atom_contract(): return weak_bottleneck_hypothesis + section_limitation_context + claim_scope + evidence_grade + uncertainty_reasons\n"
        'def _build_bottleneck_lineage(): return {"can_explain": ["x"], "cannot_explain": ["a proven causal root-cause chain when section-level typed triples are missing", "that a bottleneck is solved without linked resolution atoms"]}\n'
        'def _claim_card_evidence_objects(): minimal_validation_experiment Step13 Claim Card "evidence_objects": item.get("evidence_objects")\n'
        'def _build_validation_directions(): return {"can_explain": ["x"], "cannot_explain": ["that the direction is ready for Radar", "Radar promotion without a complete Claim Card"], "required_evidence": ["x"]}\n'
        'def _build_topic_evidence_repair_plan(): return {"claim_scope": "evidence_repair_queue_only", "gap_type": "future_candidates_missing_claim_card", "target_pipeline_steps": ["section-atom-chains"]}\n'
        '"evidence_repair_plan": evidence_repair_plan\n'
        "def _apply_future_edge_contracts(): future_candidates candidate_pool_only required_evidence evidence_objects\n"
        "def _visual_edge_contract(): return visual_edge + claim_scope + evidence_grade + uncertainty_reasons\n"
        "def get_visual_edges(): return _visual_edge_contract\n"
        "def _build_uncertainty_overlays(): return linked_refs + section_evidence + openalex_topic_coverage + uncertainty_overlay_only + source_audit_uri\n"
        '_build_evidence_map history_main_path_contract recommended_layer_combinations "main_path": { "claim_scope": main_path_contract.get("claim_scope") "evidence_grade": main_path_contract.get("evidence_grade") "evidence_objects": main_path_contract.get("evidence_objects")\n'
        '"uncertainty_overlays": uncertainty_overlays\n'
        '"branches": [ parent_branch_id lineage_status claim_scope evidence_grade uncertainty_reasons\n'
        '"evidence_map": evidence_map\n'
        '_build_history_main_path_contract history_main_path_contract "history_main_path": {\n'
        '"candidate_score": candidate_score "score_semantics": "candidate ranking score; not validation confidence or a conclusion probability" "candidate_score": conf claim_cards incomplete_claim_cards candidate_pool GNN/VGAE candidate edges future candidate generator candidate_score calibrated_candidate_score raw_candidate_score calibrated_prob raw_predicted_prob\n'
        '"future_growth": {"candidate_edges": future_growth, "future_directions": future_directions}\n'
        "def _future_candidate_evidence_text(): return 'GNN/VGAE candidate edge candidate_score= calibrated_candidate_score= raw_candidate_score='\n"
        'if edge_type == "future_candidate": obj.pop("confidence", None) "candidate_score": candidate_score "calibrated_candidate_score": evidence.get("calibrated_candidate_score")\n'
        "topic_readiness = build_topic_readiness_preflight\n",
        encoding="utf-8",
    )
    web = root / "web/visual-graph"
    web.mkdir(parents=True, exist_ok=True)
    (web / "app.js").write_text(
        "function renderTopicReadiness() { return topic_readiness; }\n"
        "function renderPaperList() { return paper.claim_scope + paper.evidence_grade + paper.uncertainty_reasons + paper.required_evidence + renderEvidenceObjects(paper.evidence_objects); }\n"
        "function renderLimitations() { return lim.claim_scope + lim.evidence_grade + lim.uncertainty_reasons + renderEvidenceObjects(lim.evidence_objects); }\n"
        "function localEdgeScoreCopy() { return 'candidate_score support_score'; }\n"
        "function renderLocalEdges() { return localEdgeScoreCopy(edge) + edge.claim_scope + edge.evidence_grade + edge.uncertainty_reasons + renderEvidenceObjects(edge.evidence_objects); }\n"
        "function renderClusters() { return lineage.claim_scope + lineage.evidence_grade + lineage.uncertainty_reasons + 'split/support / support ' + renderEvidenceObjects(lineage.evidence_objects); }\n"
        "function renderStory() { return step.claim_scope + step.evidence_grade + step.uncertainty_reasons + renderEvidenceObjects(step.evidence_objects); }\n"
        "function renderPaper() { return paperRole.claim_scope + paperRole.evidence_grade + paperRole.uncertainty_reasons + renderEvidenceObjects(paperRole.evidence_objects); }\n"
        "function renderHover() { els.hover.innerHTML = node.claim_scope + node.evidence_grade + node.uncertainty_reasons; }\n"
        "function renderBottleneckLineage() { return c.can_explain + c.cannot_explain + '不能说明'; }\n"
        "function buildSearchFallbackTopicLens() { return 'ui_search_fallback_readiness insufficient_evidence retrieval_context_only No branch lineage, bottleneck lineage, main-path, Step6 fusion, or Step13 Claim Card'; }\n"
        "function renderTopicDossier() { const repairPlan = dossier.evidence_repair_plan; return 'Evidence repair plan' + readingPath + item.can_explain + item.cannot_explain + '不能说明' + split.lineage_status + split.parent_branch_id + split.claim_scope + split.evidence_grade + split.uncertainty_reasons + b.resolution_status + b.unresolved_evidence_count + b.resolved_evidence_count + d.minimal_validation_experiment + d.can_explain + d.cannot_explain + d.required_evidence + '进入 Radar 还需要' + task.target_pipeline_steps + task.cannot_explain + renderEvidenceObjects(task.evidence_objects) + renderEvidenceObjects(d.evidence_objects); }\n"
        "function renderEvidenceMapSummary() { const mainPath = evidence.main_path; return 'Main-path evidence boundary' + renderComboContract(mainPath) + renderEvidenceObjects(mainPath.evidence_objects) + renderUncertaintyOverlays(evidence.uncertainty_overlays) + renderComboContract('Fusion value'); }\n"
        "function renderUncertaintyOverlays() { return 'Uncertainty overlays' + overlay.claim_scope + overlay.evidence_grade + overlay.uncertainty_reasons + renderEvidenceObjects(overlay.evidence_objects); }\n"
        "function collectTopicIds() { return lens.future_growth?.candidate_edges; }\n"
        "function futureCalibrationCopy() { return 'candidate_score calibrated_candidate_score raw_candidate_score'; }\n"
        "function renderFutureEdges() { return 'Future edge uncertainty' + edge.claim_scope + edge.evidence_grade + edge.required_evidence + edge.uncertainty_reasons + renderEvidenceObjects(edge.evidence_objects); }\n"
        "function renderDossierRadar() { return item.evidence_grade + item.uncertainty_reasons + item.required_evidence + renderEvidenceObjects(item.evidence_objects) + experiment.falsification_conditions + item.candidate_score + '候选分数 Claim Card uncertainty Success criteria Falsification No complete Claim Cards yet Future candidate generator pool future candidate generator candidate score'; }\n"
        "function renderRadarScores() { return item.candidate_score; }\n"
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
        'def _future_edges(lens): return lens.get("future_growth", {}).get("candidate_edges") or []\n'
        'def _topic_dossier_repair_plan_rows(result): return "topic_dossier_evidence_repair_plan target_pipeline_steps evidence_repair_queue_only"\n'
        '"topic_dossier_repair_plan"\n'
        "def run_topic_readiness_preflight():\n    return build_topic_readiness_preflight\n",
        encoding="utf-8",
    )
    (v14 / "topic_gap_repair_plan.py").write_text(
        "closure_state partial_atoms_available_no_chain section-evidence-topic-gaps-local "
        "section-atom-embeddings no_direct_promotion GNN/VGAE atom generation fuzzy vector recall\n",
        encoding="utf-8",
    )
    (v14 / "product_baseline.py").write_text(
        'PRODUCT_BASELINE_TOPICS = ("metalens", "metasurface holography", "photonic crystal cavity", "quantum light source")\n'
        'parser.add_argument("--topic", default="all")\n'
        'def build_snapshot(): return {"topic_lens_quality_suite": []}\n'
        'def evaluate_topic_lens(topic, lens): return lens.get("future_growth", {}).get("candidate_edges") or []\n',
        encoding="utf-8",
    )
    (v14 / "step5s_section_queue_audit.py").write_text(
        "from echelon.v14b.product_baseline import PRODUCT_BASELINE_TOPICS\n"
        "DEFAULT_SECTION_AUDIT_TOPICS = PRODUCT_BASELINE_TOPICS\n"
        "topic_terms = topic_terms or list(DEFAULT_SECTION_AUDIT_TOPICS)\n"
        '"has_decision_grade_primary_section"\n'
        '"decision_grade_primary_section_rate"\n'
        'not r["has_decision_grade_primary_section"]\n'
        '"repair_contracts_json" "source_contracts" "target_pipeline_steps" "parser_contracts" "topic_dossier_evidence_repair_plan"\n',
        encoding="utf-8",
    )
    (v14 / "step5s_section_ingest.py").write_text(
        'def read_candidate_repair_contracts(): return "repair_contracts_json"\n'
        'repair_contracts_by_paper = read_candidate_repair_contracts(None)\n'
        'section_meta = {"repair_contracts": repair_contracts_by_paper, "repair_contract_source": "candidate_file"}\n'
        'stats = {"candidate_repair_contract_papers": len(repair_contracts_by_paper)}\n',
        encoding="utf-8",
    )
    (v14 / "section_atoms.py").write_text(
        'def _repair_contracts_from_meta(meta): return meta.get("repair_contracts_json")\n'
        'section_atom = {"repair_contracts": [], "claim_scope": "retrieval_context_only"}\n'
        'repair_contracts_json = "[]"\n',
        encoding="utf-8",
    )
    (v14 / "section_atom_chains.py").write_text(
        'def _repair_contracts(selected): return selected\n'
        'evidence_objects_json = {"repair_contracts": [], "repair_contracts_json": "[]"}\n',
        encoding="utf-8",
    )
    (v14 / "direction_readiness_audit.py").write_text(
        "def _public_latest_fusion_audit(row):\n"
        "    return {'candidate_ranking_score_avg': 0.8, 'min_candidate_score_threshold': 0.55}\n",
        encoding="utf-8",
    )
    (v14 / "step0_id_repair.py").write_text(
        "from echelon.v14b.reference_relink_audit import apply_exact_relinks\n"
        "def repair_ids():\n"
        "    result = apply_exact_relinks(conn)\n"
        "    return {'exact_reference_status_counts': result['candidate_summary']['status_counts']}\n",
        encoding="utf-8",
    )
    (v14 / "step1_enrich.py").write_text(
        "from echelon.v14b.reference_relink_audit import apply_exact_relinks\n"
        "def link_paper_reference_internals(conn):\n"
        "    result = apply_exact_relinks(conn)\n"
        "    return result['apply_result']['link_updates_applied']\n",
        encoding="utf-8",
    )
    (v14 / "step10_visual_graph_builder.py").write_text(
        '"candidate_edges": child_future\n'
        "Future candidate edges and unresolved limitation bottlenecks\n"
        "future_candidate_edges + limitation_atoms\n"
        '"candidate_score" "raw_candidate_score" "calibrated_candidate_score" "candidate_score_semantics"\n',
        encoding="utf-8",
    )
    (v14 / "future_candidate_lifecycle.py").write_text(
        '"candidate_score": candidate_score\n'
        '"raw_candidate_score": raw_candidate_score\n'
        '"calibrated_candidate_score": calibrated_candidate_score\n'
        "candidate_score={score:.3f}\n",
        encoding="utf-8",
    )
    (v14 / "topic_readiness.py").write_text(
        "NO_LLM_PREFLIGHT_POLICY = 'LLM may audit/name/explain only after evidence exists'\n",
        encoding="utf-8",
    )
    (v14 / "config.py").write_text(
        'V14B_LIMITATION_USE_LLM", "false"\n'
        'V14B_SCIBERT_LLM_FALLBACK", "false"\n'
        'V14B_FUSION_USE_LLM_NAMING", "false"\n'
        'REPORT_ALGO_VALIDATION = REPORT_DIR / "V14B_Evidence_Decision_算法验证报告.md"\n'
        'REPORT_FUTURE_DIRECTIONS = REPORT_DIR / "未来候选方向_证据合同报告.md"\n'
        "Low-confidence edges fall back to heuristic correction 不隐式调用 LLM\n",
        encoding="utf-8",
    )
    (v14 / "__init__.py").write_text(
        "Echelon V14-B Evidence Decision workflow\n"
        "evidence-constrained research decision pipeline\n"
        "legacy pilot graph flow\n"
        "compatibility-only\n",
        encoding="utf-8",
    )
    (v14 / "step5c_limitation.py").write_text(
        "section-first Limitation 默认不调用外部 LLM LLM opt-in "
        "不能自动升级为决策级证据 extractor_method LIMITATION_USE_LLM else None "
        "_limitation_evidence_common\n",
        encoding="utf-8",
    )
    (v14 / "step5a_scibert.py").write_text(
        "--use-llm LLM opt-in weak-label audit weak-label audit mode "
        "citation_function_evidence_level weak_paper_metadata "
        "Ignoring V14B_SCIBERT_LLM_FALLBACK\n",
        encoding="utf-8",
    )
    (v14 / "step6_fusion.py").write_text(
        "FUSION_USE_LLM_NAMING Optional LLM naming "
        "Future candidate generator GNN/VGAE candidate edge "
        "has_decision_grade_section_evidence limitation_decision_grade_section_count "
        "current parser-contract decision-grade limitation section evidence triangulated_strong\n",
        encoding="utf-8",
    )
    (v14 / "step4_subgraph.py").write_text(
        "bounded_evidence_subgraph "
        "bounded_evidence_subgraph_adequate_for_extraction "
        "evidence_subgraph_sparse_increase_or_use_step10_full_graph\n",
        encoding="utf-8",
    )
    (v14 / "step12_goal_alignment_audit.py").write_text(
        "bounded evidence subgraph for extraction support "
        "bounded evidence subgraph "
        "candidate_ranking_score_avg min_candidate_score_threshold "
        "candidate_edges_used top_candidate_edges_used\n",
        encoding="utf-8",
    )
    (v14 / "db_schema.py").write_text(
        "bounded evidence subgraph for heavier extraction\n",
        encoding="utf-8",
    )
    (v14 / "step11_llm_edge_audit.py").write_text(
        "Stratified LLM edge audit Default execution is capped\n",
        encoding="utf-8",
    )
    (v14 / "step13_first_principles_history.py").write_text(
        "默认不调用外部 LLM 已入库证据可重跑 "
        "section_evidence_strong section_provenance_ready section_decision_grade_ready "
        "SECTION_PARSER_CONTRACT_VERSION missing_high_confidence_gates "
        "candidate_score_ready \"candidate_score\": candidate_score future candidate score "
        "success_criteria falsification_conditions minimal validation experiment with success and falsification criteria "
        "evidence_grade uncertainty_reasons_json evidence_objects_json repair_contracts_json "
        '"repair_contracts" section_atom_chain\n',
        encoding="utf-8",
    )
    (v14 / "step9_report.py").write_text(
        "make product-chain make post-frontfill-chain legacy compatibility "
        "claim_scope evidence_grade uncertainty_reasons candidate_pool_only "
        "OpenAlex W 覆盖率 Field/Topic 覆盖率 coverage is not a success claim\n"
        "Citation-function evidence 覆盖率 Citation Function Evidence\n"
        "Future candidate generator 候选边数 ## 7. Future Candidate Generator\n"
        "_future_candidate_evidence_text candidate_score= 候选排序分数 "
        "candidate_score (候选排序分数) calibrated_candidate_score= raw_candidate_score= **candidate_score**\n"
        "GNN/VGAE 只生成 future candidate edges 公开报告只显示 candidate_score "
        "candidate_score 是候选排序信号 不是方向结论 Step13 complete Claim Card\n"
        "_normalise_subgraph_scope_row "
        "bounded_evidence_subgraph bounded evidence / extraction support "
        "与旧 V12.5 图谱样例对比\n"
        "V14B_Evidence_Decision_算法验证报告.md\n"
        "未来候选方向_证据合同报告.md\n"
        "capped LLM edge audit LLM 结果只能作为弱标签 不能直接升级结论\n"
        "保持 exploratory / candidate_pool limitation/discussion/resolution section evidence "
        "linked resolution evidence 阈值不得下调\n"
        "证据决策放行条件 Topic Dossier multi-topic regression "
        "Radar 主视图只允许完整 Step13 Claim Card candidate_pool_only\n",
        encoding="utf-8",
    )
    makefile = root / "Makefile"
    makefile_text = makefile.read_text(encoding="utf-8") if makefile.exists() else ""
    makefile.write_text(
        makefile_text
        + "\n## Step 5c: section-first limitation tracking; LLM opt-in only for weak traced assistance\n",
        encoding="utf-8",
    )
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run_after_frontfill_product_chain.py").write_text(
        "V14B_TOPIC_GAP_FRONTFILL_CMD make topic-gap-repair\n"
        "section-atoms section-atom-embeddings section-atom-chains\n"
        "active_section_ingest still running\n"
        "decision_grade_primary_section_papers\n"
        "topic_gap_decision_grade_section_rate\n"
        "SECTION_PARSER_CONTRACT_VERSION\n",
        encoding="utf-8",
    )
    (scripts / "guard_topic_gap_repair.py").write_text(
        "active broad section ingest detected\n"
        "V14B_ALLOW_CONCURRENT_TOPIC_GAP_REPAIR\n"
        "watch_step5s_section_ingest.py\n"
        "run_after_frontfill_product_chain.py\n",
        encoding="utf-8",
    )
    (scripts / "guard_openalex_backfill.py").write_text(
        "select_openalex_frontfill_state\n"
        "cooling_down_or_stopped\n"
        "cooldown_remaining_s\n"
        "active 429 cooldown detected\n"
        "V14B_ALLOW_OPENALEX_BACKFILL_DURING_COOLDOWN\n"
        "active OpenAlex backfill already detected\n"
        "V14B_ALLOW_CONCURRENT_OPENALEX_BACKFILL\n",
        encoding="utf-8",
    )


def _write_makefile_contracts(root: Path) -> None:
    (root / "Makefile").write_text(
        "#   make product-chain\n"
        "#   make post-frontfill-chain\n"
        "# Legacy compatibility:\n"
        "#   make pilot # LEGACY compatibility only; not current V14B decision workflow\n"
        "openalex-backfill:\n"
        "\tpython scripts/guard_openalex_backfill.py --repo-root .\n"
        "\tpython -m echelon.v14b.step0_openalex_backfill\n"
        "product-chain-fast: id-repair graph-features\n"
        "product-baseline:\n"
        "\tpython -m echelon.v14b.product_baseline --topic $${V14B_BASELINE_TOPIC:-all}\n"
        "product-chain: id-repair graph-prep evidence-prep\n"
        "\t$(MAKE) decision-audit\n"
        "decision-audit:\n"
        "\t$(MAKE) topic-regression\n"
        "\t$(MAKE) section-queue-audit\n"
        "\t$(MAKE) topic-gap-section-audit\n"
        "\t$(MAKE) topic-gap-repair-plan\n"
        "\t$(MAKE) topic-gap-no-target-inspect\n"
        "\t$(MAKE) cited-work-backfill-queue\n"
        "\t$(MAKE) raw-pdf-store-audit\n"
        "\t$(MAKE) topic-gap-raw-pdf-inspect\n"
        "\t$(MAKE) direction-readiness-audit\n"
        "\t$(MAKE) algorithm-logic-audit\n"
        "\t$(MAKE) value-delivery-audit\n"
        "topic-gap-repair:\n"
        "\tpython scripts/guard_topic_gap_repair.py\n"
        "\t$(MAKE) topic-regression\n"
        "\t$(MAKE) section-queue-audit\n"
        "\t$(MAKE) topic-gap-section-audit\n"
        "\t$(MAKE) topic-gap-repair-plan\n"
        "\t$(MAKE) section-evidence-topic-gaps\n"
        "\t$(MAKE) topic-regression\n"
        "\t$(MAKE) section-queue-audit\n"
        "\t$(MAKE) topic-gap-section-audit\n"
        "\t$(MAKE) topic-gap-repair-plan\n"
        "\t$(MAKE) direction-readiness-audit\n"
        "\t$(MAKE) value-delivery-audit\n"
        "topic-gap-repair-plan:\n"
        "\tpython -m echelon.v14b.topic_gap_repair_plan --triage-json reports/v14b_pilot/topic_gap_section_evidence_audit.json\n"
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
        "report:\n"
        "\t@echo 'reports/v14b_pilot/V14B_Evidence_Decision_算法验证报告.md'\n"
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

    assert len(result["gates"]) == 15
    future_gate = next(g for g in result["gates"] if g["issue"] == "Future Growth Calibration")
    assert future_gate["checks"]["step9_vgae_language_is_candidate_generator"] is True
    assert future_gate["checks"]["future_report_filename_is_candidate_contract"] is True
    assert future_gate["checks"]["future_direction_report_uses_candidate_score_labels"] is True
    assert future_gate["checks"]["step6_future_evidence_avoids_prediction_copy"] is True
    assert future_gate["checks"]["step6_strong_fusion_requires_decision_grade_sections"] is True
    assert future_gate["checks"]["current_docs_label_future_edges_as_candidates"] is True
    assert future_gate["checks"]["public_future_candidate_language_avoids_prediction_copy"] is True
    assert future_gate["checks"]["ui_future_calibration_copy_uses_candidate_score_labels"] is True
    assert future_gate["checks"]["direction_readiness_report_uses_candidate_score_labels"] is True
    assert future_gate["checks"]["step12_goal_alignment_report_uses_candidate_score_labels"] is True
    assert future_gate["checks"]["future_lifecycle_uses_candidate_score_labels"] is True
    openalex_gate = next(g for g in result["gates"] if g["issue"] == "OpenAlex Frontfill Guard Contract")
    assert openalex_gate["status"] == "pass"
    assert openalex_gate["checks"]["openalex_backfill_runs_guard_before_fetch"] is True
    assert openalex_gate["checks"]["guard_respects_429_cooldown"] is True
    bottleneck_gate = next(g for g in result["gates"] if g["issue"] == "Bottleneck Lineage Graph")
    assert bottleneck_gate["checks"]["api_bottleneck_constraints_carry_limits"] is True
    assert bottleneck_gate["checks"]["ui_renders_bottleneck_lineage_limits"] is True
    branch_gate = next(g for g in result["gates"] if g["issue"] == "Branch Lineage Validity")
    assert branch_gate["checks"]["api_visual_clusters_carry_lineage_contract"] is True
    assert branch_gate["checks"]["ui_cluster_panel_renders_lineage_contract"] is True
    assert branch_gate["checks"]["ui_branch_scores_are_labeled_as_support"] is True
    assert any(g["issue"] == "Multi-topic Regression" and g["status"] == "pass" for g in result["gates"])
    multi_gate = next(g for g in result["gates"] if g["issue"] == "Multi-topic Regression")
    assert multi_gate["checks"]["topic_regression_avoids_gold_topic_aliases"] is True
    assert multi_gate["checks"]["topic_regression_cli_defaults_to_suite"] is True
    assert multi_gate["checks"]["topic_regression_exports_topic_dossier_repair_plan"] is True
    assert multi_gate["checks"]["product_baseline_defaults_to_suite"] is True
    assert multi_gate["checks"]["makefile_product_baseline_defaults_to_suite"] is True
    assert multi_gate["checks"]["section_queue_defaults_to_multi_topic"] is True
    assert multi_gate["checks"]["section_queue_preserves_repair_contracts"] is True
    assert multi_gate["checks"]["section_ingest_preserves_repair_contract_provenance"] is True
    assert multi_gate["checks"]["section_atom_layer_preserves_repair_contract_provenance"] is True
    assert multi_gate["checks"]["topic_gap_repair_plan_uses_closure_states"] is True
    assert multi_gate["checks"]["current_plan_docs_avoid_gold_topic_language"] is True
    claim_card_gate = next(g for g in result["gates"] if g["issue"] == "Claim Card Engine")
    assert claim_card_gate["status"] == "pass"
    assert claim_card_gate["checks"]["complete_cards_have_falsifiable_validation_experiment"] is True
    assert claim_card_gate["checks"]["claim_cards_carry_persisted_evidence_contract"] is True
    assert claim_card_gate["checks"]["step13_requires_success_and_falsification"] is True
    assert claim_card_gate["checks"]["ui_renders_success_and_falsification"] is True
    high_conf_contract = next(
        g for g in result["gates"] if g["issue"] == "Claim Card High-Confidence Evidence Contract"
    )
    assert high_conf_contract["checks"]["step13_uses_candidate_score_gate"] is True
    topic_gate = next(g for g in result["gates"] if g["issue"] == "Topic Dossier Product Value")
    assert topic_gate["online_readiness_contract"]["status"] == "pass"
    assert topic_gate["online_readiness_contract"]["checks"]["no_llm_preflight"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_branch_splits_inherit_lineage"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_reading_path_items_carry_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_search_hits_carry_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_evidence_atom_search_is_read_only_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_bottlenecks_use_resolution_evidence"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_limitation_atoms_carry_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_validation_directions_inherit_claim_card_evidence"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_validation_directions_carry_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["api_topic_dossier_exposes_evidence_repair_plan"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_search_fallback_is_insufficient_evidence"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_reading_path_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_paper_list_renders_hit_contract"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_topic_dossier_branch_contracts"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_limitation_contracts"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_topic_bottleneck_resolution_counts"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_validation_direction_evidence_objects"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_validation_direction_limits"] is True
    assert topic_gate["online_readiness_contract"]["checks"]["ui_renders_topic_dossier_evidence_repair_plan"] is True
    evidence_map_gate = next(g for g in result["gates"] if g["issue"] == "Evolution Evidence Map Contract")
    assert evidence_map_gate["status"] == "pass"
    assert evidence_map_gate["checks"]["fusion_value_is_auditable_layer"] is True
    assert evidence_map_gate["checks"]["evidence_map_main_path_contract_present"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_main_path_carries_contract"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_uncertainty_overlays"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_future_edges_carry_contract"] is True
    assert evidence_map_gate["checks"]["api_evidence_map_branches_carry_contract"] is True
    assert evidence_map_gate["checks"]["api_visual_edges_carry_contract"] is True
    assert evidence_map_gate["checks"]["ui_renders_evidence_map_main_path_contract"] is True
    assert evidence_map_gate["checks"]["ui_renders_uncertainty_overlays"] is True
    assert evidence_map_gate["checks"]["ui_renders_future_edge_contracts"] is True
    assert evidence_map_gate["checks"]["ui_renders_local_edge_contracts"] is True
    radar_gate = next(g for g in result["gates"] if g["issue"] == "R&D Radar Promotion Contract")
    assert radar_gate["status"] == "pass"
    assert radar_gate["checks"]["raw_gnn_edges_are_candidate_pool_only"] is True
    assert radar_gate["checks"]["radar_public_scores_avoid_probability_copy"] is True
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
    assert high_conf_gate["checks"]["step9_does_not_recommend_threshold_relaxation"] is True
    llm_gate = next(g for g in result["gates"] if g["issue"] == "LLM Evidence Boundary Contract")
    assert llm_gate["status"] == "pass"
    assert llm_gate["checks"]["abstract_llm_atoms_remain_weak"] is True
    assert llm_gate["checks"]["citation_llm_fallback_explicit_and_weak"] is True
    assert llm_gate["checks"]["limitation_user_copy_is_section_first"] is True
    assert llm_gate["checks"]["makefile_limitation_target_avoids_llm_cost_claim"] is True
    legacy_gate = next(g for g in result["gates"] if g["issue"] == "Legacy Flow Isolation Contract")
    assert legacy_gate["status"] == "pass"
    assert legacy_gate["checks"]["product_chains_avoid_legacy_targets"] is True
    assert legacy_gate["checks"]["legacy_arxiv_scripts_require_explicit_opt_in"] is True
    assert legacy_gate["checks"]["topic_gap_repair_refuses_concurrent_section_ingest"] is True
    assert legacy_gate["checks"]["step9_report_avoids_old_pilot_instruction"] is True
    assert legacy_gate["checks"]["step9_openalex_language_is_coverage_not_success"] is True
    assert legacy_gate["checks"]["step9_uses_decision_readiness_not_frontend_launch"] is True
    assert legacy_gate["checks"]["step9_algo_report_filename_is_evidence_decision"] is True
    assert legacy_gate["checks"]["package_docstring_avoids_legacy_pilot_flow"] is True
    assert legacy_gate["checks"]["id_repair_uses_unambiguous_exact_reference_relinking"] is True
    assert legacy_gate["checks"]["legacy_enrich_relinker_delegates_to_exact_relinking"] is True
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
    assert result["checks"]["api_topic_dossier_exposes_evidence_repair_plan"] is True
    assert result["checks"]["ui_search_fallback_is_insufficient_evidence"] is True
    assert result["checks"]["ui_renders_reading_path_limits"] is True
    assert result["checks"]["ui_renders_topic_bottleneck_resolution_counts"] is True
    assert result["checks"]["ui_renders_validation_direction_evidence_objects"] is True
    assert result["checks"]["ui_renders_validation_direction_limits"] is True
    assert result["checks"]["ui_renders_topic_dossier_evidence_repair_plan"] is True
    assert "turning papers with strong/moderate section provenance" in result["observed_gates"]


def test_evolution_evidence_map_contract_exposes_layer_limits_and_fusion_value(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_evolution_evidence_map_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["required_layers_present"] is True
    assert result["checks"]["combination_contracts_present"] is True
    assert result["checks"]["fusion_value_is_auditable_layer"] is True
    assert result["checks"]["evidence_map_main_path_contract_present"] is True
    assert result["checks"]["uncertainty_overlays_contract_present"] is True
    assert result["checks"]["required_uncertainty_overlay_gates_present"] is True
    assert result["missing_required_combinations"] == []


def test_evolution_evidence_map_contract_rejects_generic_local_edge_score_copy(tmp_path):
    _write_product_sources(tmp_path)
    app_path = tmp_path / "web/visual-graph/app.js"
    app_path.write_text(
        app_path.read_text(encoding="utf-8")
        + "\nfunction badLocalEdges() { return 'edge score'; }\n",
        encoding="utf-8",
    )

    result = audit_evolution_evidence_map_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["ui_renders_local_edge_contracts"] is False


def test_rd_radar_promotion_contract_keeps_raw_gnn_edges_out_of_main_view(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_rd_radar_promotion_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["complete_cards_only_in_main_radar"] is True
    assert result["checks"]["incomplete_cards_are_candidate_pool_only"] is True
    assert result["checks"]["raw_gnn_edges_are_candidate_pool_only"] is True
    assert result["checks"]["claim_cards_carry_evidence_contract"] is True
    assert result["checks"]["claim_card_public_scores_are_candidate_scores"] is True
    assert result["checks"]["candidate_edges_carry_evidence_contract"] is True
    assert result["checks"]["topic_lens_public_future_growth_uses_candidate_edges"] is True
    assert result["checks"]["ui_radar_main_avoids_raw_edge_cards"] is True
    assert result["checks"]["ui_renders_radar_claim_card_evidence_contract"] is True
    assert result["candidate_edges"] == 1


def test_rd_radar_contract_rejects_technical_score_public_copy(tmp_path):
    _write_product_sources(tmp_path)
    api_path = tmp_path / "echelon/api/graph_visual_backend.py"
    app_path = tmp_path / "web/visual-graph/app.js"
    api_path.write_text(
        api_path.read_text(encoding="utf-8")
        + '\nitem = {"technical_score": d.get("confidence"), "technical_probability": 0.8}\n',
        encoding="utf-8",
    )
    app_path.write_text(
        app_path.read_text(encoding="utf-8")
        + "\nfunction renderBadRadar() { return item.technical_score + '技术评分'; }\n",
        encoding="utf-8",
    )

    result = audit_rd_radar_promotion_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["radar_public_scores_avoid_probability_copy"] is False


def test_main_path_uncertainty_contract_demotes_low_linked_refs(tmp_path):
    _write_product_sources(tmp_path)

    result = audit_main_path_uncertainty_contract(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["low_linked_refs_add_uncertainty"] is True
    assert result["checks"]["main_path_edges_inherit_uncertainty"] is True
    assert result["claim_scope"] == "main_path_context_low_linked_refs"


def test_openalex_frontfill_guard_contract_requires_cooldown_guard(tmp_path):
    _write_makefile_contracts(tmp_path)
    _write_product_sources(tmp_path)

    result = audit_openalex_frontfill_guard(tmp_path)

    assert result["status"] == "pass"
    assert result["checks"]["openalex_backfill_runs_guard_before_fetch"] is True
    assert result["checks"]["guard_blocks_duplicate_backfill"] is True


def test_openalex_frontfill_guard_contract_fails_without_guard(tmp_path):
    (tmp_path / "Makefile").write_text(
        "openalex-backfill:\n\tpython -m echelon.v14b.step0_openalex_backfill\n",
        encoding="utf-8",
    )

    result = audit_openalex_frontfill_guard(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["openalex_backfill_runs_guard_before_fetch"] is False


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
    assert result["checks"]["post_frontfill_rebuilds_section_atom_substrate"] is True
    assert result["checks"]["post_frontfill_requires_decision_grade_section_gates"] is True
    assert result["checks"]["pilot_full_is_legacy_compatibility_only"] is True
    assert result["checks"]["legacy_arxiv_scripts_require_explicit_opt_in"] is True
    assert result["checks"]["step9_openalex_language_is_coverage_not_success"] is True
    assert result["checks"]["step9_algo_report_filename_is_evidence_decision"] is True
    assert result["checks"]["package_docstring_avoids_legacy_pilot_flow"] is True
    assert result["checks"]["step4_and_step9_use_bounded_subgraph_scope"] is True
    assert result["checks"]["step12_and_schema_use_bounded_subgraph_scope"] is True
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


def test_legacy_flow_isolation_contract_rejects_frontend_launch_step9(tmp_path):
    _write_makefile_contracts(tmp_path)
    _write_product_sources(tmp_path)
    _write_legacy_arxiv_script_contracts(tmp_path)
    step9 = tmp_path / "echelon/v14b/step9_report.py"
    step9.write_text(
        "make product-chain make post-frontfill-chain legacy compatibility "
        "OpenAlex W 覆盖率 Field/Topic 覆盖率 coverage is not a success claim\n"
        "前端启动条件 VGAE test AUC 主干道节点 100-200 突变节点 100-300 "
        "_go_nogo_recommendation 可启动 V14-B 前端开发\n",
        encoding="utf-8",
    )

    result = audit_legacy_flow_isolation_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["step9_uses_decision_readiness_not_frontend_launch"] is False


def test_legacy_flow_isolation_contract_rejects_pilot_report_filename_and_docstring(tmp_path):
    _write_makefile_contracts(tmp_path)
    _write_product_sources(tmp_path)
    _write_legacy_arxiv_script_contracts(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "config.py").write_text(
        'REPORT_ALGO_VALIDATION = REPORT_DIR / "V14B_Pilot_算法验证报告.md"\n',
        encoding="utf-8",
    )
    (v14 / "__init__.py").write_text(
        "Echelon V14-B 演化树 Pilot 模块\n"
        "包含完整的 9-step 演化树分析流程\n"
        "Step 1: OpenAlex enrich\n",
        encoding="utf-8",
    )

    result = audit_legacy_flow_isolation_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["step9_algo_report_filename_is_evidence_decision"] is False
    assert result["checks"]["package_docstring_avoids_legacy_pilot_flow"] is False


def test_legacy_flow_isolation_contract_rejects_pilot_subgraph_scope_copy(tmp_path):
    _write_makefile_contracts(tmp_path)
    _write_product_sources(tmp_path)
    _write_legacy_arxiv_script_contracts(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "step4_subgraph.py").write_text(
        "pilot_evidence_subgraph pilot_adequate_for_algorithmic_evidence\n",
        encoding="utf-8",
    )
    (v14 / "step9_report.py").write_text(
        "make product-chain make post-frontfill-chain legacy compatibility "
        "OpenAlex W 覆盖率 Field/Topic 覆盖率 coverage is not a success claim "
        "证据决策放行条件 Topic Dossier multi-topic regression "
        "Radar 主视图只允许完整 Step13 Claim Card candidate_pool_only "
        "V14B_Evidence_Decision_算法验证报告.md "
        "pilot_evidence_subgraph pilot/evidence 与 V12.5 Pilot 对比\n",
        encoding="utf-8",
    )

    result = audit_legacy_flow_isolation_contract(tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["step4_and_step9_use_bounded_subgraph_scope"] is False


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
                        "section_decision_grade_ready": False,
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
    assert "section_decision_grade_ready" in result["invalid_examples"][0]["missing"]
    assert "decision_grade_current_contract_section_evidence" in result["invalid_examples"][0]["missing"]
    conn.close()


def test_claim_card_high_confidence_contract_rejects_threshold_relaxation_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "step9_report.py").write_text(
        "OpenAlex W 覆盖率 Field/Topic 覆盖率 coverage is not a success claim\n"
        "Limitation: 如 high-confidence resolution < 30%,放宽阈值到 0.5\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        )
        """
    )

    result = audit_claim_card_high_confidence_evidence_contract(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["step9_does_not_recommend_threshold_relaxation"] is False
    conn.close()


def test_claim_card_high_confidence_contract_rejects_direction_confidence_gate(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "step13_first_principles_history.py").write_text(
        "section_evidence_strong section_provenance_ready missing_high_confidence_gates "
        'direction_confidence_ready "direction_confidence": "future-growth graph confidence"\n',
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        )
        """
    )

    result = audit_claim_card_high_confidence_evidence_contract(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["step13_uses_candidate_score_gate"] is False
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


def test_llm_evidence_boundary_rejects_step5c_llm_default_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "step5c_limitation.py").write_text(
        "Step 5c\n"
        "Phase 2: LLM 把 limitation 段原子化\n"
        "Phase 3: 对每个 atom 遍历后续引用,LLM 判 resolution\n"
        "extractor_method LIMITATION_USE_LLM else None _limitation_evidence_common\n",
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        "## Step 5c: Limitation Tracking (~4h, ~$40 LLM 费用)\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    result = audit_llm_evidence_boundary(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["limitation_user_copy_is_section_first"] is False
    assert result["checks"]["makefile_limitation_target_avoids_llm_cost_claim"] is False
    conn.close()


def test_llm_evidence_boundary_rejects_hidden_scibert_llm_fallback_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "step5a_scibert.py").write_text(
        "若模型不可用,自动降级到 LLM 分类。\n"
        "低置信度的降级到 LLM\n"
        "--use-llm SCIBERT_LLM_FALLBACK citation_function_evidence_level\n",
        encoding="utf-8",
    )
    (v14 / "config.py").write_text(
        'V14B_LIMITATION_USE_LLM", "false"\n'
        'V14B_SCIBERT_LLM_FALLBACK", "false"\n'
        'V14B_FUSION_USE_LLM_NAMING", "false"\n'
        "# 置信度阈值,低于此值降级到 LLM 分类\n",
        encoding="utf-8",
    )
    (v14 / "step9_report.py").write_text(
        "OpenAlex W 覆盖率 Field/Topic 覆盖率 coverage is not a success claim\n"
        "考虑换 LLM 分类\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    result = audit_llm_evidence_boundary(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["citation_llm_fallback_explicit_and_weak"] is False
    conn.close()


def test_llm_evidence_boundary_rejects_scibert_report_claim_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "echelon/v14b"
    (v14 / "step9_report.py").write_text(
        "OpenAlex W 覆盖率 Field/Topic 覆盖率 coverage is not a success claim\n"
        "capped LLM edge audit LLM 结果只能作为弱标签 不能直接升级结论\n"
        "SciBERT 分类完成率 SciBERT 引用功能分布\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    result = audit_llm_evidence_boundary(conn, tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["citation_llm_fallback_explicit_and_weak"] is False
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


def test_future_growth_audit_rejects_step9_vgae_prediction_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    step9_path = tmp_path / "echelon/v14b/step9_report.py"
    step9_path.write_text(
        "make product-chain make post-frontfill-chain legacy compatibility\n"
        "VGAE 预测未来边数\n"
        "## 7. VGAE Link Prediction\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["step9_vgae_language_is_candidate_generator"] is False


def test_future_growth_audit_rejects_step9_public_prediction_fields(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "V14B_Evidence_Decision_算法验证报告.md").write_text(
        "## 7. Future Candidate Generator\n"
        "`predicted_prob`/`calibrated_prob` 是候选排序信号\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path, report_dir)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["step9_vgae_language_is_candidate_generator"] is False


def test_future_growth_audit_rejects_future_report_legacy_score_labels(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "未来候选方向_证据合同报告.md").write_text(
        "| # | 候选方向 | 排序分数 | claim_scope |\n"
        "| 1 | x | 0.8 | candidate_pool_only |\n"
        "- **排序分数**: **0.8**\n"
        "GNN/VGAE candidate edge: calibrated=0.9, raw=0.8, candidate_score=0.7\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path, report_dir)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["future_direction_report_uses_candidate_score_labels"] is False


def test_future_growth_audit_rejects_api_future_evidence_legacy_score_labels(tmp_path):
    _write_product_sources(tmp_path)
    api_path = tmp_path / "echelon/api/graph_visual_backend.py"
    api_path.write_text(
        "def _future_candidate_evidence_text(): return 'GNN/VGAE candidate edge candidate_score='\n",
        encoding="utf-8",
    )
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path, report_dir)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["step6_future_evidence_avoids_prediction_copy"] is False


def test_future_growth_audit_rejects_lifecycle_score_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "future_candidate_lifecycle_audit.md").write_text(
        "- p1 -> p2: state=future_candidate_unfused, score=0.700, reason=Step5b candidate\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path, report_dir)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["future_lifecycle_uses_candidate_score_labels"] is False


def test_future_growth_audit_rejects_prediction_report_filename(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    config_path = tmp_path / "echelon/v14b/config.py"
    config_path.write_text(
        'REPORT_FUTURE_DIRECTIONS = REPORT_DIR / "未来方向预测_交集报告.md"\n',
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["future_report_filename_is_candidate_contract"] is False


def test_future_growth_audit_rejects_prediction_copy_in_current_docs(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "100h_value_delivery_plan.md").write_text(
        "Future candidate generation exists: 1,000 predicted future edges.\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["current_docs_label_future_edges_as_candidates"] is False


def test_future_growth_audit_rejects_probability_copy_in_current_docs(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "100h_value_delivery_plan.md").write_text(
        "Make future growth a calibrated probability product with clear limits.\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["current_docs_label_future_edges_as_candidates"] is False


def test_future_growth_audit_rejects_radar_probability_copy_in_current_docs(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "end_to_end_audit_goals_20260530.md").write_text(
        "Each Radar item must expose technical probability and claim scope.\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["current_docs_label_future_edges_as_candidates"] is False


def test_future_growth_audit_rejects_builder_predicted_edges_contract(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    builder_path = tmp_path / "echelon/v14b/step10_visual_graph_builder.py"
    builder_path.write_text(
        '"predicted_edges": child_future\n'
        "Predicted growth arcs and unresolved limitations\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["topic_dossier_builders_use_candidate_edges_contract"] is False


def test_future_growth_audit_rejects_public_model_probability_keys(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    api_path = tmp_path / "echelon/api/graph_visual_backend.py"
    api_path.write_text(
        api_path.read_text(encoding="utf-8")
        + '\nmodel_evidence = {"calibrated_prob": evidence.get("calibrated_prob"), "raw_predicted_prob": evidence.get("raw_predicted_prob")}\n',
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["public_future_model_evidence_uses_candidate_score_labels"] is False


def test_future_growth_audit_rejects_visual_future_edges_without_contract(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    conn = sqlite3.connect(str(v14))
    conn.executescript(
        """
        DROP TABLE visual_edges;
        CREATE TABLE visual_edges (
            edge_type TEXT,
            layer TEXT,
            evidence_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO visual_edges VALUES (?, ?, ?)",
        ("future_growth", "future", json.dumps({"candidate_score": 0.72})),
    )
    conn.commit()

    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["visual_future_edges_carry_contract"] is False
    assert result["future_visual_edge_contract"]["bad_contract_edges"] == 1


def test_future_growth_audit_rejects_future_recommendations_without_contract(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    conn = sqlite3.connect(str(v14))
    conn.executescript(
        """
        CREATE TABLE visual_recommendations (
            mode TEXT,
            reason_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO visual_recommendations VALUES (?, ?)",
        ("future", json.dumps({"why": "future prediction support", "candidate_score": 0.72})),
    )
    conn.commit()

    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["future_recommendations_carry_contract"] is False
    assert result["future_visual_recommendation_contract"]["bad_contract_recommendations"] == 1


def test_future_growth_audit_rejects_ui_future_calibration_probability_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    app_path = tmp_path / "web/visual-graph/app.js"
    app_path.write_text(
        app_path.read_text(encoding="utf-8")
        + "\nfunction badFutureCalibrationCopy(edge) { return evidence.calibrated_prob + ' / raw ' + evidence.raw_predicted_prob + ' edge score'; }\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["ui_future_calibration_copy_uses_candidate_score_labels"] is False


def test_future_growth_audit_rejects_direction_readiness_prediction_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "direction_readiness_audit.md").write_text(
        '"calibration_json": "{\\"prediction_confidence_avg\\": 0.83, \\"min_vgae_confidence\\": 0.55}"\n',
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path, report_dir)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["direction_readiness_report_uses_candidate_score_labels"] is False


def test_future_growth_audit_rejects_step12_vgae_confidence_copy(tmp_path):
    _write_product_sources(tmp_path)
    v14 = tmp_path / "v14.sqlite3"
    _make_v14(v14)
    step12_path = tmp_path / "echelon/v14b/step12_goal_alignment_audit.py"
    step12_path.write_text(
        step12_path.read_text(encoding="utf-8")
        + '\nkey_map = {"min_vgae_confidence": "min_vgae_candidate_score", "vgae_top_n": "vgae_top_n"}\n'
        + 'report_line = "top_vgae_candidate_edges_used"\n',
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
    (report_dir / "goal_alignment_audit_step1_step6.md").write_text(
        "candidate_ranking_score_avg min_vgae_candidate_score vgae_top_n "
        "top_vgae_candidate_edges_used\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(v14))
    result = audit_future_growth(conn, tmp_path, report_dir)
    conn.close()

    assert result["status"] == "fail"
    assert result["checks"]["step12_goal_alignment_report_uses_candidate_score_labels"] is False


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


def test_multi_topic_audit_rejects_stale_gold_topic_plan_docs(tmp_path):
    report_dir = tmp_path / "reports/v14b_pilot"
    report_dir.mkdir(parents=True)
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
        'parser.add_argument("--topic", default="all")\n',
        encoding="utf-8",
    )
    (report_dir / "100h_value_delivery_plan.md").write_text(
        "Create gold expectations for each topic.\n",
        encoding="utf-8",
    )

    result = audit_multi_topic_regression(report_dir, repo_root=tmp_path)

    assert result["status"] == "fail"
    assert result["checks"]["current_plan_docs_avoid_gold_topic_language"] is False


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
    assert multi["topic_gap_decision_grade_section_papers"] == 0
    assert multi["topic_gap_decision_grade_section_rate"] == 0.0


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
