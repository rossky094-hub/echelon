# Quantum Light Source Topic Regression

- Audit: `2026-05-31T03:28:18Z`
- Topic: `quantum light source`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 4 | 5 | fail |
| key turning papers | 10 | 4 | pass |
| turning papers with access links | 10 | 3 | pass |
| turning papers with primary sections | 7 | 2 | pass |
| turning papers with strong/moderate section provenance | 7 | 2 | pass |
| turning papers with decision-grade section evidence | 7 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 5 | 1 | fail |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| Single-photon emitters | 3 | True | True | pass |
| Entangled photon-pair sources | 3 | True | True | pass |
| Integrated quantum photonics | 3 | True | True | pass |
| Deterministic coupling and collection | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| brightness | True | True | 5 | pass |
| indistinguishability | False | True | 5 | fail |
| collection efficiency | True | True | 5 | pass |
| scalability | True | True | 3 | pass |
| integration | True | True | 5 | pass |

## Interpretation

- Key turning papers: 10 total, 10 with access links, 7 with primary local sections, 7 with strong/moderate parser provenance, 7 with decision-grade current-contract evidence.
- Future candidates: 320 graph candidates, 0 Radar cards, 0 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: full=0, partial=5, clickable=5/5. Only full typed chains satisfy the lineage gate.
- Reading path contracts: 5/5 steps are auditable; modes=bottleneck, branch_driver, future_candidate, starter, turning.
- Benchmark topics are regression fixtures, not a product allowlist or an LLM cost-control boundary.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- future candidates exist but no complete Claim Cards are promoted

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| missing_bottleneck_section_evidence | indistinguishability | 100 | 5 | Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 12 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card; frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence. missing five-question gates: historical attempts and failure evidence=4, unresolved bottleneck evidence=3; missing high-confidence gates: complete five-question Claim Card=4, current parser-contract decision-grade section evidence=3, strong or moderate section parser provenance=3, strong section-level evidence=3, triangulated Step6 fusion evidence=4; incomplete direction ids: 83,84,85,86; complete Claim Cards found only as weak topic context: 82 |
