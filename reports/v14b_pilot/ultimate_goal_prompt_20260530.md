# Echelon V14B Ultimate Goal Prompt

Generated: 2026-05-30 CST

## Goal Prompt

You are Codex working in `/Users/r/Documents/New project/echelon/echelon-v14b`.
Your long-running goal is to turn the updated V14B workflow into an
evidence-constrained research decision engine, not a graph demo and not an old
enrich/pilot rerun.

The end product must help researchers and R&D teams answer three questions:

1. Why did this scientific direction evolve into its current branch structure?
2. Which bottlenecks are real, historically persistent, and still unresolved?
3. Which future directions are worth validating in the next 6-18 months, with
   evidence, uncertainty, cost, and falsifiable next experiments?

## Current Audited Baseline

- Corpus: optics V14B, 55,391 papers.
- Citation bone: 443,651 linked refs / 3,202,790 refs, about 13.8%; usable but
  not decision-grade.
- OpenAlex W coverage: 34,663 / 55,391, about 62.6%; field/topic explanation
  must carry uncertainty until stronger.
- Primary section evidence: 738 papers; still far below the high-value evidence
  budget.
- Visual graph data layer exists: 55,391 visual nodes, 772,947 visual edges,
  5,286 visual clusters, 21,144 visual tiles.
- Future growth: 1,000 calibrated VGAE/GNN candidates exist, but these are only
  candidate-generator outputs.
- Direction layer: 5 future directions, 5 Claim Cards, 1 complete Claim Card,
  0 high-confidence Claim Cards.
- Current readiness: actionable/exploratory, not high-confidence.
- Current blockers: evidence bone, section evidence, OpenAlex/topic coverage,
  and multi-topic regression.

These numbers are not cosmetic. They define what the system is allowed to
claim. Until gates pass, conclusions must be labeled exploratory or weak.

## Updated Workflow To Respect

Only use the current V14B workflow:

1. Frontfill evidence: section evidence top12000/delta queue and conservative
   OpenAlex backfill.
2. `id-repair` and deterministic reference relinking.
3. `graph-features` and `embeddings`.
4. `quality-audit`.
5. `reset-pilot`.
6. Step2 Main Path using SCC condensation DAG, not arbitrary edge deletion.
7. Step3 KeystoneScore, guarded by feature-quality checks.
8. Step4 subgraph/full-graph evidence selection, with pilot scope explicitly
   labeled.
9. Step5a citation function as weak evidence unless full citation context exists.
10. Step5b calibrated VGAE/GNN future candidate generation with rolling
    held-out-year backtest.
11. Step5c limitation/resolution extraction from section-level evidence first;
    abstract-only evidence is fallback and must be labeled weak.
12. Step6 tiered fusion of main path, citation function, limitations,
    calibration, branch lineage, and evidence strength.
13. Step13 first-principles and bottleneck-history engine, before user-facing
    Radar: generate Bottleneck Lineage triples and five-question Claim Cards.
14. Step7 mutation, Step8 layout, Step9 report.
15. Step10 visual graph builder, Topic Lens API, Dossier, Evidence Map, and
    Radar.
16. Step12 goal/value audit.
17. Optional Step11 stratified LLM audit for semantic sampling, not primary
    truth.
18. Quarterly and multi-corpus runs with `corpus_id`, snapshots, and deltas.

Do not restore old arXiv gap-first monitoring, old mixed-ID enrich semantics,
old raw-edge Radar behavior, or old layout-cluster-as-science wording.

## Non-Negotiable Product Contract

The product is a three-layer workbench:

1. Topic Dossier is the default first screen.
   - For a topic such as Metalens, it must answer: real branches, branch split
     reasons, historical bottlenecks, key turning papers, unresolved constraints,
     current evidence gaps, future validation candidates, and recommended reading.
   - It must not start with "50 papers / 10 edges" as the main value.

2. Evolution Evidence Map is for verification, not decoration.
   - Main layer shows historical evolution backbone.
   - Co-cite/citation/semantic layers explain thematic neighborhoods and
     evidence support.
   - Bottleneck layer shows where constraints recur.
   - Future layer shows candidate growth only after calibration and fusion labels.
   - Uncertainty layer shows weak linked refs, weak section evidence, weak
     OpenAlex/topic coverage, or low calibration support.
   - Layer combinations must explain what their fusion means, not merely toggle
     visibility.

3. Claim Card / R&D Radar is the decision layer.
   - Radar shows directions, not raw edge IDs.
   - A direction can enter Radar only when Step6 and Step13 produce a complete
     Claim Card.
   - Raw VGAE/GNN edges remain in candidate pool until fused and carded.
   - High confidence requires complete five-question card, calibrated future
     evidence, strong section evidence, and triangulated evidence tier.

## Required Claim Card Template

Every direction must answer all five questions:

1. Root constraint: physical / engineering / data / cost.
2. What was tried in the past 10 years, and why did those attempts fail?
3. What new enabling condition makes this direction different now?
4. Which bottleneck remains unresolved, and what is the evidence strength?
5. What is the minimum validation experiment, including cost, cycle, success
   criterion, and falsification condition?

If any answer is missing or generic, the item stays out of Radar and is labeled
candidate-pool-only or exploratory.

## Algorithm Contracts

- Evidence Bone: every user-facing conclusion must carry `evidence_grade`,
  `claim_scope`, `evidence_objects`, and `uncertainty_reasons`.
- Bottleneck Lineage Graph: extract typed chains from sections:
  constraint -> failure mechanism -> attempt path -> local fix -> new constraint,
  with paper, section, year, and page candidate when available.
- Branch Lineage Validity: distinguish `evidence_backed_split`,
  `weak_split_candidate`, and `layout_cluster_only`; only the first may be
  narrated as scientific branch evolution.
- Future Growth Calibration: VGAE/GNN is only a candidate generator; each
  candidate must have calibration label, rolling backtest evidence, lifecycle
  state, and downstream fusion/card status.
- Step6 Fusion: direction strength comes from converging evidence across
  calibrated future candidates, unresolved bottlenecks, branch lineage,
  main-path/keystone/citation signals, and section evidence.
- Step13: first-principles/history is not a report appendix. It is the gate
  that determines whether a direction becomes actionable.
- Topic regression: do not tune for Metalens only. Required gold topics include
  metalens, metasurface holography, photonic crystal cavity, and quantum light
  source.
- Quarterly/multi-corpus: optics, CS, and materials must be independently
  scoped with `corpus_id`; cross-corpus bridges come after independent graphs.

## Acceptance Gates

The system is not considered successful until these gates pass or are explicitly
scoped as exploratory:

- Linked references at least 30% for decision-grade citation evolution claims.
- High-value primary section evidence at least 70% for main path nodes, branch
  drivers, future endpoints, top keystone papers, limitation/resolution papers,
  and gold-topic papers.
- OpenAlex W/topic/field coverage high enough for cross-field explanations, or
  all cross-field claims carry uncertainty.
- Every Radar item has a complete Claim Card.
- Future candidates have rolling held-out-year calibration reports.
- Multi-topic regression passes without hand-tuned prose.
- Topic Dossier has clickable evidence for branches, bottlenecks, turning
  papers, future candidates, and gaps.
- Access links exist where possible through arXiv, DOI, Semantic Scholar, and
  OpenAlex; missing links are explicit access gaps.
- Quarterly snapshots show what changed this quarter in papers, branches,
  bottlenecks, directions, and uncertainty.

## Engineering Rules

- Read the code and audit reports before editing.
- Prefer repairs that improve the scientific/product objective, not shortcuts
  that merely silence errors.
- Do not lower thresholds blindly, promote raw model edges, or hide weak
  evidence.
- Do not delete unrelated files or system applications to recover space.
- Keep section parsing temporary-PDF based unless explicitly asked otherwise.
- Control memory and concurrency: section/OpenAlex should remain conservative
  while disk is tight.
- Keep code changes minimal, tested, and reviewable; add tests when behavior
  changes.
- Keep runtime state out of commits unless intentionally part of a report.

## Autonomous Work Loop

On every continuation:

1. Check current running processes, disk/memory, logs, and DB metrics.
2. Run or inspect value/readiness/evidence/topic audits.
3. Identify the highest-leverage gap blocking decision-grade output.
4. Fix the algorithm/schema/API/UI path end to end.
5. Rerun the smallest meaningful validation, then the relevant audit.
6. Report what changed, what improved, what still blocks the ultimate goal.

The final delivery is not "all scripts ran." The final delivery is a system that
can produce evidence-backed, falsifiable, interactive scientific and R&D
decision dossiers from a growing multi-corpus literature graph.

