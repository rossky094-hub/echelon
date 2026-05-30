# Photonic Crystal Cavity Topic Regression

- Audit: `2026-05-30T22:16:15Z`
- Topic: `photonic crystal cavity`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 4 | 5 | fail |
| key turning papers | 9 | 4 | pass |
| turning papers with access links | 9 | 3 | pass |
| turning papers with primary sections | 3 | 2 | pass |
| turning papers with strong/moderate section provenance | 3 | 2 | pass |
| turning papers with decision-grade section evidence | 2 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 5 | 1 | pass |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| High-Q nanocavities | 3 | True | True | pass |
| Cavity quantum electrodynamics | 2 | True | True | pass |
| On-chip coupling and integration | 3 | True | True | pass |
| Tunable and nonlinear cavity devices | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| quality factor | True | True | 3 | pass |
| mode volume | False | True | 5 | fail |
| coupling loss | True | True | 3 | pass |
| fabrication disorder | True | True | 3 | pass |
| thermal stability | True | True | 3 | pass |

## Interpretation

- Key turning papers: 9 total, 9 with access links, 3 with primary local sections, 3 with strong/moderate parser provenance, 2 with decision-grade current-contract evidence.
- Future candidates: 320 graph candidates, 0 Radar cards, 0 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: 5/5 constraints have typed/clickable evidence contracts.
- Reading path contracts: 5/5 steps are auditable; modes=bottleneck, branch_driver, future_candidate, starter, turning.
- Benchmark topics are regression fixtures, not a product allowlist or an LLM cost-control boundary.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- future candidates exist but no complete Claim Cards are promoted

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| missing_bottleneck_section_evidence | mode volume | 100 | 5 | Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_stale_parser_contract |  | 90 | 1 | key turning paper has strong/moderate section provenance but lacks current parser-contract evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 12 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card; frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence |
