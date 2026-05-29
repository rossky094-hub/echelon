# V14B 100-Hour Product Execution Plan

Start: `2026-05-29 22:06 CST`

Mission: turn the optics graph from a visual paper map into a decision-grade research engine. The product is successful only when a topic query can produce evidence-backed branch lineage, bottleneck history, calibrated future candidates, and actionable Claim Cards.

## Starting Audit

- papers: `55,391`
- linked refs: `442,304 / 3,194,013` = `13.8%`
- OpenAlex W IDs: `33,821 / 55,391` = `61.1%`
- primary field coverage: `55,342 / 55,391` = `99.9%`
- section evidence: `1,241` rows / `690` papers
- primary section evidence: `690` papers
- predicted future edges: `1,000`
- live future directions: `0`
- live Claim Cards: `0`
- visual graph: `55,391` nodes / `739,318` edges / `5,426` branch lineages

## Success Gates

- linked refs: toward `>=30%`; if still below, all graph claims carry uncertainty.
- section-level evidence: top decision-critical papers `>=70%`.
- future candidates: calibrated and labeled as candidate-generator output unless fused into Claim Cards.
- Claim Cards: every Radar item must answer all five hard questions.
- Topic Lens: every branch, bottleneck, turning paper, and future direction must be clickable to paper/evidence.
- final audit: remaining risk must be explicit, not hidden behind UI polish.

## 0-12 Hours: Stabilize Evidence Frontfill And Direction Readiness

1. Keep section top12000 and OpenAlex running at conservative concurrency.
2. Add Direction Readiness Audit for Step5b -> Step5c -> Step6 -> Step13 blockers.
3. Track why `future_directions=0` while predicted edges exist.
4. Make the dashboard/report say whether the system has investable Claim Cards or only candidate edges.
5. Confirm watchdog will auto-start delta section ingest after top12000 if primary evidence remains below target.

Deliverables:

- `reports/v14b_pilot/direction_readiness_audit.md`
- `make direction-readiness-audit`
- tests for readiness scoring and blocker classification

## 12-24 Hours: Section Evidence Quality Lift

1. Monitor top12000 completion and watchdog stalling.
2. Rebuild delta queue from main path, future endpoints, branch drivers, top keystone, and Metalens gold topic.
3. Run delta section ingest if primary section evidence remains weak.
4. Audit local evidence coverage for key turning papers and branch drivers.
5. Keep PDF temp-only; do not persist full PDF cache.

Gate:

- primary decision-critical evidence grows, or the audit explains why a paper needs external access.

## 24-36 Hours: OpenAlex And Relink Completion Pass

1. Continue OpenAlex conservative backfill.
2. If OpenAlex stalls, classify failures by DOI/title/network/429.
3. Run local field/topic fallback and provider ID consistency audit.
4. Re-run reference relinking only if it increases linked refs without ID pollution.

Gate:

- no S2 IDs in `openalex_id`; OpenAlex gap is explicit and uncertainty-visible.

## 36-48 Hours: Re-run Evidence Chain

1. Run Step5c limitation with section-level evidence.
2. Run Step6 fusion.
3. Run Step13 Claim Card generator.
4. Run Direction Readiness Audit after each step.

Gate:

- future_directions materialize only when evidence exists.
- incomplete cards stay out of Radar.

## 48-60 Hours: Visual Product Rebuild

1. Run Step7 mutation.
2. Run Step8 layout.
3. Run Step9 report.
4. Run Step10 visual graph.
5. Validate Topic Lens and Radar on Metalens.

Gate:

- branch lineage explains parent/split/driver/constraint shift.
- Future layer shows calibrated candidates, not unsupported conclusions.

## 60-72 Hours: Metalens Gold Topic Deep Regression

1. Validate expected branches: imaging, broadband achromatic, high NA, tunable/multifunctional, manufacturing scale-up, computational compensation.
2. Each branch must have driver papers and bottleneck/enabler evidence.
3. Key turning papers must have access links and local/section evidence status.
4. Claim Cards must show missing gates if not actionable.

Gate:

- Metalens output is useful to a researcher or R&D lead without manual re-search.

## 72-84 Hours: Generalize Beyond Metalens

1. Pick 3 additional optics topics: metasurface holography, photonic crystal cavity, quantum light source.
2. Run the same Topic Dossier regression.
3. Identify whether failures are topic-search, branch-lineage, section-evidence, or fusion/Claim Card failures.
4. Add regression fixtures for repeated checking.

Gate:

- Topic Lens value is not overfit to Metalens.

## 84-96 Hours: Quarterly / Multi-Corpus Readiness

1. Verify corpus registry and quarterly run commands.
2. Ensure optics/cs/materials corpus configs have isolated corpus IDs.
3. Confirm steps accept `--corpus-id` or report a blocker.
4. Add snapshot delta report expectations.

Gate:

- quarterly updates can compare how new papers changed branches, bottlenecks, and directions.

## 96-100 Hours: Final Audit And Delivery

1. Re-run product baseline, topic regression, access audit, direction readiness audit.
2. Summarize completed items, blockers, and remaining risk.
3. Push GitHub.
4. Keep heartbeat monitoring section/OpenAlex and downstream chain.

Final report must answer:

- What can the system claim today?
- What is still only exploratory?
- Which evidence gaps block high-confidence directions?
- What exact next run will close each gap?
