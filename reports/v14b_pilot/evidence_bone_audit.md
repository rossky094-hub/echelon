# V14B Evidence Bone Audit

- generated_at: `2026-05-30T19:50:29Z`

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

- section rows: 5,168
- section papers: 2,942
- primary section papers: 2,942

### High-Value Priority Coverage

| category | total | in topN | any section | primary section | eligible PDF |
| --- | ---: | ---: | ---: | ---: | ---: |
| cluster_representative | 5,958 | 5,331 | 699 | 699 | 5,958 |
| active_learning_uncertainty_hotspot | 3,000 | 647 | 363 | 363 | 3,000 |
| branch_split_driver | 1,970 | 1,970 | 964 | 964 | 1,970 |
| main_path_node | 1,101 | 1,101 | 230 | 230 | 1,101 |
| top_keystone | 1,000 | 1,000 | 378 | 378 | 1,000 |
| resolution_evidence | 464 | 207 | 170 | 170 | 464 |
| future_endpoint | 291 | 291 | 109 | 109 | 291 |
| limitation_evidence | 268 | 268 | 268 | 268 | 268 |
| topic:metalens | 257 | 86 | 91 | 91 | 257 |
| topic:quantum light source | 226 | 73 | 41 | 41 | 226 |
| topic:photonic crystal cavity | 135 | 33 | 10 | 10 | 135 |
| topic_gap_key_turning_section | 26 | 13 | 9 | 9 | 26 |
| topic:metasurface holography | 18 | 5 | 4 | 4 | 18 |
| topic_gap_claim_card_inputs | 14 | 14 | 11 | 11 | 14 |
| topic_gap_bottleneck_evidence | 9 | 1 | 5 | 5 | 9 |
| topic_evidence_gap | 8 | 2 | 3 | 3 | 8 |

### Latest Section Ingest Outcomes

| outcome | papers |
| --- | ---: |
| no_target_sections | 4,914 |
| success_primary | 1,706 |
| already_has_primary | 466 |
| success_secondary_only | 283 |
| pdf_download_failed | 45 |
| parse_no_blocks | 1 |

## Frontfill Log Signals

| event | count |
| --- | ---: |
| pdf_graphics_warning | 54,871 |
| download_failure | 22,643 |
| parser_exception | 3 |
| timeout | 1 |

- section progress: 877/6603 (logs/v14b/step5s_section_delta.log)

## Frontfill Health

- status: `insufficient_but_running`
- source: `section_delta`
- progress: `877/6603`
- rows / papers / primary papers: `5,168` / `2,942` / `2,942`
- candidates since last evidence growth: `0`
- seconds since last evidence growth: `0`
- recommendation: Continue section frontfill and keep all bottleneck/Claim Card conclusions scoped until the high-value primary-section budget is met.

## Recommended Next Actions

- Run DOI-normalized relinking before adding more crawlers; DOI refs should be exact local joins.
- Continue OpenAlex W backfill and relink W IDs after each successful batch.
- Normalize arXiv version/category variants, then relink against arxiv_id.
- Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.
- After top12000 completes, run delta queue for high-value papers missing primary sections.
- Prioritize section evidence for weak high-value classes: cluster_representative, active_learning_uncertainty_hotspot, topic:quantum light source, topic:photonic crystal cavity
- Retry only high-value retryable PDF failures with conservative concurrency; do not broaden to all PDFs.
- Mark no_target_sections papers as weak evidence unless alternate parser/Sci-Bot sections are available.
- Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.
- Keep single-process section ingest and add retry classification before increasing concurrency.

## Product Interpretation

Evidence Bone remains the limiting factor if linked refs are below 30% or primary section evidence is below the high-value claim budget. The graph can guide inspection, but claims must remain scoped and uncertainty-labeled.
