# V14B Product Baseline Snapshot

- Snapshot: `2026-05-30T18:25:48Z`
- Main DB: `db/echelon_library.sqlite3`
- V14 DB: `db/v14_pilot.sqlite3`

## Coverage

- Papers: 55,391
- OpenAlex W IDs: 35,663 / 55,391 (64.4%); missing 19,728
- Invalid OpenAlex IDs: 0
- Pending enrich: 454
- Primary Field coverage: 55,359 / 55,391 (99.9%)
- References: 3,215,130; linked refs: 445,957 (13.9%)
- Section rows: 4,848; section papers: 2,767; primary evidence papers: 2,767 (5.0%)

## Derived Product Tables

- access_link_audit_items: 6,903
- bottleneck_lineage_triples: 2,920
- branch_lineages: 5,286
- direction_claim_cards: 5
- future_directions: 5
- limitation_atoms: 730
- limitation_resolutions: 1,001
- main_path_cycle_audit: 66
- main_path_edges: 277,526
- predicted_future_edges: 1,000
- section_priority_papers: 12,514
- section_priority_summary: 940
- subgraph_edges: 38,538
- subgraph_nodes: 5,000
- visual_clusters: 5,286
- visual_edges: 772,947
- visual_nodes: 55,391
- visual_search_fts: 55,391
- visual_tiles: 21,144
- complete Claim Cards: 1
- high-confidence Claim Cards: 0
- access audit: 6,903 papers, 0 gaps
- future_directions by claim_scope: {"exploratory_incomplete_card": 4, "exploratory_with_claim_card": 1}

## Metalens Baseline

- Ready: True
- Expected branch coverage: 100.0%
- Expected branches found: Imaging systems, Broadband achromatic correction, High-NA focusing performance, Tunable and multifunctional optics, Manufacturing scale-up, Computational compensation and inverse design
- Missing branches: none
- Branches: 7; driver papers: 21
- Bottlenecks: 8; evidence papers: 30
- Key turning papers: 13; with access links: 13; with primary section: 9
- Future candidate edges: 3; Radar Claim Cards: 0; complete cards: 0

### Quality Gaps
- future candidates exist but no complete Claim Cards are promoted

## Topic Dossier Rubric

- **Branch is valuable**: must have branch name, why_appeared, historical_bottleneck, enabling_condition, clickable driver_papers; empty output = cluster counts without split reason or driver papers.
- **Bottleneck is actionable**: must have constraint label, section/limitation evidence, affected branch or paper, evidence quality; empty output = generic keywords such as technical limitation without source section.
- **Key turning paper is explainable**: must have paper role, selection reason, main-path/branch/limitation evidence, access links or access_gap; empty output = paper id/title only, or no local evidence and no external link.
- **Future direction is investable**: must have complete five-question Claim Card, calibrated future evidence, bottleneck linkage, claim_scope; empty output = raw GNN edge shown as a product recommendation.
- **Uncertainty is honest**: must have linked-ref, OpenAlex, section, calibration, and access gaps are visible; empty output = confident prose hiding weak evidence coverage.

## Next Gate

P0-P8 are complete in the first engineering pass: baseline, Metalens regression, evidence-object UI loop, Step13/Radar hard gates, access-link audit, and delta-section handoff controls now exist. A temporary-DB smoke test also verified Step5c -> Step6 -> Step13 -> Step10 runs without schema breakage on partial section data. Branch dossiers now separate evidence-backed splits from weak layout clusters, future-growth candidates are explicitly shown as calibrated candidate-generator output unless converted into complete Claim Cards, and the Topic Lens/layer interaction now explains what the selected evidence combination means. The next gate is P10: final delivery audit, GitHub sync, and post-frontfill automatic run readiness.
