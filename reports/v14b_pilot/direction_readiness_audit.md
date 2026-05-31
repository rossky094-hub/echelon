# Direction Readiness Audit

- generated_at: `2026-05-31T04:12:50Z`
- readiness_level: `actionable_but_not_high_confidence`

## Metrics

- linked refs: 451,905 / 3,215,592 (14.1%)
- reference relink audit: `local_corpus_gap_dominates`; exact-linkable=0; no-local-match=2,763,687
- cited-work backfill queue: `ready`; targets=2,000; providers={"arxiv": 1, "doi": 903, "openalex": 1051, "s2": 45}
- cited-work backfill run: `ran`; processed=10; inserted_or_updated=6
- OpenAlex W IDs: 35,673 (64.4%)
- OpenAlex frontfill health: stalled_after_cooldown [openalex_backfill_current] (processed=3000/22643, ok=2898, fail=102, cooldown_hours=0.0)
- section evidence: 5,515 rows / 3,024 papers
- primary section evidence: 3,024 papers (5.5%)
- primary section provenance: 1,176 strong/moderate papers; weak-only=61.1%
- current section parser contract: 425 papers (14.1%)
- section parser contracts: legacy_unknown_contract:4,533, v14b_section_parser_contract_v3_toc_guard:982
- multi-topic evidence-gap queue: 23 / 47 decision-grade section covered (48.9%); raw primary=23 (48.9%)
- topic-gap section triage: `fail`; current-parser no-target=22; stale-contract=0; unattempted-PDF=2
- topic-gap no-target inspection: `pass`; parser-target-signal=0; subthreshold-target-signal=2; sectionless/non-target-heading=11
- section frontfill health: running_or_unknown [section_delta] (done=227/8373, no_evidence_delta=0, no_evidence_hours=0.0, current_contract_primary=423, contract_status=running_or_unknown, no_current_contract_delta=0, no_current_contract_hours=0.0)
- raw PDF store: `warn`; success=1,959; probable_pdf_rate=100.0%; section_cache_papers=0; topic_gap_local_pdf=5/47
- future candidate edges: 1,000
- visual future edges: 1,000
- future directions: 5
- Claim Cards: 5; complete=1; high_confidence=0

## Blockers

- **citation_graph_bone** (high): linked refs are 14.1%; branch/main-path claims need uncertainty labels. Reference relink audit: 0 exact-linkable, 2,763,687 no-local-match. Next: Continue processing the remaining cited-work queue in small exact-ID batches; rerun exact relink and graph features after each applied batch.
- **section_evidence** (high): primary section evidence covers only 3,024 papers. Next: Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.
- **section_evidence_provenance** (medium): primary section evidence quality is still fragile: 1,176 papers have strong/moderate parser provenance; weak-only rate is 61.1%. Next: Use explicit/embedded heading evidence for bottleneck and Claim Card promotion; keep loose/legacy section matches as weak evidence until manually audited or re-parsed.
- **section_parser_contract_coverage** (medium): primary section evidence has current parser-contract coverage for only 425/3,024 papers (14.1%); legacy parser-contract sections may predate TOC/fragment guards. Next: Re-run section evidence with the current parser contract before promoting section-derived bottleneck, Topic Dossier, or Claim Card claims.
- **multi_topic_evidence_gap** (high): multi-topic regression still has decision-grade section evidence for only 23/47 queued benchmark-topic papers (48.9%); raw primary-section coverage is 23/47 (48.9%). Triage: current-parser no-target=22, stale-contract=0, unattempted-PDF=2. Typed-chain triage: atoms-missing=3, chains-missing=5, full-chain-missing=4, topic-mismatch=0. No-target inspection: parser-target-signal=0, subthreshold-target-signal=2, sectionless/non-target-heading=11. Next: Do not loosen the current parser for the no-target bucket; keep those papers as weak full-text or metadata evidence and focus repair effort on stale-contract reparse and unattempted PDFs.
- **raw_pdf_cache_reuse** (medium): external raw PDF cache has 1,959 successful PDFs, but section evidence has not yet consumed local-cache PDFs. Topic-gap queue local PDF availability is 5/47. Next: At the next safe section-ingest boundary, start Step5s with V14B_RAW_PDF_STORE_ROOT, V14B_RAW_PDF_MANIFEST, and V14B_SECTION_INGEST_PREFER_LOCAL_RAW_PDF=true.
- **openalex_topic_coverage** (medium): OpenAlex W coverage is 64.4%; cross-field claims need uncertainty. Next: Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.
- **openalex_frontfill_health** (high): OpenAlex frontfill is stalled_after_cooldown; processed=3000/22643, cooldown_remaining_hours=0.0. Next: Restart conservative OpenAlex backfill or run local field-topic repair before cross-corpus or cross-field claims are treated as decision-grade.

## Latest Fusion Audit

```json
{
  "run_id": "20260530T225250Z",
  "terminals_considered": 50,
  "candidate_edges_used": 500,
  "future_candidate_edges_total": 1000,
  "cross_field_candidate_edges_total": 60,
  "unresolved_limitations_used": 50,
  "fusion_candidates": 5,
  "fusion_directions": 5,
  "adequacy_label": "limited_but_usable_with_uncertainty",
  "remaining_risk": "If Step5b/Step5c evidence remains sparse, Step6 should output few or zero directions. Do not lower thresholds blindly; improve branch-lineage, candidate generation, limitation section evidence, and calibration first.",
  "created_at": "2026-05-30 22:52:50",
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
    "status": {
      "calibrated_with_run_audit": 5
    },
    "candidate_ranking_score_avg": 0.8329225875546147,
    "min_candidate_score_threshold": 0.55,
    "candidate_edges_used": 500,
    "decision_grade_limitation_sections": 0
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
