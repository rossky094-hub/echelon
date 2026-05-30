# V14B Product Baseline Snapshot

- Snapshot: `2026-05-30T22:46:50Z`
- Main DB: `db/echelon_library.sqlite3`
- V14 DB: `db/v14_pilot.sqlite3`

## Coverage

- Papers: 55,391
- OpenAlex W IDs: 35,663 / 55,391 (64.4%); missing 19,728
- Invalid OpenAlex IDs: 0
- Pending enrich: 454
- Primary Field coverage: 55,359 / 55,391 (99.9%)
- References: 3,215,130; linked refs: 445,957 (13.9%)
- Section rows: 5,345; section papers: 3,020; primary evidence papers: 3,020 (5.5%)

## Derived Product Tables

- access_link_audit_items: 6,903
- bottleneck_lineage_triples: 2,920
- branch_lineages: 5,278
- direction_claim_cards: 5
- future_directions: 5
- limitation_atoms: 730
- limitation_resolutions: 1,001
- main_path_cycle_audit: 66
- main_path_edges: 277,526
- future_candidate_edges_table: 1,000
- section_priority_papers: 12,797
- section_priority_summary: 1,547
- subgraph_edges: 38,538
- subgraph_nodes: 5,000
- visual_clusters: 5,278
- visual_edges: 775,406
- visual_nodes: 55,391
- visual_search_fts: 55,391
- visual_tiles: 21,112
- complete Claim Cards: 1
- high-confidence Claim Cards: 0
- access audit: 6,903 papers, 0 gaps
- future_directions by claim_scope: {"exploratory_incomplete_card": 4, "exploratory_with_claim_card": 1}

## Section Evidence Priority Coverage

| Category | Total | In topN | Any section | Primary section | Current parser primary | Eligible PDF |
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

## Multi-topic Topic Baseline

| Topic | Ready | Expected Branch Coverage | Branches | Driver Papers | Turning Papers | Primary Sections | Strong/Moderate Primary | Decision-grade Primary | Candidate Edges | Complete Cards | Gaps |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| metalens | True | 100.0% | 7 | 19 | 13 | 8 | 8 | 7 | 3 | 0 | 1 |
| metasurface holography | True | 100.0% | 4 | 11 | 8 | 4 | 4 | 2 | 3 | 0 | 1 |
| photonic crystal cavity | True | 100.0% | 4 | 11 | 9 | 3 | 3 | 2 | 320 | 0 | 1 |
| quantum light source | True | 100.0% | 4 | 12 | 10 | 7 | 7 | 7 | 320 | 0 | 1 |

### Per-topic Quality Gaps

- **metalens**: future candidates exist but no complete Claim Cards are promoted
- **metasurface holography**: future candidates exist but no complete Claim Cards are promoted
- **photonic crystal cavity**: future candidates exist but no complete Claim Cards are promoted
- **quantum light source**: future candidates exist but no complete Claim Cards are promoted

## Topic Dossier Rubric

- **Branch is valuable**: must have branch name, why_appeared, historical_bottleneck, enabling_condition, clickable driver_papers; empty output = cluster counts without split reason or driver papers.
- **Bottleneck is actionable**: must have constraint label, section/limitation evidence, affected branch or paper, evidence quality; empty output = generic keywords such as technical limitation without source section.
- **Key turning paper is explainable**: must have paper role, selection reason, main-path/branch/limitation evidence, access links or access_gap; empty output = paper id/title only, or no local evidence and no external link.
- **Future direction is investable**: must have complete five-question Claim Card, calibrated future evidence, bottleneck linkage, claim_scope; empty output = raw GNN edge shown as a product recommendation.
- **Uncertainty is honest**: must have linked-ref, OpenAlex, section, calibration, and access gaps are visible; empty output = confident prose hiding weak evidence coverage.

## Next Gate

P0-P8 are complete in the first engineering pass: baseline, multi-topic regression, evidence-object UI loop, Step13/Radar hard gates, access-link audit, and delta-section handoff controls now exist. A temporary-DB smoke test also verified Step5c -> Step6 -> Step13 -> Step10 runs without schema breakage on partial section data. Branch dossiers now separate evidence-backed splits from weak layout clusters, future-growth candidates are explicitly shown as calibrated candidate-generator output unless converted into complete Claim Cards, and the Topic Lens/layer interaction now explains what the selected evidence combination means. The next gate is P10: final delivery audit, GitHub sync, and post-frontfill automatic run readiness.
