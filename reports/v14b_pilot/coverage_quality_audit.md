# V14B Coverage / Quality Audit

- Generated: 2026-05-28T23:49:59.061304+00:00
- Corpus scope: **all**
- Overall status: **WARN**

## Core Metrics

- Scoped papers: **55391**
- Expected total: **56251**
- Coverage: **98.47%**
- Missing IDs in latest diff file: **25**
- Enriched: **54844** (99.01%)
- Abstract completeness: **55391** (100.00%)
- DOI coverage: **33009** (59.59%)
- External work ID coverage: **30574** (55.20%)
- OpenAlex Field coverage: **55334** (99.90%)
- Graph signal coverage: **55391** (100.00%)
- Embedding coverage: **55391** (100.00%)
- References: **3016141**
- Papers with references: **49640**
- Internal linked references: **414083** (13.73%)

## Gates

| Gate | Status | Value | Threshold | Note |
|---|---:|---:|---|---|
| scope_coverage | **warn** | 98.47% | pass >= 99.5%, warn >= 97% | scoped=55391, expected=56251 |
| missing_id_file | **warn** | 25 | pass = 0, warn < 1% of expected | Remaining IDs from the latest arXiv-vs-DB diff. |
| enrich_coverage | **pass** | 99.01% | pass >= 95%, warn >= 85% | enriched=54844, scoped=55391 |
| abstract_completeness | **pass** | 100.00% | pass >= 98%, warn >= 90% | with_abstract=55391, scoped=55391 |
| reference_coverage | **pass** | 89.62% | pass >= 80%, warn >= 60% | papers_with_refs=49640, scoped=55391 |
| reference_internal_linkage | **warn** | 13.73% | pass >= 25%, warn >= 5% | linked_refs=414083, refs=3016141 |
| openalex_field_coverage | **pass** | 99.90% | pass >= 90%, warn >= 60% | with_field=55334, scoped=55391 |
| graph_signal_coverage | **pass** | 100.00% | pass >= 95%, warn >= 85% | signal_ready=55391, present_signal_cols=12/12 |
| embedding_coverage | **pass** | 100.00% | pass >= 95%, warn >= 85% | embedding_ready=55391, scoped=55391 |
| duplicate_core_ids | **pass** | {"duplicate_doi_groups": 0, "duplicate_arxiv_groups": 0} | pass = no duplicate DOI/arXiv groups | SQLite unique constraints should normally keep this at zero. |
| provider_id_semantics | **pass** | 0 | pass = 0 S2 IDs stored in openalex_id | S2 IDs must be stored in s2_paper_id, not openalex_id. |

## Missing IDs By Year

- 2007: 1
- 2008: 2
- 2010: 2
- 2011: 2
- 2017: 4
- 2019: 1
- 2020: 3
- 2021: 5
- 2022: 1
- 2023: 1
- 2024: 3

## Notes

- Algorithmic audit is the source of truth for coverage and consistency.
- `sample_for_llm_review.jsonl` is for semantic spot-checking, not full-library counting.
- `expert_review_sample.csv` is for final human validation of high-impact / high-score papers.
- `provider_id_semantics` warns when Semantic Scholar IDs are stored in the historical `openalex_id` column.
- Set `--corpus-id` to audit an isolated corpus (optics/cs/materials).
