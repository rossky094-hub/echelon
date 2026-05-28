# V14B Optics Goal Alignment Audit

Generated: 2026-05-28 13:29

## Project Goal

Build an explainable optics evolution graph that can show why the field grew into its current branch structure and where it may grow next, while exposing evidence quality for user-facing claims.

## Executive Verdict

- Product graph layer exists: 55,391 visual nodes, 738,663 visual edges, 5,443 clusters, 5,443 branch lineages.
- Step5b future-growth signal is numerically strong as a ranker: test AUC=0.9022, predicted_edges=1,000, cross_field=37; product confidence is calibrated separately from raw model score.
- Step5c limitation evidence is currently mostly abstract/algorithmic unless section tables are ingested: atoms=1,066, resolutions=1,743.
- Step6 fusion output is limited: directions=20, adequacy=adequate_candidate_set. This is acceptable as an honest signal, but not yet enough for strong user-facing future claims.

## Step1-Step6 Evidence Chain

| step | key output | quality status | interpretation |
|---|---:|---|---|
| Step1 library/enrich | papers=55,391, abstracts=99.9%, linked_refs=413,737/3,016,141 (13.7%) | warning | citation graph is usable but still coverage-limited against all raw references |
| Step1 field/topic | primary_field_id=30,575/55,391 (55.2%) | warning | cross-field interpretation remains partial |
| Step0 embeddings | embeddings=55,391/55,391 (100.0%) | pass | semantic layer/search/layout is well supported |
| Step2 main path | edges=277,195, main=2,771, cycles=66, cyclic_nodes=138, intra_cycle_edges=148 | pass | SCC condensation preserves ambiguous cycles instead of arbitrary deletion |
| Step3 keystone | avg_signal_reliability=1.000, critical_default_papers=0 | pass | score is discriminative only while graph feature columns remain populated |
| Step4 subgraph | nodes=5,000, edges=38,794, scope=pilot_evidence_subgraph | pilot_adequate_for_algorithmic_evidence | pilot/evidence subgraph, not complete optics graph |
| Step5a citation function | classified=38,794 | weak evidence | no full citation context, therefore use only as fusion/visual weighting |
| Step5b future growth | predicted=1,000, cross_field=37, calibrated_min/avg/max=0.944/0.944/0.944 | warning | ranking works; calibrated confidence is product evidence, not scientific certainty |
| Step5c limitations | atoms=1,066, resolutions=1,743 | weak-to-moderate | limitation quality must be visible in graph |
| Step6 fusion | directions=20, candidates=20 | adequate_candidate_set | few directions means evidence intersection is sparse, not a reason to lower thresholds |

## Limitation Evidence Quality

| quality | source | atoms | avg_weight |
|---|---|---:|---:|
| weak_abstract | abstract | 1,066 | 0.350 |

## Fusion Evidence Adequacy

- top_vgae_used: 500
- total_vgae_predictions: 1000
- cross_field_predictions: 37
- unresolved_limitations_used: 50
- evidence_path_distribution: `{"2": 20}`
- candidate_tier_distribution: `{"exploratory_weak_limitation": 20}`
- calibration_distribution: `{"labels": {"calibrated_temporal_holdout": 20}, "prediction_confidence_avg": 0.8517545731272295, "min_vgae_confidence": 0.55, "vgae_top_n": 500}`
- limitation_quality_distribution: `{"weak_abstract": 50}`

## Step5b Calibration

- calibrated_predicted_prob_min_avg_max: 0.944/0.944/0.944
- raw_predicted_prob_min_avg_max: 0.998/0.999/1.000
- prediction_confidence_avg: 0.852
- calibration_labels: `[{"label": "calibrated_temporal_holdout", "n": 1000}]`

## Future Direction Evidence Tiers

| tier | directions | avg_confidence |
|---|---:|---:|
| exploratory_weak_limitation | 20 | 0.620 |

## What Was Improved

- Step2 now exposes canonical `source_paper_id` / `target_paper_id` for time-forward main-path semantics while retaining legacy columns for compatibility.
- Step3 now records signal reliability and dampens KeystoneScore toward neutral if critical features regress to defaults.
- Step4 now records `subgraph_scope_audit`, explicitly labeling the 5,000-node subgraph as pilot/evidence and evaluating whether the cap is adequate.
- Step5a now writes method/evidence-level/weight, so title/abstract-only citation-function labels cannot masquerade as ground truth.
- Step5c now writes limitation evidence source, quality, weight, section name, and extractor method.
- Step5b now separates raw VGAE scores from calibrated product confidence using chronological validation evidence.
- Step6 now writes evidence tiers and claim scopes, making sparse/exploratory evidence an explicit product signal.
- Step10 propagates limitation and calibrated future-edge evidence into visual node/edge flags and detail JSON.

## Remaining Risk

1. Linked-reference coverage is still the largest graph-bone risk. The internal citation DAG is large enough to run, but linked_refs/raw_refs is still coverage-limited.
2. OpenAlex Field/Topic coverage is partial. Cross-field color, bridge, and future direction claims should expose uncertainty until field coverage improves.
3. Step5b now has internal calibration, but it is still based on sampled temporal holdouts. Before user-facing confidence claims, add rolling held-out-year backtests and LLM/human audit calibration.
4. Step5c is weak when based on abstracts. Section-level `paper_sections` / Sci-Bot sections are needed before limitation-driven bottleneck claims become strong.
5. Step6 evidence tiers improve transparency, but exploratory directions remain hypotheses. The next improvement should strengthen branch lineage and candidate generation with stronger external validation, not just lower thresholds.
6. Branch lineage now exposes support ratios and alternative parents, but parent-child branch causality still needs stronger validation against citation/community history and LLM/human audit samples.
7. LLM/Doubao audit is planned but not executed. The visual graph should present unaudited future/main/branch edges with uncertainty until the stratified audit is run.

## Recommendation

The current output is suitable as an evidence-aware pilot visual graph and search/recommendation substrate. It is not yet strong enough to present future directions as high-confidence scientific forecasts. The next engineering priority is section-level evidence ingestion plus calibrated future-growth/branch-lineage validation.
