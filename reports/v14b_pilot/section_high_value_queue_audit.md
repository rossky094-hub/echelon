# V14B Section High-Value Queue Audit

- audit_ts: `2026-05-30T23:03:27Z`
- current top_n budget: `12000`
- high-value papers considered: `12,797`
- primary section papers: `3,020`; current parser-contract primary: `162`; decision-grade primary: `162`
- next delta queue needing primary section/action: `8,432`
- multi-topic evidence-gap rows merged: `28` (42 papers)
- topic evidence-gap delta queue: `27` papers

## Failure / Retry Classes

| retry_class | count |
|---|---:|
| not_attempted_pdf_available | 5,875 |
| no_target_sections | 4,228 |
| stale_parser_contract | 2,490 |
| covered | 160 |
| retryable_pdf_failure | 43 |
| parser_failure | 1 |

## Category Coverage

| category | total | in topN | any section | primary section | current parser primary | decision-grade primary | eligible PDF |
|---|---:|---:|---:|---:|---:|---:|---:|
| active_learning_uncertainty_hotspot | 3,000 | 650 | 373 | 373 | 0 | 0 | 3,000 |
| branch_split_driver | 2,007 | 2,007 | 946 | 946 | 52 | 52 | 2,007 |
| cluster_representative | 5,946 | 5,322 | 699 | 699 | 12 | 12 | 5,946 |
| future_endpoint | 291 | 291 | 109 | 109 | 40 | 40 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 62 | 62 | 268 |
| main_path_node | 1,101 | 1,101 | 237 | 237 | 74 | 74 | 1,101 |
| resolution_evidence | 464 | 206 | 170 | 170 | 26 | 26 | 464 |
| top_keystone | 1,000 | 1,000 | 438 | 438 | 73 | 73 | 1,000 |
| topic:metalens | 257 | 86 | 96 | 96 | 16 | 16 | 257 |
| topic:metasurface holography | 20 | 9 | 7 | 7 | 4 | 4 | 20 |
| topic:photonic crystal cavity | 151 | 45 | 21 | 21 | 10 | 10 | 151 |
| topic:quantum light source | 227 | 73 | 43 | 43 | 15 | 15 | 227 |
| topic_gap_bottleneck_evidence | 11 | 1 | 4 | 4 | 4 | 4 | 11 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 11 | 11 | 14 |
| topic_gap_key_turning_section | 21 | 9 | 4 | 4 | 0 | 0 | 21 |

## Why This Matters

This queue is the evidence budget for limitation extraction, bottleneck lineage, Claim Cards, Topic Lens, and the R&D Radar. Papers missing primary section evidence cannot support high-confidence claims even if they are important graph nodes.

Multi-topic regression gaps are merged into this budget so failed Topic Dossiers become targeted section evidence work instead of passive report failures.

Delta queue CSV: `data/v14b/section_delta_queue.csv`
Topic evidence-gap delta CSV: `data/v14b/topic_evidence_gap_delta_queue.csv`
