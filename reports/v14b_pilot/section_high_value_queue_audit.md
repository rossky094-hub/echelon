# V14B Section High-Value Queue Audit

- audit_ts: `2026-05-30T23:21:35Z`
- current top_n budget: `12000`
- high-value papers considered: `12,795`
- primary section papers: `3,020`; current parser-contract primary: `223`; decision-grade primary: `223`
- next delta queue needing primary section/action: `8,373`
- multi-topic evidence-gap rows merged: `30` (42 papers)
- topic evidence-gap delta queue: `31` papers

## Failure / Retry Classes

| retry_class | count |
|---|---:|
| not_attempted_pdf_available | 5,878 |
| no_target_sections | 4,227 |
| stale_parser_contract | 2,429 |
| covered | 217 |
| retryable_pdf_failure | 43 |
| parser_failure | 1 |

## Category Coverage

| category | total | in topN | any section | primary section | current parser primary | decision-grade primary | eligible PDF |
|---|---:|---:|---:|---:|---:|---:|---:|
| active_learning_uncertainty_hotspot | 3,000 | 650 | 373 | 373 | 0 | 0 | 3,000 |
| branch_split_driver | 2,007 | 2,007 | 946 | 946 | 59 | 59 | 2,007 |
| cluster_representative | 5,946 | 5,322 | 699 | 699 | 12 | 12 | 5,946 |
| future_endpoint | 291 | 291 | 109 | 109 | 45 | 45 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 101 | 101 | 268 |
| main_path_node | 1,101 | 1,101 | 237 | 237 | 95 | 95 | 1,101 |
| resolution_evidence | 464 | 206 | 170 | 170 | 34 | 34 | 464 |
| top_keystone | 1,000 | 1,000 | 438 | 438 | 114 | 114 | 1,000 |
| topic:metalens | 257 | 86 | 96 | 96 | 18 | 18 | 257 |
| topic:metasurface holography | 20 | 9 | 7 | 7 | 4 | 4 | 20 |
| topic:photonic crystal cavity | 150 | 45 | 20 | 20 | 9 | 9 | 150 |
| topic:quantum light source | 226 | 73 | 40 | 40 | 12 | 12 | 226 |
| topic_gap_bottleneck_evidence | 10 | 1 | 1 | 1 | 0 | 0 | 10 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 11 | 11 | 14 |
| topic_gap_key_turning_section | 23 | 10 | 6 | 6 | 0 | 0 | 23 |

## Why This Matters

This queue is the evidence budget for limitation extraction, bottleneck lineage, Claim Cards, Topic Lens, and the R&D Radar. Papers missing primary section evidence cannot support high-confidence claims even if they are important graph nodes.

Multi-topic regression gaps are merged into this budget so failed Topic Dossiers become targeted section evidence work instead of passive report failures.

Delta queue CSV: `data/v14b/section_delta_queue.csv`
Topic evidence-gap delta CSV: `data/v14b/topic_evidence_gap_delta_queue.csv`
