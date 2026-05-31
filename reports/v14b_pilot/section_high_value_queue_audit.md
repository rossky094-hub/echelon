# V14B Section High-Value Queue Audit

- audit_ts: `2026-05-31T12:40:18Z`
- current top_n budget: `12000`
- high-value papers considered: `12,465`
- primary section papers: `3,030`; current parser-contract primary: `727`; decision-grade primary: `723`
- next delta queue needing primary section/action: `7,787`
- multi-topic evidence-gap rows merged: `70` (78 papers)
- topic repair contracts preserved: `32` rows / `74` papers
- topic evidence-gap delta queue: `33` papers

## Failure / Retry Classes

| retry_class | count |
|---|---:|
| not_attempted_pdf_available | 5,858 |
| no_target_sections | 4,042 |
| stale_parser_contract | 1,877 |
| covered | 633 |
| retryable_pdf_failure | 42 |
| not_attempted_no_pdf | 10 |
| weak_current_contract | 2 |
| parser_failure | 1 |

## Category Coverage

| category | total | in topN | any section | primary section | current parser primary | decision-grade primary | eligible PDF |
|---|---:|---:|---:|---:|---:|---:|---:|
| active_learning_uncertainty_hotspot | 3,000 | 660 | 372 | 372 | 1 | 1 | 2,990 |
| branch_split_driver | 2,035 | 2,035 | 927 | 927 | 190 | 190 | 2,025 |
| cluster_representative | 5,942 | 5,321 | 698 | 698 | 27 | 27 | 5,937 |
| future_endpoint | 291 | 291 | 109 | 109 | 82 | 82 | 291 |
| limitation_evidence | 349 | 349 | 349 | 349 | 277 | 277 | 349 |
| main_path_node | 1,101 | 1,101 | 237 | 237 | 181 | 181 | 1,101 |
| top_keystone | 1,000 | 1,000 | 438 | 438 | 304 | 304 | 1,000 |
| topic:metalens | 259 | 88 | 98 | 98 | 33 | 33 | 259 |
| topic:metasurface holography | 35 | 23 | 18 | 18 | 17 | 17 | 35 |
| topic:photonic crystal cavity | 155 | 50 | 26 | 26 | 21 | 20 | 155 |
| topic:quantum light source | 238 | 85 | 53 | 53 | 41 | 40 | 238 |
| topic_evidence_gap | 21 | 6 | 4 | 4 | 4 | 3 | 21 |
| topic_gap_bottleneck_evidence | 45 | 35 | 35 | 35 | 34 | 33 | 45 |
| topic_gap_claim_card_inputs | 17 | 17 | 12 | 12 | 11 | 11 | 17 |
| topic_gap_key_turning_section | 26 | 12 | 1 | 1 | 1 | 0 | 26 |

## Why This Matters

This queue is the evidence budget for limitation extraction, bottleneck lineage, Claim Cards, Topic Lens, and the R&D Radar. Papers missing primary section evidence cannot support high-confidence claims even if they are important graph nodes.

Multi-topic regression gaps are merged into this budget so failed Topic Dossiers become targeted section evidence work instead of passive report failures.

Delta queue CSV: `data/v14b/section_delta_queue.csv`
Topic evidence-gap delta CSV: `data/v14b/topic_evidence_gap_delta_queue.csv`
