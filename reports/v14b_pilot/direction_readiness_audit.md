# Direction Readiness Audit

- generated_at: `2026-05-29T16:48:13Z`
- readiness_level: `candidate_generator_only`

## Metrics

- linked refs: 442,932 / 3,198,284 (13.8%)
- OpenAlex W IDs: 34,318 (62.0%)
- section evidence: 1,241 rows / 690 papers
- primary section evidence: 690 papers (1.2%)
- predicted future edges: 1,000
- visual future edges: 1,000
- future directions: 0
- Claim Cards: 0; complete=0; high_confidence=0

## Blockers

- **citation_graph_bone** (high): linked refs are 13.8%; branch/main-path claims need uncertainty labels. Next: Continue provider ID repair and reference relinking after OpenAlex/S2 identifiers stabilize.
- **section_evidence** (high): primary section evidence covers only 690 papers. Next: Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.
- **fusion_materialization** (high): Step5b produced future candidates but live future_directions is empty. Next: After section evidence improves, rerun Step5c -> Step6 -> Step13; do not promote raw GNN edges.
- **openalex_topic_coverage** (medium): OpenAlex W coverage is 62.0%; cross-field claims need uncertainty. Next: Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.

## Latest Fusion Audit

```json
{
  "run_id": "20260528T052446Z",
  "n_terminals": 50,
  "n_vgae_preds_top": 500,
  "n_vgae_preds_total": 1000,
  "n_cross_field_total": 37,
  "n_unresolved": 50,
  "n_candidates": 20,
  "n_directions": 20,
  "limitation_quality_json": "{\"weak_abstract\": 50}",
  "evidence_path_json": "{\"2\": 20}",
  "adequacy_label": "adequate_candidate_set",
  "remaining_risk": "If Step5b/Step5c evidence remains sparse, Step6 should output few or zero directions. Do not lower thresholds blindly; improve branch-lineage, candidate generation, limitation section evidence, and calibration first.",
  "created_at": "2026-05-28 05:24:46",
  "candidate_tier_json": "{\"exploratory_weak_limitation\": 20}",
  "calibration_json": "{\"labels\": {\"calibrated_temporal_holdout\": 20}, \"prediction_confidence_avg\": 0.8517545731272295, \"min_vgae_confidence\": 0.55, \"vgae_top_n\": 500}"
}
```

## Product Interpretation

- `candidate_generator_only` means the graph can suggest where to inspect, but Radar must stay empty.
- `actionable_but_not_high_confidence` means Claim Cards are complete but still exploratory.
- `decision_grade_available` requires high-confidence Claim Cards with calibrated future evidence and strong section evidence.
