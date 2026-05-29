# V14B Value Delivery Audit

- generated_at: `2026-05-29T16:58:27Z`
- evidence_policy: `insufficient_evidence`
- gate_summary: `{"fail": 1, "pass": 3, "warn": 4}`

## Eight Product Gates

| # | Gate | Status | What This Enforces |
| ---: | --- | --- | --- |
| 1 | Evidence Bone | warn | All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes. |
| 2 | Bottleneck Lineage Graph | warn | Lineage is evidence-backed only when triples carry section/page evidence; otherwise it remains weak historical context. |
| 3 | Branch Lineage Validity | pass | Only evidence_backed_split can be narrated as scientific branch evolution; weak_split_candidate and layout_cluster_only must be labeled as such. |
| 4 | Future Growth Calibration | warn | VGAE/GNN is a future candidate generator only. Radar promotion requires Step6 fusion plus Step13 complete Claim Card. |
| 5 | Claim Card Engine | warn | A card missing any of the five hard questions is candidate_pool_only and cannot enter Radar. |
| 6 | Topic Dossier Product Value | pass | Topic Lens first screen must answer branches, bottlenecks, turning papers, and validation candidates before raw graph exploration. |
| 7 | Multi-topic Regression | fail | Topic value must be tested across multiple optics themes, not tuned only for Metalens. |
| 8 | Quarterly / Multi-corpus | pass | Quarterly optics/cs/materials runs must use corpus_id scoping and snapshots; no step should be hardwired to optics-only product logic. |

## Gate Details

### Evidence Bone

```json
{
  "evidence_grade": "very_thin_evidence_bone",
  "issue": "Evidence Bone",
  "metrics": {
    "linked_ref_rate": 0.13849386499327365,
    "openalex_w_rate": 0.6202090592334495,
    "primary_section_papers": 690
  },
  "policy": "All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes.",
  "status": "warn",
  "uncertainty_reasons": [
    "linked refs below 30%; citation backbone is incomplete",
    "section-level evidence below decision-grade target",
    "OpenAlex topic/field coverage below cross-field target",
    "future-growth calibration audit missing"
  ]
}
```

### Bottleneck Lineage Graph

```json
{
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
  "status": "warn",
  "triples": 2920,
  "triples_with_page": 0
}
```

### Branch Lineage Validity

```json
{
  "branches": 5426,
  "issue": "Branch Lineage Validity",
  "missing_columns": [],
  "policy": "Only evidence_backed_split can be narrated as scientific branch evolution; weak_split_candidate and layout_cluster_only must be labeled as such.",
  "status": "pass",
  "status_counts": {
    "evidence_backed_split": 107,
    "layout_cluster_only": 4185,
    "weak_split_candidate": 1134
  }
}
```

### Future Growth Calibration

```json
{
  "bad_high_confidence_cards": 0,
  "calibration_audits": 0,
  "future_candidate_lifecycle": {
    "future_candidate_unfused": 1000
  },
  "issue": "Future Growth Calibration",
  "policy": "VGAE/GNN is a future candidate generator only. Radar promotion requires Step6 fusion plus Step13 complete Claim Card.",
  "predicted_future_edges": 1000,
  "radar_eligible_candidates": 0,
  "status": "warn"
}
```

### Claim Card Engine

```json
{
  "bad_high_confidence_cards": 0,
  "cards": 0,
  "complete_cards": 0,
  "high_confidence_cards": 0,
  "issue": "Claim Card Engine",
  "missing_columns": [],
  "policy": "A card missing any of the five hard questions is candidate_pool_only and cannot enter Radar.",
  "status": "warn"
}
```

### Topic Dossier Product Value

```json
{
  "has_visual_search_fts": true,
  "issue": "Topic Dossier Product Value",
  "policy": "Topic Lens first screen must answer branches, bottlenecks, turning papers, and validation candidates before raw graph exploration.",
  "status": "pass",
  "visual_edges": 739318,
  "visual_nodes": 55391
}
```

### Multi-topic Regression

```json
{
  "failed_topics": [
    "metalens",
    "metasurface holography",
    "photonic crystal cavity",
    "quantum light source"
  ],
  "gold_topics": [
    "metalens",
    "metasurface holography",
    "photonic crystal cavity",
    "quantum light source"
  ],
  "issue": "Multi-topic Regression",
  "live_regression_status": "fail",
  "missing_topics": [],
  "policy": "Topic value must be tested across multiple optics themes, not tuned only for Metalens.",
  "status": "fail"
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
