# V14B Product Baseline Snapshot

- Snapshot: `2026-05-29T13:27:08Z`
- Main DB: `db/echelon_library.sqlite3`
- V14 DB: `db/v14_pilot.sqlite3`

## Coverage

- Papers: 55,391
- OpenAlex W IDs: 33,618 / 55,391 (60.7%); missing 21,773
- Invalid OpenAlex IDs: 0
- Pending enrich: 543
- Primary Field coverage: 55,342 / 55,391 (99.9%)
- References: 3,187,558; linked refs: 440,978 (13.8%)
- Section rows: 1,241; section papers: 690; primary evidence papers: 690 (1.2%)

## Derived Product Tables

- bottleneck_lineage_triples: 2,920
- branch_lineages: 5,426
- direction_claim_cards: 0
- future_directions: 0
- limitation_atoms: 730
- limitation_resolutions: 1,001
- main_path_cycle_audit: 66
- main_path_edges: 277,526
- predicted_future_edges: 1,000
- section_priority_papers: 12,600
- section_priority_summary: 18
- subgraph_edges: 38,538
- subgraph_nodes: 5,000
- visual_clusters: 5,426
- visual_edges: 739,318
- visual_nodes: 55,391
- visual_search_fts: 55,391
- visual_tiles: 21,704
- complete Claim Cards: 0
- high-confidence Claim Cards: 0

## Metalens Baseline

- Ready: True
- Expected branch coverage: 100.0%
- Expected branches found: Imaging systems, Broadband achromatic correction, High-NA focusing performance, Tunable and multifunctional optics, Manufacturing scale-up, Computational compensation and inverse design
- Missing branches: none
- Branches: 7; driver papers: 21
- Bottlenecks: 4; evidence papers: 6
- Key turning papers: 80; with access links: 80; with primary section: 1
- Future edges: 10; Radar Claim Cards: 0; complete cards: 0

### Quality Gaps
- future candidates exist but no complete Claim Cards are promoted

## Topic Dossier Rubric

- **Branch is valuable**: must have branch name, why_appeared, historical_bottleneck, enabling_condition, clickable driver_papers; empty output = cluster counts without split reason or driver papers.
- **Bottleneck is actionable**: must have constraint label, section/limitation evidence, affected branch or paper, evidence quality; empty output = generic keywords such as technical limitation without source section.
- **Key turning paper is explainable**: must have paper role, selection reason, main-path/branch/limitation evidence, access links or access_gap; empty output = paper id/title only, or no local evidence and no external link.
- **Future direction is investable**: must have complete five-question Claim Card, calibrated future evidence, bottleneck linkage, claim_scope; empty output = raw GNN edge shown as a product recommendation.
- **Uncertainty is honest**: must have linked-ref, OpenAlex, section, calibration, and access gaps are visible; empty output = confident prose hiding weak evidence coverage.

## Next Gate

Phase 0 is complete only when this snapshot and the task list are committed.  Phase 1 starts by turning the Metalens baseline into a regression fixture.
