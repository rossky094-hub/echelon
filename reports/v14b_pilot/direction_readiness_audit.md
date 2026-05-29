# Direction Readiness Audit

- generated_at: `2026-05-29T17:49:22Z`
- readiness_level: `candidate_generator_only`

## Metrics

- linked refs: 443,443 / 3,201,174 (13.9%)
- OpenAlex W IDs: 34,549 (62.4%)
- section evidence: 1,310 rows / 725 papers
- primary section evidence: 725 papers (1.3%)
- section frontfill health: running_or_unknown [section_delta] (done=None/None, no_evidence_delta=0, no_evidence_hours=0.0)
- predicted future edges: 1,000
- visual future edges: 1,000
- future directions: 0
- Claim Cards: 0; complete=0; high_confidence=0

## Blockers

- **citation_graph_bone** (high): linked refs are 13.9%; branch/main-path claims need uncertainty labels. Next: Continue provider ID repair and reference relinking after OpenAlex/S2 identifiers stabilize.
- **section_evidence** (high): primary section evidence covers only 725 papers. Next: Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.
- **fusion_materialization** (high): Step5b produced future candidates but live future_directions is empty. Next: After section evidence improves, rerun Step5c -> Step6 -> Step13; do not promote raw GNN edges.
- **openalex_topic_coverage** (medium): OpenAlex W coverage is 62.4%; cross-field claims need uncertainty. Next: Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.

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

## Future Candidate Lifecycle

- total candidates: 1,000
- radar eligible: 0

| state | count |
| --- | ---: |
| future_candidate_unfused | 1,000 |

### Missing Claim Gates

| gate | count |
| --- | ---: |
| Step13 Claim Card | 1,000 |
| Step6 fusion direction | 1,000 |

## Product Interpretation

- `candidate_generator_only` means the graph can suggest where to inspect, but Radar must stay empty.
- `actionable_but_not_high_confidence` means Claim Cards are complete but still exploratory.
- `decision_grade_available` requires high-confidence Claim Cards with calibrated future evidence and strong section evidence.
