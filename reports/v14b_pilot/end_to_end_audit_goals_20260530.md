# V14B End-to-End Audit Goals While Frontfill Runs

Generated: 2026-05-30 00:30 CST

## Current State

- papers: 55,391
- linked refs: 442,878 / 3,197,663 = 13.9%
- OpenAlex W coverage: 34,252 / 55,391 = 61.8%
- paper_sections: 1,241 rows / 690 papers
- primary section papers: 690
- future candidate edge rows: 1,000
- future_directions: 0
- Claim Cards: 0 complete / 0 high-confidence
- visual graph: ready, 55,391 nodes / 739,318 edges
- readiness_level: candidate_generator_only

## Audit Principle

The project goal is not to render a graph.  The goal is a research decision
system that can explain why a field evolved, which bottlenecks matter, and
which future directions are worth testing.  Therefore every waiting-time task
must improve one of three properties:

1. evidence strength,
2. claim traceability,
3. decision usefulness.

## 20 Concrete Audit Goals

### Evidence Bone

1. **Evidence Grade Propagation Audit**
   - Goal: verify every Topic Dossier branch, bottleneck, turning paper, future candidate, and Claim Card has `evidence_grade`, `claim_scope`, and uncertainty reasons.
   - Acceptance: no user-facing conclusion is emitted without evidence metadata.

2. **Linked Reference Failure Taxonomy**
   - Goal: categorize unlinked refs by DOI/arXiv/OpenAlex/S2/title-only/reference-string cause.
   - Acceptance: top 5 relink blockers are quantified, not guessed.

3. **High-Value Section Coverage Audit**
   - Goal: verify section coverage for main-path nodes, branch drivers, future endpoints, top keystone papers, limitation atoms, and the 4 benchmark topics.
   - Acceptance: a table shows coverage per evidence-critical class.

4. **Section Parser Error Audit**
   - Goal: classify failed PDF parses into no-PDF, download failure, parser warning, no target section, malformed PDF, timeout.
   - Acceptance: section frontfill improvements target the dominant failure mode.

### Bottleneck And Branch Lineage

5. **Bottleneck Lineage Page Evidence**
   - Goal: attach section name and page candidates to lineage triples where the parser has them.
   - Acceptance: `triples_with_page` moves above 0 and page gaps are explicit.

6. **Lineage Chain Completeness Audit**
   - Goal: detect incomplete chains missing constraint/failure/attempt/fix/new-constraint stages.
   - Acceptance: each future direction reports complete vs partial bottleneck lineage.

7. **Branch Split Evidence Scoring**
   - Goal: score branch split validity from parent citation support, driver papers, bottleneck shift, term shift, and section evidence.
   - Acceptance: branch labels separate true split, weak split, and layout-only cluster with reasons.

8. **Layout Cluster Demotion Check**
   - Goal: ensure layout-only clusters never appear in the UI as scientific evolutionary branches.
   - Acceptance: Topic Dossier wording uses "visual cluster" unless split evidence passes threshold.

### Future Growth And Claim Cards

9. **VGAE Calibration Readiness Audit**
   - Goal: verify whether rolling held-out-year backtest tables exist and whether calibration curves are current.
   - Acceptance: future candidates expose calibrated/not-calibrated status.

10. **Future Candidate Lifecycle Audit**
    - Goal: track each future edge from GNN candidate -> Step6 fusion -> Step13 Claim Card -> Radar eligibility.
    - Acceptance: every candidate has a lifecycle state; raw model edges stay out of Radar.

11. **Claim Card Missing-Gate Matrix**
    - Goal: aggregate which of the five hard questions are missing most often.
    - Acceptance: Step13 improvements are guided by actual missing gates.

12. **Minimum Validation Experiment Quality Check**
    - Goal: detect generic experiments and require cost, cycle, success criterion, falsification condition.
    - Acceptance: no high-confidence card has a vague experiment.

### Topic Dossier Product Value

13. **Multi-topic Benchmark Regression Expansion**
    - Goal: strengthen benchmark regression fixtures for metalens, metasurface holography, photonic crystal cavity, quantum light source.
    - Acceptance: each topic has expected branches, bottlenecks, turning-paper anchors, and failure criteria.

14. **Topic Dossier Evidence Object Audit**
    - Goal: ensure every branch/bottleneck/turning/future statement links to clickable paper/section/edge/lineage evidence.
    - Acceptance: no dead-end card in the first-screen dossier.

15. **Researcher Reading Path Audit**
    - Goal: for each topic, return starter papers, turning papers, current frontier, unresolved bottlenecks, and recommended validation path.
    - Acceptance: the output helps a researcher learn and act, not just browse.

16. **Enterprise R&D Radar Audit**
    - Goal: verify each Radar item has technical score, commercial relevance, validation cost, evidence strength, and claim scope.
    - Acceptance: Radar contains only complete Claim Cards; incomplete candidates stay in candidate pool.

### Operations, Corpus, And Release

17. **Post-Frontfill Safe Checkpoint Audit**
    - Goal: define exact thresholds for starting Step5c -> Step6 -> Step13 -> Step10 after section/OpenAlex frontfill.
    - Acceptance: downstream rerun begins only when evidence is usable or explicitly marked exploratory.

18. **Quarterly Snapshot Delta Audit**
    - Goal: prove a quarterly run can compare old vs new papers, branches, bottlenecks, and directions.
    - Acceptance: snapshot delta report names what changed this quarter.

19. **Multi-corpus Scope Audit**
    - Goal: verify each V14B step respects `--corpus-id` and does not hardwire optics.
    - Acceptance: CS/materials/optics can run independently before cross-corpus bridge graph.

20. **Release/Push Readiness Audit**
    - Goal: keep local commits, generated reports, tests, and GitHub sync state visible.
    - Acceptance: no runtime state files are committed; code/report commits are push-ready once network/auth works.

## Recommended Waiting-Time Execution Order

1. Build the coverage/error audits that do not need the frontfill to finish.
2. Strengthen multi-topic benchmark regression fixtures and evidence-object checks.
3. Prepare post-frontfill checkpoint logic and Claim Card missing-gate matrix.
4. When section/OpenAlex finishes or watchdog hands off delta queue, rerun Step5c -> Step6 -> Step13 -> visual graph -> value audit.
