# V14B Section High-Value Queue Audit

- audit_ts: `2026-05-30T15:36:18Z`
- current top_n budget: `12000`
- high-value papers considered: `12,514`
- next delta queue needing primary section/action: `6,184`
- multi-topic evidence-gap rows merged: `32` (46 papers)
- topic evidence-gap delta queue: `20` papers

## Failure / Retry Classes

| retry_class | count |
|---|---:|
| not_attempted_pdf_available | 6,118 |
| no_target_sections | 4,084 |
| covered | 2,266 |
| retryable_pdf_failure | 45 |
| parser_failure | 1 |

## Category Coverage

| category | total | in topN | any section | primary section | eligible PDF |
|---|---:|---:|---:|---:|---:|
| active_learning_uncertainty_hotspot | 3,000 | 647 | 360 | 360 | 3,000 |
| branch_split_driver | 1,970 | 1,970 | 679 | 679 | 1,970 |
| cluster_representative | 5,958 | 5,331 | 698 | 698 | 5,958 |
| future_endpoint | 291 | 291 | 96 | 96 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 268 |
| main_path_node | 1,101 | 1,101 | 230 | 230 | 1,101 |
| resolution_evidence | 464 | 207 | 170 | 170 | 464 |
| top_keystone | 1,000 | 1,000 | 355 | 355 | 1,000 |
| topic:metalens | 257 | 86 | 87 | 87 | 257 |
| topic:metasurface holography | 8 | 2 | 3 | 3 | 8 |
| topic:photonic crystal cavity | 7 | 1 | 3 | 3 | 7 |
| topic:quantum light source | 19 | 15 | 11 | 11 | 19 |
| topic_evidence_gap | 8 | 2 | 3 | 3 | 8 |
| topic_gap_bottleneck_evidence | 9 | 1 | 5 | 5 | 9 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 14 |
| topic_gap_key_turning_section | 26 | 13 | 9 | 9 | 26 |

## Why This Matters

This queue is the evidence budget for limitation extraction, bottleneck lineage, Claim Cards, Topic Lens, and the R&D Radar. Papers missing primary section evidence cannot support high-confidence claims even if they are important graph nodes.

Multi-topic regression gaps are merged into this budget so failed Topic Dossiers become targeted section evidence work instead of passive report failures.

Delta queue CSV: `data/v14b/section_delta_queue.csv`
Topic evidence-gap delta CSV: `data/v14b/topic_evidence_gap_delta_queue.csv`
