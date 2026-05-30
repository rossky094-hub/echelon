# Direction Readiness Audit

- generated_at: `2026-05-30T19:47:10Z`
- readiness_level: `actionable_but_not_high_confidence`

## Metrics

- linked refs: 445,957 / 3,215,130 (13.9%)
- OpenAlex W IDs: 35,663 (64.4%)
- OpenAlex frontfill health: cooling_down_or_stopped [openalex_backfill_current] (processed=3000/22643, ok=2898, fail=102, cooldown_hours=4.2)
- section evidence: 5,168 rows / 2,942 papers
- primary section evidence: 2,942 papers (5.3%)
- primary section provenance: 705 strong/moderate papers; weak-only=76.0%
- multi-topic evidence-gap queue: 0 / 20 primary-section covered (0.0%)
- section frontfill health: running_or_unknown [section_delta] (done=877/6603, no_evidence_delta=0, no_evidence_hours=0.0)
- future candidate edges: 1,000
- visual future edges: 1,000
- future directions: 5
- Claim Cards: 5; complete=1; high_confidence=0

## Blockers

- **citation_graph_bone** (high): linked refs are 13.9%; branch/main-path claims need uncertainty labels. Next: Continue provider ID repair and reference relinking after OpenAlex/S2 identifiers stabilize.
- **section_evidence** (high): primary section evidence covers only 2,942 papers. Next: Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.
- **section_evidence_provenance** (medium): primary section evidence quality is still fragile: 705 papers have strong/moderate parser provenance; weak-only rate is 76.0%. Next: Use explicit/embedded heading evidence for bottleneck and Claim Card promotion; keep loose/legacy section matches as weak evidence until manually audited or re-parsed.
- **multi_topic_evidence_gap** (high): multi-topic regression still has primary section evidence for 0/20 queued benchmark-topic papers (0.0%). Next: After the active top12000 ingest finishes, run make topic-gap-repair to refresh regression gaps, rebuild the topic-gap section queue, ingest targeted papers, and re-audit before promoting Topic Dossier, bottleneck lineage, or Claim Card conclusions.
- **openalex_topic_coverage** (medium): OpenAlex W coverage is 64.4%; cross-field claims need uncertainty. Next: Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.
- **openalex_frontfill_health** (medium): OpenAlex frontfill is cooling_down_or_stopped; processed=3000/22643, cooldown_remaining_hours=4.2. Next: Respect the OpenAlex 429 cooldown; resume conservative backfill after cooldown before promoting cross-field/topic claims.

## Latest Fusion Audit

```json
{
  "run_id": "20260529T175949Z",
  "terminals_considered": 50,
  "candidate_edges_used": 500,
  "future_candidate_edges_total": 1000,
  "cross_field_candidate_edges_total": 60,
  "unresolved_limitations_used": 50,
  "fusion_candidates": 5,
  "fusion_directions": 5,
  "adequacy_label": "limited_but_usable_with_uncertainty",
  "remaining_risk": "If Step5b/Step5c evidence remains sparse, Step6 should output few or zero directions. Do not lower thresholds blindly; improve branch-lineage, candidate generation, limitation section evidence, and calibration first.",
  "created_at": "2026-05-29 17:59:49",
  "limitation_quality_distribution": {
    "section_level": 50
  },
  "evidence_path_distribution": {
    "2": 5
  },
  "candidate_tier_distribution": {
    "exploratory": 5
  },
  "calibration_summary": {
    "labels": {
      "calibrated_temporal_holdout": 5
    },
    "candidate_ranking_score_avg": 0.8329225875546147,
    "min_candidate_score_threshold": 0.55,
    "candidate_edges_used": 500
  }
}
```

## Future Candidate Lifecycle

- total candidates: 1,000
- radar eligible: 0

| state | count |
| --- | ---: |
| candidate_pool_incomplete_claim_card | 21 |
| exploratory_claim_card | 421 |
| future_candidate_unfused | 558 |

### Missing Claim Gates

| gate | count |
| --- | ---: |
| Step13 Claim Card | 558 |
| Step6 fusion direction | 558 |
| historical attempts and failure evidence | 21 |
| unresolved bottleneck evidence | 4 |

## Product Interpretation

- `candidate_generator_only` means the graph can suggest where to inspect, but Radar must stay empty.
- `actionable_but_not_high_confidence` means Claim Cards are complete but still exploratory.
- `decision_grade_available` requires high-confidence Claim Cards with calibrated future evidence and strong section evidence.
