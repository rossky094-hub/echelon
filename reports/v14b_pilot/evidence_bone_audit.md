# V14B Evidence Bone Audit

- generated_at: `2026-05-31T00:16:49Z`

## Reference Linkage

- linked refs: 449,041 / 3,215,350 (14.0%)
- unlinked refs: 2,766,309

| unlinked kind | count |
| --- | ---: |
| doi_unlinked | 1,410,283 |
| openalex_unlinked | 1,292,604 |
| s2_unlinked | 55,806 |
| arxiv_unlinked | 7,616 |

### Reference Relink Diagnosis

- status: `local_corpus_gap_dominates`
- scanned unlinked refs: 2,766,309
- exact-linkable refs: 0
- no-local-match refs: 2,766,309
- next action: Prioritize high-value cited-work backfill for missing DOI/OpenAlex/S2/arXiv references; broad relinking has little remaining yield until the cited papers exist locally.

### Cited Work Backfill Queue

- status: `ready`
- queued exact provider-ID targets: 2,000
- provider mix: `{"arxiv": 1, "doi": 902, "openalex": 1054, "s2": 43}`
- path: `data/v14b/cited_work_backfill_queue.csv`

### Cited Work Backfill Run

- status: `ran`
- processed targets: 5
- inserted/updated local works: 4
- status counts: `{"fetch_failed": 1, "inserted": 4}`
- relink updates applied: `3084`

## Section Evidence

- section rows: 5,429
- section papers: 3,020
- primary section papers: 3,020
- current parser-contract primary section papers: 284
- decision-grade primary section papers: 284

### High-Value Priority Coverage

| category | total | in topN | any section | primary section | current parser primary | decision-grade primary | eligible PDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cluster_representative | 5,946 | 5,322 | 699 | 699 | 12 | 12 | 5,946 |
| active_learning_uncertainty_hotspot | 3,000 | 650 | 373 | 373 | 0 | 0 | 3,000 |
| branch_split_driver | 2,007 | 2,007 | 946 | 946 | 59 | 59 | 2,007 |
| main_path_node | 1,101 | 1,101 | 237 | 237 | 95 | 95 | 1,101 |
| top_keystone | 1,000 | 1,000 | 438 | 438 | 114 | 114 | 1,000 |
| resolution_evidence | 464 | 206 | 170 | 170 | 34 | 34 | 464 |
| future_endpoint | 291 | 291 | 109 | 109 | 45 | 45 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 101 | 101 | 268 |
| topic:metalens | 257 | 86 | 96 | 96 | 18 | 18 | 257 |
| topic:quantum light source | 226 | 73 | 40 | 40 | 12 | 12 | 226 |
| topic:photonic crystal cavity | 150 | 45 | 20 | 20 | 9 | 9 | 150 |
| topic_gap_key_turning_section | 23 | 10 | 6 | 6 | 0 | 0 | 23 |
| topic:metasurface holography | 20 | 9 | 7 | 7 | 4 | 4 | 20 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 11 | 11 | 14 |
| topic_gap_bottleneck_evidence | 10 | 1 | 1 | 1 | 0 | 0 | 10 |

### Latest Section Ingest Outcomes

| outcome | papers |
| --- | ---: |
| no_target_sections | 4,976 |
| success_primary | 1,939 |
| already_has_primary | 401 |
| success_secondary_only | 283 |
| pdf_download_failed | 46 |
| parse_no_blocks | 1 |

## Frontfill Log Signals

| event | count |
| --- | ---: |
| pdf_graphics_warning | 55,916 |
| download_failure | 22,646 |
| parser_exception | 3 |
| timeout | 1 |

- section progress: 310/8592 (logs/v14b/step5s_section_delta.log)

## Frontfill Health

- status: `insufficient_but_running`
- source: `section_delta`
- progress: `310/8592`
- rows / papers / primary papers: `5,429` / `3,020` / `3,020`
- candidates since last evidence growth: `0`
- seconds since last evidence growth: `0`
- recommendation: Continue section frontfill and keep all bottleneck/Claim Card conclusions scoped until the high-value primary-section budget is met.

## Recommended Next Actions

- Continue cited-work backfill in small exact-ID batches; rerun exact relink and graph features after each batch.
- Use DOI refs as exact cited-work backfill targets; avoid fuzzy title matching for citation evidence.
- Continue OpenAlex W cited-work backfill and rerun exact relink after each successful batch.
- Normalize arXiv version/category variants, then ingest high-value missing arXiv cited works.
- Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.
- After top12000 completes, run the delta/action queue for high-value papers missing decision-grade primary sections.
- Prioritize decision-grade section evidence for weak high-value classes: cluster_representative, active_learning_uncertainty_hotspot, branch_split_driver, main_path_node, top_keystone, resolution_evidence, future_endpoint, topic:metalens
- Retry only high-value retryable PDF failures with conservative concurrency; do not broaden to all PDFs.
- Mark no_target_sections papers as weak evidence unless alternate parser/Sci-Bot sections are available.
- Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.
- Keep single-process section ingest and add retry classification before increasing concurrency.

## Product Interpretation

Evidence Bone remains the limiting factor if linked refs are below 30% or primary section evidence is below the high-value claim budget. The graph can guide inspection, but claims must remain scoped and uncertainty-labeled.
