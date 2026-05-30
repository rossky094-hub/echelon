# V14B Evidence Bone Audit

- generated_at: `2026-05-30T22:39:54Z`

## Reference Linkage

- linked refs: 445,957 / 3,215,130 (13.9%)
- unlinked refs: 2,769,173

| unlinked kind | count |
| --- | ---: |
| doi_unlinked | 1,412,488 |
| openalex_unlinked | 1,293,263 |
| s2_unlinked | 55,806 |
| arxiv_unlinked | 7,616 |

## Section Evidence

- section rows: 5,345
- section papers: 3,020
- primary section papers: 3,020
- current parser-contract primary section papers: 154

### High-Value Priority Coverage

| category | total | in topN | any section | primary section | current parser primary | eligible PDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cluster_representative | 5,946 | 5,322 | 699 | 699 | 12 | 5,946 |
| active_learning_uncertainty_hotspot | 3,000 | 650 | 373 | 373 | 0 | 3,000 |
| branch_split_driver | 2,007 | 2,007 | 946 | 946 | 52 | 2,007 |
| main_path_node | 1,101 | 1,101 | 237 | 237 | 74 | 1,101 |
| top_keystone | 1,000 | 1,000 | 438 | 438 | 65 | 1,000 |
| resolution_evidence | 464 | 206 | 170 | 170 | 26 | 464 |
| future_endpoint | 291 | 291 | 109 | 109 | 40 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 54 | 268 |
| topic:metalens | 257 | 86 | 96 | 96 | 16 | 257 |
| topic:quantum light source | 227 | 73 | 43 | 43 | 15 | 227 |
| topic:photonic crystal cavity | 151 | 45 | 21 | 21 | 10 | 151 |
| topic_gap_key_turning_section | 21 | 9 | 4 | 4 | 0 | 21 |
| topic:metasurface holography | 20 | 9 | 7 | 7 | 4 | 20 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 11 | 14 |
| topic_gap_bottleneck_evidence | 11 | 1 | 4 | 4 | 4 | 11 |

### Latest Section Ingest Outcomes

| outcome | papers |
| --- | ---: |
| no_target_sections | 4,976 |
| success_primary | 1,844 |
| already_has_primary | 439 |
| success_secondary_only | 283 |
| pdf_download_failed | 46 |
| parse_no_blocks | 1 |

## Frontfill Log Signals

| event | count |
| --- | ---: |
| pdf_graphics_warning | 55,727 |
| download_failure | 22,646 |
| parser_exception | 3 |
| timeout | 1 |

- section progress: 180/8592 (logs/v14b/step5s_section_delta.log)

## Frontfill Health

- status: `insufficient_but_running`
- source: `section_delta`
- progress: `180/8592`
- rows / papers / primary papers: `5,345` / `3,020` / `3,020`
- candidates since last evidence growth: `0`
- seconds since last evidence growth: `0`
- recommendation: Continue section frontfill and keep all bottleneck/Claim Card conclusions scoped until the high-value primary-section budget is met.

## Recommended Next Actions

- Run DOI-normalized relinking before adding more crawlers; DOI refs should be exact local joins.
- Continue OpenAlex W backfill and relink W IDs after each successful batch.
- Normalize arXiv version/category variants, then relink against arxiv_id.
- Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.
- After top12000 completes, run delta queue for high-value papers missing current parser-contract primary sections.
- Prioritize current parser-contract section evidence for weak high-value classes: cluster_representative, active_learning_uncertainty_hotspot, branch_split_driver, main_path_node, top_keystone, resolution_evidence, future_endpoint, topic:metalens
- Retry only high-value retryable PDF failures with conservative concurrency; do not broaden to all PDFs.
- Mark no_target_sections papers as weak evidence unless alternate parser/Sci-Bot sections are available.
- Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.
- Keep single-process section ingest and add retry classification before increasing concurrency.

## Product Interpretation

Evidence Bone remains the limiting factor if linked refs are below 30% or primary section evidence is below the high-value claim budget. The graph can guide inspection, but claims must remain scoped and uncertainty-labeled.
