# V14B 100-Hour Value Delivery Plan

This plan is based on the first 50-hour engineering pass and the current full-system audit. It is not a crawler schedule. It is a value-delivery plan: what must be solved so Echelon becomes a research decision system rather than a graph demo.

## Current Audit Diagnosis

The system has a usable visual graph shell, but the value engine is not closed yet.

- The graph exists: `55,391` papers, `739,318` visual edges, `5,426` branch lineages.
- The citation bone is still thin: linked refs are about `13.8%`, below the `30%` minimum target.
- Section evidence is still too sparse: primary section evidence covers about `690` papers.
- Future candidate generation exists: `1,000` future candidate edges.
- Decision output is not ready: live `future_directions=0`, live `Claim Cards=0`.
- Therefore the current state is `candidate_generator_only`, not `decision_grade_available`.

The key insight is that the project does not need more decorative graph features. It needs the evidence chain to close:

`paper sections -> bottleneck lineage -> calibrated future candidates -> fusion -> five-question Claim Cards -> Topic Dossier/Radar`.

## Strategic Objective

In 100 hours, the goal is to make the system reliably answer:

1. What is this topic really about?
2. How did it split into branches?
3. What bottlenecks caused those splits?
4. Which bottlenecks remain unresolved?
5. Which future directions are worth testing, and why?
6. What evidence is strong, weak, missing, or only model-generated?

The final output should not be “50 papers and 10 edges”. It should be a decision dossier with clickable evidence.

## Workstream A: Evidence Bone And Data Trust

### Problem

The project cannot make strong evolution claims if the internal citation graph and section evidence are weak.

### 100-Hour Goal

Raise the trust floor enough that every user-facing claim carries a correct evidence grade.

### Tasks

1. Continue section top12000 and delta section ingest.
2. Prioritize section evidence for:
   - main path papers
   - future edge endpoints
   - branch split drivers
   - top keystone papers
   - benchmark-topic regression fixtures such as Metalens, plus arbitrary-topic readiness samples
3. Continue OpenAlex backfill conservatively.
4. Re-run provider ID repair and reference relinking only after identifier coverage improves.
5. Add evidence-grade labels everywhere:
   - section-backed
   - abstract-only
   - metadata-only
   - model-only
   - insufficient evidence

### Acceptance Gates

- Decision-critical primary section coverage grows materially.
- Access gaps are explicit.
- Linked refs improvement is measured, not assumed.
- Low-coverage graph areas are visibly uncertain.

## Workstream B: Bottleneck Lineage Graph

### Problem

The original first-principles report can still become generic unless it is anchored in real section evidence.

### 100-Hour Goal

Make bottleneck history the core reasoning engine.

### Tasks

1. Extract typed triples from `limitation/discussion/conclusion/future_work/results/error_analysis/ablation/method/experiments`:
   - constraint
   - failure mechanism
   - attempted path
   - partial fix
   - new constraint
2. Attach each triple to:
   - paper ID
   - section name
   - evidence text
   - page number if available
   - confidence/evidence quality
3. Group triples into bottleneck lineages by branch and time.
4. Mark whether a bottleneck is:
   - unresolved
   - partially resolved
   - shifted into a new constraint
   - only weakly evidenced

### Acceptance Gates

- Metalens bottlenecks are not generic keywords like `technical limitation`.
- The system can explain “why this bottleneck exists historically”.
- Every bottleneck shown in Topic Lens links to papers/sections.

## Workstream C: Branch Lineage Validity

### Problem

A branch is not valuable if it is merely a layout cluster. It must explain why a scientific direction split.

### 100-Hour Goal

Turn branches into evidence-backed evolution claims.

### Tasks

1. Upgrade branch lineage classification:
   - evidence-backed split
   - weak split candidate
   - layout cluster only
2. Add branch split reasons based on:
   - time-forward citation flow
   - co-citation community shift
   - semantic drift
   - bottleneck lineage shift
   - driver papers
3. For each topic branch, show:
   - parent branch
   - split year
   - driver papers
   - split evidence
   - constraint shift
   - uncertainty
4. Do not narrate layout-only clusters as real scientific branches.

### Acceptance Gates

- Topic Dossier uses only evidence-backed or explicitly weak-labeled branches.
- Metalens branches map to meaningful categories: imaging, achromatic, high NA, tunable/multifunctional, manufacturing, computational compensation.

## Workstream D: Future Growth Calibration

### Problem

GNN/VGAE can generate candidate edges, but it cannot be treated as a conclusion generator.

### 100-Hour Goal

Make future growth a calibrated candidate-score product with clear limits.

### Tasks

1. Keep Step5b output as candidate generator.
2. Ensure every future candidate shows:
   - raw model score
   - calibrated candidate score
   - calibration method
   - rolling held-out-year backtest result
   - evidence scope
   - whether it entered Step6/Step13
3. Re-run Step5b only if needed after graph/section improvements.
4. Add a promotion path:
   - candidate edge
   - fused direction
   - incomplete Claim Card
   - complete exploratory Claim Card
   - high-confidence Claim Card

### Acceptance Gates

- Radar never shows raw future edges as investable directions.
- Future candidates are useful as “where to inspect next”.
- Claim Cards explain why a candidate is or is not actionable.

## Workstream E: Claim Card Quality Engine

### Problem

Without a hard quality gate, the system risks producing plausible but low-value strategy prose.

### 100-Hour Goal

Make every direction pass five hard questions before entering Radar.

### Claim Card Must Include

1. Root constraint: physics, engineering, data, cost, or manufacturing.
2. Historical attempts over the last 10 years and why they failed.
3. New enabling condition that changes the prior failure logic.
4. Remaining bottleneck and evidence strength.
5. Minimal validation experiment: cost, cycle, success criterion.

### Tasks

1. Re-run Step5c -> Step6 -> Step13 after section evidence improves.
2. Generate Claim Cards from structured evidence only.
3. Push incomplete cards into candidate pool, not Radar.
4. Add missing-gate diagnostics to every candidate.

### Acceptance Gates

- Radar has no raw IDs as primary display.
- Every Radar card is human-readable and evidence-linked.
- Missing evidence is a feature, not hidden.

## Workstream F: Topic Dossier Product Value

### Problem

The user experience must answer the research question first, not display the graph first.

### 100-Hour Goal

Make Topic Lens the primary product surface.

### Tasks

1. For a topic such as Metalens, first screen must show:
   - topic stage
   - real branches
   - branch split reasons
   - key turning papers
   - unresolved bottlenecks
   - solved vs open constraints
   - candidate future directions
   - recommended reading
2. Every item must be clickable into:
   - paper card
   - section evidence
   - limitation atom
   - branch lineage
   - future candidate
   - Claim Card
3. Add explicit explanations for layer combinations:
   - Main
   - Main + Co-cite
   - Main + Bottleneck
   - Future + Bottleneck
   - Semantic + Cite
   - Fusion value

### Acceptance Gates

- A researcher can understand a topic without manually searching again.
- An R&D lead can see what is actionable vs exploratory.
- UI does not bury weak evidence under impressive visuals.

## Workstream G: Regression Topics Beyond Metalens

### Problem

If the system only works for Metalens, it is a demo, not a general engine.

### 100-Hour Goal

Build topic regression across multiple optics directions.

### Topics

1. Metalens
2. Metasurface holography
3. Photonic crystal cavity
4. Quantum light source

### Tasks

1. Define benchmark expectations for each topic under the regression-fixture contract.
2. Run Topic Lens regression.
3. Classify failures:
   - retrieval failure
   - branch failure
   - bottleneck failure
   - future growth failure
   - Claim Card failure
4. Add reports and tests.

### Acceptance Gates

- The system improves across topic classes, not just one hand-picked example.

## Workstream H: Quarterly And Multi-Corpus Productization

### Problem

The project must support quarterly updates and future corpora such as CS/materials.

### 100-Hour Goal

Ensure the architecture is not optics-hardcoded.

### Tasks

1. Audit every step for `--corpus-id` support.
2. Verify corpus registry:
   - optics
   - cs
   - materials
3. Add snapshot comparison:
   - new papers
   - changed branches
   - new bottlenecks
   - changed future directions
4. Add cross-corpus bridge placeholder:
   - same bottleneck across corpora
   - shared methods
   - transferable enablers

### Acceptance Gates

- Quarterly run can explain how new papers changed the map.
- CS/materials can be added without rewriting V14B logic.

## 100-Hour Sequence

### 0-12 Hours

- Add and run Direction Readiness Audit.
- Keep section/OpenAlex stable.
- Produce blocker report.
- Ensure Radar remains empty when only raw candidates exist.

### 12-24 Hours

- Improve section evidence queue and delta handoff.
- Audit decision-critical local evidence.
- Expand access/evidence gap reporting.

### 24-36 Hours

- Continue OpenAlex/backfill.
- Audit relink readiness.
- Re-run ID/reference repair if justified.

### 36-48 Hours

- Re-run Step5c/Step6/Step13 after evidence improves.
- Track whether directions/Claim Cards materialize.

### 48-60 Hours

- Rebuild Step7-Step10 visual graph.
- Verify Topic Lens and Radar.

### 60-72 Hours

- Run Metalens deep regression.
- Fix topic-specific value gaps.

### 72-84 Hours

- Add 3 more topic regressions.
- Generalize failures into algorithm fixes.

### 84-96 Hours

- Audit quarterly/multi-corpus readiness.
- Fix optics-hardcoded assumptions.

### 96-100 Hours

- Final product audit.
- GitHub sync.
- Remaining risk report.

## Definition Of Done

The 100 hours are successful if the system can honestly produce:

- evidence-backed topic dossier
- branch lineage with uncertainty
- bottleneck history with section evidence
- calibrated future candidate pool
- Claim Cards when evidence is sufficient
- clear explanation when evidence is insufficient

The project is not successful if it merely shows a beautiful graph.
