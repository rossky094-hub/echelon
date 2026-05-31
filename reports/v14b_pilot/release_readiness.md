# V14B Release Readiness

- generated_at: `2026-05-31T12:44:13Z`
- release_status: `evidence_gated_not_release_ready`
- acceptance_ready: `false`
- evidence_policy: `insufficient_evidence`
- direction_readiness_level: `actionable_but_not_high_confidence`

## Readiness Checks

| Check | Ready |
| --- | --- |
| post_frontfill_finishes_with_decision_audit | pass |
| section_atom_retrieval_substrate_available | pass |
| section_embeddings_materialized | hold |
| multi_topic_regression_passed | hold |
| value_delivery_has_no_failures | hold |
| radar_has_high_confidence_claim_card | hold |
| raw_pdf_store_available | pass |
| path_challenge_audit_available | pass |
| path_challenge_path_aligned | hold |
| evidence_repair_priority_available | pass |
| evidence_repair_has_no_blocking_p0 | hold |

## Frontfill Snapshot

- section_frontfill_status: `running_or_unknown`
- section_frontfill_done: `532`
- section_frontfill_total: `8373`
- section_current_contract_primary: `722`
- paper_sections: `5688`
- section_atoms: `61708`
- section_atom_embeddings: `61708`
- section_embeddings: `None`
- direction_claim_cards: `5`
- high_confidence_claim_cards: `0`
- raw_pdf_store_status: `pass`

## Gate Blockers

- **Evidence Bone** `warn`: All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes.
- **Multi-topic Regression** `fail`: Topic value must be tested across multiple optics themes, not tuned only for Metalens. Benchmark topics are regression fixtures, not product allowlists or LLM cost-control gates; the active regression and product-baseline entrypoints must default to the full benchmark suite, and topic-gap repair is blocked until queued papers have decision-grade current-contract section evidence. When blocked, a topic-gap section triage report must identify whether the next repair is current-contract reparse, parser/full-text inspection, access recovery, or targeted ingest. Current-parser no-target papers require a no-target PDF inspection before parser thresholds can be loosened.

## Direction Blockers

- **citation_graph_bone** `high`: linked refs are 14.1%; branch/main-path claims need uncertainty labels. Reference relink audit: 0 exact-linkable, 2,763,687 no-local-match. Next: Continue processing the remaining cited-work queue in small exact-ID batches; rerun exact relink and graph features after each applied batch.
- **section_evidence** `high`: primary section evidence covers only 3,030 papers. Next: Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.
- **section_evidence_provenance** `medium`: primary section evidence quality is still fragile: 1,445 papers have strong/moderate parser provenance; weak-only rate is 52.3%. Next: Use explicit/embedded heading evidence for bottleneck and Claim Card promotion; keep loose/legacy section matches as weak evidence until manually audited or re-parsed.
- **section_parser_contract_coverage** `medium`: primary section evidence has current parser-contract coverage for only 729/3,030 papers (24.1%); legacy parser-contract sections may predate TOC/fragment guards. Next: Re-run section evidence with the current parser contract before promoting section-derived bottleneck, Topic Dossier, or Claim Card claims.
- **multi_topic_evidence_gap** `high`: multi-topic regression still has decision-grade section evidence for only 45/78 queued benchmark-topic papers (57.7%); raw primary-section coverage is 48/78 (61.5%). Triage: current-parser no-target=17, stale-contract=2, unattempted-PDF=8. Typed-chain triage: atoms-missing=0, chains-missing=1, full-chain-missing=1, topic-mismatch=0. Missing stages: constraint:1, attempted_path:1, local_fix:1. Repair-contract closure: closed=17/215 (7.9%). No-target inspection: parser-target-signal=0, subthreshold-target-signal=1, sectionless/non-target-heading=10. Next: Do not loosen the current parser for the no-target bucket; keep those papers as weak full-text or metadata evidence and focus repair effort on stale-contract reparse and unattempted PDFs.
- **openalex_topic_coverage** `medium`: OpenAlex W coverage is 64.4%; cross-field claims need uncertainty. Next: Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.

## Required Next Actions

- **P0** Wait for the active broad section ingest to reach a safe boundary, then run post-frontfill-chain. Why: Section-level fuzzy context is code-complete but not materialized; downstream Claim Cards need the rebuilt section retrieval substrate and decision-audit refresh. Command: `make post-frontfill-chain`
- **P0** Continue targeted benchmark-topic evidence repair before promoting Topic Dossier or Radar conclusions. Why: Multi-topic regression still has benchmark-topic decision-grade section gaps. Command: `make topic-gap-repair`
- **P1** Process exact-ID cited-work batches, then rerun exact relinking and graph features. Why: linked refs are 14.1%; branch/main-path claims need uncertainty labels. Reference relink audit: 0 exact-linkable, 2,763,687 no-local-match. Command: `make cited-work-backfill && make reference-relink-apply && make graph-features`
- **P2** Continue conservative OpenAlex/local field-topic repair without treating coverage as a success claim. Why: OpenAlex W coverage is 64.4%; cross-field claims need uncertainty. Command: `make openalex-backfill`

## Evidence Repair Priority

- status: `evidence_first_repair_required`
- summary: `{"blocking_p0": 3, "can_run_while_broad_ingest_active": 2, "counts_by_priority": {"P0": 3, "P1": 1, "P2": 2}, "items": 6, "requires_db_writer_boundary": 4, "top_action_id": "topic_gap_evidence_repair", "top_command": "make topic-gap-repair"}`
- **P0** `topic_gap_evidence_repair` command: `make topic-gap-repair` db_writer_boundary: `True`
- **P0** `post_frontfill_retrieval_rebuild` command: `make post-frontfill-chain` db_writer_boundary: `True`
- **P0** `typed_stage_candidate_review` command: `make topic-gap-stage-candidate-recall` db_writer_boundary: `False`
- **P1** `exact_cited_work_backfill` command: `make cited-work-backfill && make reference-relink-apply && make graph-features` db_writer_boundary: `True`
- **P2** `openalex_field_topic_repair` command: `make openalex-backfill` db_writer_boundary: `True`

## Product Boundary

This report is a release gate, not a scientific conclusion. Green tests or graph renderability alone do not make the system decision-grade. Topic Dossier, Evolution Evidence Map, Claim Card, and R&D Radar output must remain evidence-scoped until the failed and held checks above are closed by current-state evidence.
