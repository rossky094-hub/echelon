# Direction Readiness Audit

- generated_at: `2026-05-31T05:57:18Z`
- readiness_level: `actionable_but_not_high_confidence`

## Metrics

- linked refs: 451,932 / 3,215,711 (14.1%)
- reference relink audit: `local_corpus_gap_dominates`; exact-linkable=0; no-local-match=2,763,687
- cited-work backfill queue: `ready`; targets=2,000; providers={"arxiv": 1, "doi": 903, "openalex": 1051, "s2": 45}
- cited-work backfill run: `ran`; processed=10; inserted_or_updated=6
- OpenAlex W IDs: 35,681 (64.4%)
- OpenAlex frontfill health: completed [step0_openalex_backfill_20260531_135214] (processed=25/25, ok=8, fail=17, cooldown_hours=0.0)
- section evidence: 5,555 rows / 3,029 papers
- primary section evidence: 3,029 papers (5.5%)
- primary section provenance: 1,230 strong/moderate papers; weak-only=59.4%
- current section parser contract: 495 papers (16.3%)
- section parser contracts: legacy_unknown_contract:4,426, v14b_section_parser_contract_v3_toc_guard:1,129
- multi-topic evidence-gap queue: 16 / 38 decision-grade section covered (42.1%); raw primary=20 (52.6%)
- topic-gap section triage: `fail`; current-parser no-target=18; stale-contract=0; unattempted-PDF=0
- topic-gap no-target inspection: `pass`; parser-target-signal=0; subthreshold-target-signal=2; sectionless/non-target-heading=11
- section frontfill health: running_or_unknown [section_delta] (done=293/8373, no_evidence_delta=0, no_evidence_hours=0.0, current_contract_primary=487, contract_status=running_or_unknown, no_current_contract_delta=0, no_current_contract_hours=0.0)
- raw PDF store: `pass`; success=2,679; probable_pdf_rate=100.0%; section_cache_papers=6; topic_gap_local_pdf=7/38
- topic-gap raw PDF parser dry run: `warn`; local=7; primary-ready=2; repair-ready=0; no-target=1; parser-exception=0; no-target-shapes=sectionless_or_non_target_heading_format:1; actions=weak_primary_context_only:4, already_covered_parser_control:2, weak_fulltext_or_metadata_only:1
- future candidate edges: 1,000
- visual future edges: 1,000
- future directions: 5
- Claim Cards: 5; complete=5; high_confidence=0

## Blockers

- **citation_graph_bone** (high): linked refs are 14.1%; branch/main-path claims need uncertainty labels. Reference relink audit: 0 exact-linkable, 2,763,687 no-local-match. Next: Continue processing the remaining cited-work queue in small exact-ID batches; rerun exact relink and graph features after each applied batch.
- **section_evidence** (high): primary section evidence covers only 3,029 papers. Next: Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.
- **section_evidence_provenance** (medium): primary section evidence quality is still fragile: 1,230 papers have strong/moderate parser provenance; weak-only rate is 59.4%. Next: Use explicit/embedded heading evidence for bottleneck and Claim Card promotion; keep loose/legacy section matches as weak evidence until manually audited or re-parsed.
- **section_parser_contract_coverage** (medium): primary section evidence has current parser-contract coverage for only 495/3,029 papers (16.3%); legacy parser-contract sections may predate TOC/fragment guards. Next: Re-run section evidence with the current parser contract before promoting section-derived bottleneck, Topic Dossier, or Claim Card claims.
- **multi_topic_evidence_gap** (high): multi-topic regression still has decision-grade section evidence for only 16/38 queued benchmark-topic papers (42.1%); raw primary-section coverage is 20/38 (52.6%). Triage: current-parser no-target=18, stale-contract=0, unattempted-PDF=0. Typed-chain triage: atoms-missing=0, chains-missing=1, full-chain-missing=1, topic-mismatch=0. No-target inspection: parser-target-signal=0, subthreshold-target-signal=2, sectionless/non-target-heading=11. Next: Do not loosen the current parser for the no-target bucket; keep those papers as weak full-text or metadata evidence and focus repair effort on stale-contract reparse and unattempted PDFs.
- **openalex_topic_coverage** (medium): OpenAlex W coverage is 64.4%; cross-field claims need uncertainty. Next: Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.

## Latest Fusion Audit

```json
{
  "run_id": "20260531T054601Z",
  "terminals_considered": 50,
  "candidate_edges_used": 500,
  "future_candidate_edges_total": 1000,
  "cross_field_candidate_edges_total": 60,
  "unresolved_limitations_used": 50,
  "fusion_candidates": 5,
  "fusion_directions": 5,
  "adequacy_label": "limited_but_usable_with_uncertainty",
  "remaining_risk": "If Step5b/Step5c evidence remains sparse, Step6 should output few or zero directions. Do not lower thresholds blindly; improve branch-lineage, candidate generation, limitation section evidence, and calibration first.",
  "created_at": "2026-05-31 05:46:01",
  "limitation_quality_distribution": {
    "section_level": 50
  },
  "evidence_path_distribution": {
    "3": 5
  },
  "candidate_tier_distribution": {
    "triangulated_limited": 5
  },
  "calibration_summary": {
    "labels": {
      "calibrated_temporal_holdout": 5
    },
    "status": {
      "calibrated_with_run_audit": 5
    },
    "candidate_ranking_score_avg": 0.8329225875546147,
    "min_candidate_score_threshold": 0.55,
    "candidate_edges_used": 500,
    "decision_grade_limitation_sections": 41,
    "chain_supported_candidates": 5,
    "decision_grade_section_atom_chain_candidates": 5
  }
}
```

## Future Candidate Lifecycle

- total candidates: 1,000
- radar eligible: 0

| state | count |
| --- | ---: |
| exploratory_claim_card | 500 |
| future_candidate_unfused | 500 |

### Missing Claim Gates

| gate | count |
| --- | ---: |
| Step13 Claim Card | 500 |
| Step6 fusion direction | 500 |

## Product Interpretation

- `candidate_generator_only` means the graph can suggest where to inspect, but Radar must stay empty.
- `actionable_but_not_high_confidence` means Claim Cards are complete but still exploratory.
- `decision_grade_available` requires high-confidence Claim Cards with calibrated future evidence and strong section evidence.
