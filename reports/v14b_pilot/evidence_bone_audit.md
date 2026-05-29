# V14B Evidence Bone Audit

- generated_at: `2026-05-29T17:51:03Z`

## Reference Linkage

- linked refs: 443,443 / 3,201,281 (13.9%)
- unlinked refs: 2,757,838

| unlinked kind | count |
| --- | ---: |
| doi_unlinked | 1,412,488 |
| openalex_unlinked | 1,281,928 |
| s2_unlinked | 55,806 |
| arxiv_unlinked | 7,616 |

## Section Evidence

- section rows: 1,312
- section papers: 726
- primary section papers: 726

### High-Value Priority Coverage

| category | total | in topN | any section | primary section | eligible PDF |
| --- | ---: | ---: | ---: | ---: | ---: |
| cluster_representative | 6,115 | 5,478 | 187 | 146 | 6,115 |
| active_learning_uncertainty_hotspot | 3,000 | 555 | 15 | 11 | 3,000 |
| branch_split_driver | 1,819 | 1,819 | 48 | 19 | 1,819 |
| main_path_node | 1,101 | 1,101 | 67 | 38 | 1,101 |
| top_keystone | 1,000 | 1,000 | 350 | 194 | 1,000 |
| resolution_evidence | 464 | 207 | 33 | 22 | 464 |
| future_endpoint | 291 | 291 | 33 | 13 | 291 |
| limitation_evidence | 268 | 268 | 268 | 160 | 268 |
| topic:metalens | 253 | 82 | 15 | 9 | 253 |

### Latest Section Ingest Outcomes

| outcome | papers |
| --- | ---: |
| no_target_sections | 232 |
| success_secondary_only | 31 |
| success_primary | 26 |
| pdf_download_failed | 2 |

## Frontfill Log Signals

| event | count |
| --- | ---: |
| download_failure | 22,616 |
| pdf_graphics_warning | 414 |

- section progress: 291/12227 (logs/v14b/step5s_section_delta.log)

## Frontfill Health

- status: `insufficient_but_running`
- source: `section_delta`
- progress: `None/None`
- rows / papers / primary papers: `1,312` / `726` / `726`
- candidates since last evidence growth: `0`
- seconds since last evidence growth: `0`
- recommendation: Continue section frontfill and keep all bottleneck/Claim Card conclusions scoped until the high-value primary-section budget is met.

## Recommended Next Actions

- Run DOI-normalized relinking before adding more crawlers; DOI refs should be exact local joins.
- Continue OpenAlex W backfill and relink W IDs after each successful batch.
- Normalize arXiv version/category variants, then relink against arxiv_id.
- Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.
- After top12000 completes, run delta queue for high-value papers missing primary sections.
- Prioritize section evidence for weak high-value classes: cluster_representative, active_learning_uncertainty_hotspot, branch_split_driver, main_path_node, top_keystone, resolution_evidence, future_endpoint, topic:metalens
- Retry only high-value retryable PDF failures with conservative concurrency; do not broaden to all PDFs.
- Mark no_target_sections papers as weak evidence unless alternate parser/Sci-Bot sections are available.
- Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.
- Keep single-process section ingest and add retry classification before increasing concurrency.

## Product Interpretation

Evidence Bone remains the limiting factor if linked refs are below 30% or primary section evidence is below the high-value claim budget. The graph can guide inspection, but claims must remain scoped and uncertainty-labeled.
