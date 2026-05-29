# V14B Evidence Bone Audit

- generated_at: `2026-05-29T16:58:25Z`

## Reference Linkage

- linked refs: 442,988 / 3,198,611 (13.8%)
- unlinked refs: 2,755,623

| unlinked kind | count |
| --- | ---: |
| doi_unlinked | 1,412,488 |
| openalex_unlinked | 1,279,713 |
| s2_unlinked | 55,806 |
| arxiv_unlinked | 7,616 |

## Section Evidence

- section rows: 1,241
- section papers: 690
- primary section papers: 690

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

## Frontfill Log Signals

| event | count |
| --- | ---: |
| download_failure | 22,614 |
| pdf_graphics_warning | 3,044 |

- section progress: 1020/12000

## Recommended Next Actions

- Run DOI-normalized relinking before adding more crawlers; DOI refs should be exact local joins.
- Continue OpenAlex W backfill and relink W IDs after each successful batch.
- Normalize arXiv version/category variants, then relink against arxiv_id.
- Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.
- After top12000 completes, run delta queue for high-value papers missing primary sections.
- Prioritize section evidence for weak high-value classes: cluster_representative, active_learning_uncertainty_hotspot, branch_split_driver, main_path_node, top_keystone, resolution_evidence, future_endpoint, topic:metalens
- Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.
- Keep single-process section ingest and add retry classification before increasing concurrency.

## Product Interpretation

Evidence Bone remains the limiting factor if linked refs are below 30% or primary section evidence is below the high-value claim budget. The graph can guide inspection, but claims must remain scoped and uncertainty-labeled.
