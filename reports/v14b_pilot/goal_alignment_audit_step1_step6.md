# V14B Goal Alignment Audit

Generated: 2026-05-31 04:03

## Project Goal

Build an explainable **all** evolution graph that can show why the field grew into its current branch structure and where it may grow next, while exposing evidence quality for user-facing claims.

## Executive Verdict

- Product graph layer exists: 55,391 visual nodes, 772,947 visual edges, 5,286 clusters, 5,286 branch lineages.
- Step5b future candidate generator is numerically strong as a ranker: test AUC=0.8371, candidate_edge_rows=1,000, cross_field=60; product evidence score is calibrated separately from raw model score.
- Step5c limitation evidence is currently mostly abstract/algorithmic unless section tables are ingested: atoms=730, resolutions=1,001.
- Section evidence inventory: table_present=True, rows=5,168, primary-section papers=2,942.
- Step6 fusion output is limited: directions=5, audit_n_directions=5, adequacy=limited_but_usable_with_uncertainty, consistent=True. This is acceptable as an honest signal only when audit/product tables agree.
- Step13 first-principles bottleneck lineage: principles=6, atoms_covered=730, high_risk_principles=0.
- Step13 claim cards: total=5, five-question-complete=1, high-confidence-eligible=0, lineage_triples=2,920.

## Step1-Step6 Evidence Chain

| step | key output | quality status | interpretation |
|---|---:|---|---|
| Step1 library/enrich | papers=55,391, abstracts=99.9%, linked_refs=445,957/3,215,130 (13.9%) | warning | citation graph is usable but still coverage-limited against all raw references |
| Step1 field/topic | primary_field_id=55,359/55,391 (99.9%) | pass | cross-field interpretation remains partial |
| Step0 embeddings | embeddings=55,391/55,391 (100.0%) | pass | semantic layer/search/layout is well supported |
| Step2 main path | edges=277,526, main=2,775, cycles=66, cyclic_nodes=138, intra_cycle_edges=148 | pass | SCC condensation preserves ambiguous cycles instead of arbitrary deletion |
| Step3 keystone | avg_signal_reliability=1.000, critical_default_papers=0 | pass | score is discriminative only while graph feature columns remain populated |
| Step4 subgraph | nodes=5,000, edges=38,538, scope=bounded_evidence_subgraph | bounded_evidence_subgraph_adequate_for_extraction | bounded evidence subgraph for extraction support, not complete all graph |
| Step5a citation function | classified=38,538 | weak evidence | no full citation context, therefore use only as fusion/visual weighting |
| Step5b future candidates | candidate_edges=1,000, cross_field=60, calibrated_score_min/avg/max=0.995/0.995/0.995 | warning | ranking works; calibrated score is product evidence, not scientific certainty |
| Step5c limitations | atoms=730, resolutions=1,001 | weak-to-moderate | limitation quality must be visible in graph |
| Step6 fusion | directions=5, candidates=5 | limited_but_usable_with_uncertainty | few directions means evidence intersection is sparse, not a reason to lower thresholds |
| Step13 claim cards | cards=5, complete=1, high_conf=0, lineage_triples=2,920 | risk | missing 5-question cards cannot be promoted into high-confidence directions |

## Limitation Evidence Quality

| quality | source | atoms | avg_weight |
|---|---|---:|---:|
| section_level | structured_sections | 730 | 0.750 |

## Fusion Evidence Adequacy

- top_candidate_edges_used: 500
- total_future_candidate_edges: 1000
- cross_field_candidate_edges: 60
- unresolved_limitations_used: 50
- evidence_path_distribution: `{"2": 5}`
- candidate_tier_distribution: `{"exploratory": 5}`
- calibration_distribution: `{"labels": {"calibrated_temporal_holdout": 5}, "candidate_ranking_score_avg": 0.8329225875546147, "min_candidate_score_threshold": 0.55, "candidate_edges_used": 500}`
- limitation_quality_distribution: `{"section_level": 50}`

## Step5b Calibration

- calibrated_candidate_score_min_avg_max: 0.995/0.995/0.995
- raw_candidate_score_min_avg_max: 0.985/0.991/1.000
- candidate_ranking_score_avg: 0.833
- calibration_labels: `[{"label": "calibrated_temporal_holdout", "n": 1000}]`
- rolling_backtest_avg_raw_auc: 0.8367
- rolling_backtest_avg_calibrated_auc: 0.8367
- rolling_backtest_years: `[{"year": 2024, "positives": 1721, "negatives": 1721, "raw_auc": 0.8156535073962444, "calibrated_auc": 0.8156535073962444, "raw_avg": 0.5951502919197083, "calibrated_avg": 0.42553314566612244}, {"year": 2025, "positives": 3222, "negatives": 3222, "raw_auc": 0.8453453349315942, "calibrated_auc": 0.8453408557168843, "raw_avg": 0.6346316337585449, "calibrated_avg": 0.5269697308540344}, {"year": 2026, "positives": 2255, "negatives": 2255, "raw_auc": 0.8491778309841151, "calibrated_auc": 0.8491778309841151, "raw_avg": 0.6276218891143799, "calibrated_avg": 0.5213567614555359}]`

## Future Direction Evidence Tiers

| tier | directions | avg_evidence_score |
|---|---:|---:|
| exploratory | 5 | 0.810 |

## Hard Acceptance Gates

- linked_refs_ratio >= 30%: current=0.139 -> risk
- top-keystone section evidence coverage >= 70%: current=2.942 (2942/1000) -> pass
- every direction has 5-question claim card: current=1/5 -> risk
- future calibration report present: current=True -> pass
- fusion audit matches future_directions table: current=True -> pass
- claim_scope present for all directions: distribution=`[{"claim_scope": "exploratory_incomplete_card", "n": 4}, {"claim_scope": "exploratory_with_claim_card", "n": 1}]`

## What Was Improved

- Step2 now exposes canonical `source_paper_id` / `target_paper_id` for time-forward main-path semantics while retaining legacy columns for compatibility.
- Step3 now records signal reliability and dampens KeystoneScore toward neutral if critical features regress to defaults.
- Step4 now records `subgraph_scope_audit`, explicitly labeling the 5,000-node bounded evidence subgraph and evaluating whether the cap is adequate for extraction support.
- Step5a now writes method/evidence-level/weight, so title/abstract-only citation-function labels cannot masquerade as ground truth.
- Step5c now writes limitation evidence source, quality, weight, section name, and extractor method.
- Step5b now separates raw VGAE scores from calibrated product evidence scores using chronological validation evidence.
- Step6 now writes evidence tiers and claim scopes, making sparse/exploratory evidence an explicit product signal.
- Step10 propagates limitation and calibrated future-edge evidence into visual node/edge flags and detail JSON.
- Step13 reconnects first-principles + bottleneck-history analysis into current V14B evidence chain (non-LLM deterministic baseline).

## Remaining Risk

1. Linked-reference coverage is still the largest graph-bone risk. The internal citation DAG is large enough to run, but linked_refs/raw_refs is still coverage-limited.
2. OpenAlex Field/Topic coverage is partial. Cross-field color, bridge, and future direction claims should expose uncertainty until field coverage improves.
3. Step5b now includes calibration + rolling held-out-year checks, but user-facing candidate scores still need external LLM/human stratified audit calibration.
4. Step5c is weak when based on abstracts. Section-level `paper_sections` / Sci-Bot sections are needed before limitation-driven bottleneck claims become strong.
5. Step6 evidence tiers improve transparency, but exploratory directions remain hypotheses. The next improvement should strengthen branch lineage and candidate generation with stronger external validation, not just lower thresholds.
6. Branch lineage now exposes support ratios and alternative parents, but parent-child branch causality still needs stronger validation against citation/community history and LLM/human audit samples.
7. LLM/Doubao audit is planned but not executed. The visual graph should present unaudited future/main/branch edges with uncertainty until the stratified audit is run.
8. First-principles lineage is now connected, but still constrained by section evidence coverage and linked-reference coverage; unresolved-high-risk principles should remain hypothesis-level until section-level evidence expands.

## Recommendation

The current output is suitable as an evidence-aware visual graph and search/recommendation substrate. It is not yet strong enough to present future directions as high-confidence scientific directions. The next engineering priority is section-level evidence ingestion plus calibrated future-candidate/branch-lineage validation.
