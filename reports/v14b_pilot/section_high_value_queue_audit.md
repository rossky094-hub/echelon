# V14B Section High-Value Queue Audit

- audit_ts: `2026-05-30T21:00:02Z`
- current top_n budget: `12000`
- high-value papers considered: `12,797`
- next delta queue needing primary section/action: `5,996`
- multi-topic evidence-gap rows merged: `42` (55 papers)
- topic evidence-gap delta queue: `41` papers

## Failure / Retry Classes

| retry_class | count |
|---|---:|
| not_attempted_pdf_available | 5,928 |
| no_target_sections | 4,211 |
| covered | 2,614 |
| retryable_pdf_failure | 43 |
| parser_failure | 1 |

## Category Coverage

| category | total | in topN | any section | primary section | eligible PDF |
|---|---:|---:|---:|---:|---:|
| active_learning_uncertainty_hotspot | 3,000 | 650 | 373 | 373 | 3,000 |
| branch_split_driver | 2,007 | 2,007 | 944 | 944 | 2,007 |
| cluster_representative | 5,946 | 5,322 | 698 | 698 | 5,946 |
| future_endpoint | 291 | 291 | 109 | 109 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 268 |
| main_path_node | 1,101 | 1,101 | 230 | 230 | 1,101 |
| resolution_evidence | 464 | 206 | 170 | 170 | 464 |
| top_keystone | 1,000 | 1,000 | 420 | 420 | 1,000 |
| topic:metalens | 257 | 86 | 91 | 91 | 257 |
| topic:metasurface holography | 20 | 9 | 5 | 5 | 20 |
| topic:photonic crystal cavity | 151 | 46 | 19 | 19 | 151 |
| topic:quantum light source | 234 | 80 | 41 | 41 | 234 |
| topic_gap_bottleneck_evidence | 11 | 1 | 0 | 0 | 11 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 14 |
| topic_gap_key_turning_section | 35 | 20 | 3 | 3 | 35 |

## Why This Matters

This queue is the evidence budget for limitation extraction, bottleneck lineage, Claim Cards, Topic Lens, and the R&D Radar. Papers missing primary section evidence cannot support high-confidence claims even if they are important graph nodes.

Multi-topic regression gaps are merged into this budget so failed Topic Dossiers become targeted section evidence work instead of passive report failures.

Delta queue CSV: `data/v14b/section_delta_queue.csv`
Topic evidence-gap delta CSV: `data/v14b/topic_evidence_gap_delta_queue.csv`
