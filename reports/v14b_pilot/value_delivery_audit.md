# V14B Value Delivery Audit

- generated_at: `2026-05-30T17:04:53Z`
- evidence_policy: `insufficient_evidence`
- gate_summary: `{"fail": 1, "pass": 13, "warn": 1}`

## Product Gates

| # | Gate | Status | What This Enforces |
| ---: | --- | --- | --- |
| 1 | Evidence Bone | warn | All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes. |
| 2 | OpenAlex Frontfill Guard Contract | pass | OpenAlex field/topic backfill must respect provider 429 cooldowns and avoid duplicate runs; cross-field conclusions remain uncertainty-labeled until coverage and cooldown health recover. |
| 3 | Bottleneck Lineage Graph | pass | Lineage is evidence-backed only when triples carry section/page evidence; otherwise it remains weak historical context. |
| 4 | Branch Lineage Validity | pass | Only evidence_backed_split can be narrated as scientific branch evolution; weak_split_candidate and layout_cluster_only must be labeled as such, and graph cluster panels must render the same evidence contract. |
| 5 | Future Growth Calibration | pass | VGAE/GNN is a future candidate generator only. Direction claims require run-level rolling held-out-year calibration; Radar promotion also requires Step6 fusion plus Step13 complete Claim Card. |
| 6 | Claim Card Engine | pass | A card missing any of the five hard questions is candidate_pool_only and cannot enter Radar. The minimal validation experiment must include cost, cycle, success criteria, and falsification conditions. |
| 7 | Claim Card High-Confidence Evidence Contract | pass | A Claim Card can be high-confidence only when Step13 quality gates show strong section evidence and strong/moderate parser provenance; weak or missing section evidence keeps it exploratory. |
| 8 | LLM Evidence Boundary Contract | pass | LLM may audit, name, classify weak labels, or explain existing evidence; it must not create decision-grade evidence unless the claim is anchored to structured evidence and carries uncertainty. |
| 9 | Topic Dossier Product Value | pass | Topic Lens first screen must answer branches, bottlenecks, turning papers, and validation candidates before raw graph exploration. |
| 10 | Evolution Evidence Map Contract | pass | Each Evidence Map layer, top-level Evidence Map section, and recommended layer combination must say what it shows, what it can explain, what it cannot explain, required evidence, claim_scope, evidence_grade, and uncertainty; individual visual edges must carry the same evidence boundary when exposed in API or paper detail. |
| 11 | R&D Radar Promotion Contract | pass | R&D Radar main view may contain only complete Step13 Claim Cards. Incomplete cards and GNN/VGAE future edges remain visible only as candidate_pool evidence-gathering targets. |
| 12 | Main Path Uncertainty Contract | pass | When linked refs are below 30%, citation evolution, main-path claims, Story Mode timeline narratives, selected-paper roles, and visual node hover roles must carry claim_scope, evidence_grade, and uncertainty_reasons. |
| 13 | Legacy Flow Isolation Contract | pass | Current V14B acceptance must run product-chain or post-frontfill-chain, and product-chain must finish with the decision-audit loop: multi-topic regression, topic gap queue refresh, direction readiness, and value delivery. Benchmark-topic evidence gaps must have a targeted repair loop that refreshes regression gaps, refreshes the section queue, ingests topic-gap papers, and re-audits. Old enrich/pilot/arXiv-gap-era flows may remain only as explicitly labeled legacy compatibility targets. |
| 14 | Multi-topic Regression | fail | Topic value must be tested across multiple optics themes, not tuned only for Metalens. Benchmark topics are regression fixtures, not product allowlists or LLM cost-control gates; the active regression entrypoint must default to the full benchmark suite. |
| 15 | Quarterly / Multi-corpus | pass | Quarterly optics/cs/materials runs must use corpus_id scoping and snapshots; no step should be hardwired to optics-only product logic. |

## Gate Details

### Evidence Bone

```json
{
  "evidence_grade": "very_thin_evidence_bone",
  "issue": "Evidence Bone",
  "metrics": {
    "linked_ref_rate": 0.13870574440224812,
    "openalex_frontfill_cooldown_remaining_s": 24906,
    "openalex_frontfill_processed": 3000,
    "openalex_frontfill_status": "cooling_down_or_stopped",
    "openalex_frontfill_total": 22643,
    "openalex_w_rate": 0.6438410572114603,
    "primary_section_papers": 2639,
    "section_frontfill_no_evidence_delta": 0,
    "section_frontfill_status": "running_or_unknown",
    "section_provenance": {
      "paper_quality_counts": {
        "moderate": 0,
        "strong": 402,
        "weak": 2237
      },
      "primary_section_papers": 2639,
      "primary_section_rows": 4602,
      "strategy_counts": {
        "embedded_heading": 19,
        "explicit_heading": 485,
        "heading_continuation": 697,
        "inline_heading": 249,
        "legacy_unknown_strategy": 3886,
        "loose_inline_heading": 12,
        "parser_hint": 8
      },
      "strong_or_moderate_papers": 402,
      "weak_only_papers": 2237,
      "weak_only_rate": 0.8476695718075028
    }
  },
  "policy": "All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes.",
  "status": "warn",
  "uncertainty_reasons": [
    "linked refs below 30%; citation backbone is incomplete",
    "section-level evidence below decision-grade target",
    "OpenAlex topic/field coverage below cross-field target",
    "OpenAlex frontfill cooling_down_or_stopped; field/topic claims need local fallback and uncertainty",
    "section evidence provenance is weak; loose/legacy parser matches must remain low-confidence evidence"
  ]
}
```

### OpenAlex Frontfill Guard Contract

```json
{
  "checks": {
    "guard_blocks_duplicate_backfill": true,
    "guard_reads_openalex_frontfill_state": true,
    "guard_respects_429_cooldown": true,
    "openalex_backfill_runs_guard_before_fetch": true,
    "openalex_backfill_target_present": true
  },
  "issue": "OpenAlex Frontfill Guard Contract",
  "policy": "OpenAlex field/topic backfill must respect provider 429 cooldowns and avoid duplicate runs; cross-field conclusions remain uncertainty-labeled until coverage and cooldown health recover.",
  "status": "pass"
}
```

### Bottleneck Lineage Graph

```json
{
  "checks": {
    "api_bottleneck_constraints_carry_limits": true,
    "typed_stage_chain_complete": true,
    "typed_triples_have_page_evidence": true,
    "ui_renders_bottleneck_lineage_limits": true
  },
  "evidence_grade": "strong_section",
  "issue": "Bottleneck Lineage Graph",
  "missing_stage_pairs": [],
  "policy": "Lineage is evidence-backed only when triples carry section/page evidence; otherwise it remains weak historical context.",
  "stage_pairs": [
    "attempt_path->local_fix",
    "constraint->failure_mechanism",
    "failure_mechanism->attempt_path",
    "local_fix->new_constraint"
  ],
  "status": "pass",
  "triples": 2920,
  "triples_with_page": 540
}
```

### Branch Lineage Validity

```json
{
  "branches": 5286,
  "checks": {
    "api_visual_clusters_carry_lineage_contract": true,
    "branch_lineage_columns_present": true,
    "branch_lineage_statuses_present": true,
    "ui_cluster_panel_renders_lineage_contract": true
  },
  "issue": "Branch Lineage Validity",
  "missing_columns": [],
  "policy": "Only evidence_backed_split can be narrated as scientific branch evolution; weak_split_candidate and layout_cluster_only must be labeled as such, and graph cluster panels must render the same evidence contract.",
  "status": "pass",
  "status_counts": {
    "evidence_backed_split": 52,
    "layout_cluster_only": 4950,
    "weak_split_candidate": 284
  }
}
```

### Future Growth Calibration

```json
{
  "bad_high_confidence_cards": 0,
  "calibration_audits": 1,
  "calibration_gap": null,
  "checks": {
    "edge_level_calibration_not_confused_with_run_audit": true,
    "raw_future_edges_not_radar_eligible": true,
    "run_level_calibration_required_for_direction_claims": true
  },
  "edge_calibrated_candidates": 1000,
  "edge_calibration_labels": {
    "calibrated_temporal_holdout": 1000
  },
  "edge_calibration_methods": {
    "temporal_platt_logistic": 1000
  },
  "edge_calibration_rate": 1.0,
  "future_candidate_lifecycle": {
    "candidate_pool_incomplete_claim_card": 21,
    "exploratory_claim_card": 421,
    "future_candidate_unfused": 558
  },
  "future_direction_calibration_status_counts": {
    "calibrated_with_run_audit": 5
  },
  "future_direction_claim_scope_counts": {
    "exploratory_incomplete_card": 4,
    "exploratory_with_claim_card": 1
  },
  "future_directions": 5,
  "issue": "Future Growth Calibration",
  "policy": "VGAE/GNN is a future candidate generator only. Direction claims require run-level rolling held-out-year calibration; Radar promotion also requires Step6 fusion plus Step13 complete Claim Card.",
  "predicted_future_edges": 1000,
  "radar_eligible_candidates": 0,
  "status": "pass",
  "uncalibrated_promoted_direction_claims": 0,
  "uncalibrated_promoted_examples": []
}
```

### Claim Card Engine

```json
{
  "bad_high_confidence_cards": 0,
  "cards": 5,
  "checks": {
    "complete_cards_have_falsifiable_validation_experiment": true,
    "no_high_confidence_without_complete_card": true,
    "required_columns_present": true,
    "step13_requires_success_and_falsification": true,
    "ui_renders_success_and_falsification": true
  },
  "complete_cards": 1,
  "high_confidence_cards": 0,
  "invalid_minimal_validation_experiments": [],
  "issue": "Claim Card Engine",
  "missing_columns": [],
  "policy": "A card missing any of the five hard questions is candidate_pool_only and cannot enter Radar. The minimal validation experiment must include cost, cycle, success criteria, and falsification conditions.",
  "status": "pass"
}
```

### Claim Card High-Confidence Evidence Contract

```json
{
  "checks": {
    "no_high_confidence_card_without_section_evidence": true,
    "step13_has_section_evidence_gate": true
  },
  "high_confidence_cards": 0,
  "invalid_examples": [],
  "invalid_high_confidence_cards": 0,
  "issue": "Claim Card High-Confidence Evidence Contract",
  "policy": "A Claim Card can be high-confidence only when Step13 quality gates show strong section evidence and strong/moderate parser provenance; weak or missing section evidence keeps it exploratory.",
  "status": "pass"
}
```

### LLM Evidence Boundary Contract

```json
{
  "checks": {
    "abstract_llm_atoms_remain_weak": true,
    "citation_llm_fallback_explicit_and_weak": true,
    "fusion_llm_naming_opt_in": true,
    "limitation_llm_traced_and_optional": true,
    "llm_citation_without_context_remains_weak": true,
    "llm_data_contract_columns_present": true,
    "llm_defaults_off": true,
    "llm_edge_audit_is_capped_audit": true,
    "step13_non_llm_engine": true,
    "topic_preflight_no_llm": true
  },
  "invalid_llm_atom_examples": [],
  "invalid_llm_atoms": 0,
  "invalid_llm_citation_edges": 0,
  "invalid_llm_citation_examples": [],
  "issue": "LLM Evidence Boundary Contract",
  "llm_citation_edges": 0,
  "llm_limitation_atoms": 0,
  "missing_data_contracts": [],
  "policy": "LLM may audit, name, classify weak labels, or explain existing evidence; it must not create decision-grade evidence unless the claim is anchored to structured evidence and carries uncertainty.",
  "status": "pass"
}
```

### Topic Dossier Product Value

```json
{
  "has_visual_search_fts": true,
  "issue": "Topic Dossier Product Value",
  "online_readiness_contract": {
    "checks": {
      "api_exposes_topic_readiness": true,
      "api_limitation_atoms_carry_contract": true,
      "api_reading_path_items_carry_limits": true,
      "api_search_hits_carry_contract": true,
      "api_topic_bottlenecks_use_resolution_evidence": true,
      "api_topic_branch_splits_inherit_lineage": true,
      "api_topic_validation_directions_inherit_claim_card_evidence": true,
      "api_validation_directions_carry_limits": true,
      "arbitrary_topic_not_benchmark_gated": true,
      "no_llm_preflight": true,
      "required_readiness_gates_present": true,
      "topic_regression_uses_shared_contract": true,
      "ui_paper_list_renders_hit_contract": true,
      "ui_renders_limitation_contracts": true,
      "ui_renders_reading_path_limits": true,
      "ui_renders_topic_bottleneck_resolution_counts": true,
      "ui_renders_topic_dossier_branch_contracts": true,
      "ui_renders_topic_readiness": true,
      "ui_renders_validation_direction_evidence_objects": true,
      "ui_renders_validation_direction_limits": true,
      "ui_search_fallback_is_insufficient_evidence": true
    },
    "observed_gates": [
      "auditable reading path",
      "bottleneck evidence candidates",
      "bottleneck lineage typed contracts",
      "branch split candidates",
      "complete Claim Cards",
      "five-question evidence contracts",
      "topic dossier evidence contract",
      "turning papers with access",
      "turning papers with strong/moderate section provenance"
    ],
    "overall_status": "warn",
    "policy": "Any topic must receive a deterministic, no-LLM readiness state; benchmark topics are regression fixtures, not a product allowlist.",
    "readiness_level": "claim_card_available_with_gaps",
    "required_gates": [
      "auditable reading path",
      "bottleneck lineage typed contracts",
      "complete Claim Cards",
      "five-question evidence contracts",
      "topic dossier evidence contract",
      "turning papers with strong/moderate section provenance"
    ],
    "status": "pass"
  },
  "policy": "Topic Lens first screen must answer branches, bottlenecks, turning papers, and validation candidates before raw graph exploration.",
  "status": "pass",
  "visual_edges": 772947,
  "visual_nodes": 55391
}
```

### Evolution Evidence Map Contract

```json
{
  "checks": {
    "api_evidence_map_branches_carry_contract": true,
    "api_evidence_map_future_edges_carry_contract": true,
    "api_evidence_map_main_path_carries_contract": true,
    "api_returns_evidence_map": true,
    "api_visual_edges_carry_contract": true,
    "combination_contracts_present": true,
    "evidence_map_main_path_contract_present": true,
    "fusion_value_is_auditable_layer": true,
    "layer_contracts_present": true,
    "required_layer_combinations_present": true,
    "required_layers_present": true,
    "ui_has_fusion_value_layer_control": true,
    "ui_renders_evidence_map_contract": true,
    "ui_renders_evidence_map_main_path_contract": true,
    "ui_renders_future_edge_contracts": true,
    "ui_renders_local_edge_contracts": true
  },
  "combination_count": 9,
  "fusion_status": "materialized",
  "issue": "Evolution Evidence Map Contract",
  "layer_count": 8,
  "missing_layers": [],
  "missing_required_combinations": [],
  "policy": "Each Evidence Map layer, top-level Evidence Map section, and recommended layer combination must say what it shows, what it can explain, what it cannot explain, required evidence, claim_scope, evidence_grade, and uncertainty; individual visual edges must carry the same evidence boundary when exposed in API or paper detail.",
  "status": "pass"
}
```

### R&D Radar Promotion Contract

```json
{
  "candidate_edges": 1,
  "candidate_pool_items": 2,
  "checks": {
    "api_exposes_candidate_pool": true,
    "candidate_edges_carry_evidence_contract": true,
    "candidate_pool_items_not_eligible": true,
    "claim_cards_carry_evidence_contract": true,
    "complete_cards_only_in_main_radar": true,
    "empty_radar_policy_present": true,
    "incomplete_cards_are_candidate_pool_only": true,
    "raw_gnn_edges_are_candidate_pool_only": true,
    "step9_future_report_has_evidence_contract": true,
    "ui_radar_main_avoids_raw_edge_cards": true,
    "ui_renders_radar_claim_card_evidence_contract": true,
    "ui_separates_radar_from_candidate_pool": true
  },
  "incomplete_claim_cards": 1,
  "issue": "R&D Radar Promotion Contract",
  "main_radar_cards": 1,
  "policy": "R&D Radar main view may contain only complete Step13 Claim Cards. Incomplete cards and GNN/VGAE future edges remain visible only as candidate_pool evidence-gathering targets.",
  "status": "pass"
}
```

### Main Path Uncertainty Contract

```json
{
  "checks": {
    "api_returns_history_contract": true,
    "api_visual_nodes_carry_role_contract": true,
    "api_visual_paper_role_carry_contract": true,
    "api_visual_story_steps_carry_contract": true,
    "history_main_path_has_claim_scope": true,
    "history_main_path_has_evidence_grade": true,
    "history_main_path_has_evidence_objects": true,
    "history_main_path_has_required_evidence": true,
    "low_linked_refs_add_uncertainty": true,
    "main_path_edges_inherit_uncertainty": true,
    "ui_node_hover_renders_role_contract": true,
    "ui_paper_detail_renders_role_contract": true,
    "ui_renders_main_path_uncertainty": true,
    "ui_story_mode_renders_contract": true
  },
  "claim_scope": "main_path_context_low_linked_refs",
  "evidence_grade": "citation_backbone_partial_low_linked_refs",
  "issue": "Main Path Uncertainty Contract",
  "policy": "When linked refs are below 30%, citation evolution, main-path claims, Story Mode timeline narratives, selected-paper roles, and visual node hover roles must carry claim_scope, evidence_grade, and uncertainty_reasons.",
  "status": "pass",
  "uncertainty_reasons": [
    "broader field main-path anchors are separated from topic-specific turning papers",
    "linked refs below 30%; citation backbone is incomplete"
  ]
}
```

### Legacy Flow Isolation Contract

```json
{
  "checks": {
    "current_product_chain_present": true,
    "decision_audit_runs_regression_gap_readiness_value": true,
    "decision_audit_target_present": true,
    "help_prefers_current_chain": true,
    "legacy_arxiv_scripts_require_explicit_opt_in": true,
    "legacy_targets_labeled": true,
    "pilot_full_is_legacy_compatibility_only": true,
    "post_frontfill_entry_present": true,
    "post_frontfill_uses_topic_gap_repair": true,
    "product_chain_runs_decision_audit": true,
    "product_chains_avoid_legacy_targets": true,
    "step9_openalex_language_is_coverage_not_success": true,
    "step9_report_avoids_old_pilot_instruction": true,
    "topic_gap_repair_refreshes_queue_ingests_and_reaudits": true,
    "topic_gap_repair_refuses_concurrent_section_ingest": true,
    "topic_gap_repair_target_present": true
  },
  "current_target_deps": {
    "product-chain": [
      "evidence-prep",
      "first-principles",
      "fusion",
      "goal-audit",
      "graph-prep",
      "id-repair",
      "keystone",
      "layout",
      "limitation",
      "mainpath",
      "mutation",
      "quality-audit",
      "report",
      "reset-pilot",
      "scibert",
      "subgraph",
      "vgae",
      "visual-graph"
    ],
    "product-chain-fast": [
      "embeddings",
      "first-principles",
      "fusion",
      "goal-audit",
      "graph-features",
      "id-repair",
      "keystone",
      "layout",
      "limitation",
      "mainpath",
      "mutation",
      "quality-audit",
      "report",
      "reset-pilot",
      "scibert",
      "section-evidence",
      "subgraph",
      "vgae",
      "visual-graph"
    ]
  },
  "decision_audit_required_targets": [
    "topic-regression",
    "section-queue-audit",
    "direction-readiness-audit",
    "value-delivery-audit"
  ],
  "disallowed_current_deps": {},
  "issue": "Legacy Flow Isolation Contract",
  "legacy_arxiv_scripts_present": [
    "scripts/diff_arxiv_optics_vs_db.py",
    "scripts/fetch_missing_arxiv_optics.sh",
    "scripts/monitor_optics_full_pipeline.sh",
    "scripts/run_arxiv_optics_harvest.sh",
    "scripts/run_arxiv_optics_incremental.sh",
    "scripts/run_step1_arxiv_enrich.sh"
  ],
  "legacy_targets_present": [
    "enrich",
    "pilot",
    "pilot-debug",
    "pilot-full",
    "pilot-graph",
    "pilot-visual"
  ],
  "policy": "Current V14B acceptance must run product-chain or post-frontfill-chain, and product-chain must finish with the decision-audit loop: multi-topic regression, topic gap queue refresh, direction readiness, and value delivery. Benchmark-topic evidence gaps must have a targeted repair loop that refreshes regression gaps, refreshes the section queue, ingests topic-gap papers, and re-audits. Old enrich/pilot/arXiv-gap-era flows may remain only as explicitly labeled legacy compatibility targets.",
  "status": "pass",
  "topic_gap_repair_required_targets": [
    "topic-regression",
    "section-queue-audit",
    "section-evidence-topic-gaps",
    "topic-regression",
    "section-queue-audit",
    "direction-readiness-audit",
    "value-delivery-audit"
  ],
  "unguarded_legacy_arxiv_scripts": [],
  "unlabeled_legacy_targets": []
}
```

### Multi-topic Regression

```json
{
  "benchmark_topics": [
    "metalens",
    "metasurface holography",
    "photonic crystal cavity",
    "quantum light source"
  ],
  "checks": {
    "benchmark_topics_defined": true,
    "live_results_avoid_gold_topic_fields": true,
    "live_results_have_fixture_contract": true,
    "topic_regression_avoids_gold_topic_aliases": true,
    "topic_regression_cli_defaults_to_suite": true
  },
  "failed_topics": [
    "metalens",
    "metasurface holography",
    "photonic crystal cavity",
    "quantum light source"
  ],
  "issue": "Multi-topic Regression",
  "live_regression_status": "fail",
  "missing_topics": [],
  "policy": "Topic value must be tested across multiple optics themes, not tuned only for Metalens. Benchmark topics are regression fixtures, not product allowlists or LLM cost-control gates; the active regression entrypoint must default to the full benchmark suite.",
  "status": "fail",
  "topic_gap_blocking": true,
  "topic_gap_primary_section_papers": 0,
  "topic_gap_primary_section_rate": 0.0,
  "topic_gap_queue_papers": 20
}
```

### Quarterly / Multi-corpus

```json
{
  "issue": "Quarterly / Multi-corpus",
  "missing_make_targets": [],
  "missing_tables": [],
  "policy": "Quarterly optics/cs/materials runs must use corpus_id scoping and snapshots; no step should be hardwired to optics-only product logic.",
  "status": "pass",
  "supports_corpus_id": true
}
```

## Product Rule

The system may show weak evidence, but it must label it. Raw GNN edges, layout clusters, and abstract-only bottlenecks are inspection targets, not decision-grade claims.
