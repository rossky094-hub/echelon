# Metasurface Holography Topic Regression

- Audit: `2026-05-30T22:00:16Z`
- Topic: `metasurface holography`
- Overall status: **warn**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 5 | 5 | pass |
| key turning papers | 8 | 4 | pass |
| turning papers with access links | 8 | 3 | pass |
| turning papers with primary sections | 2 | 2 | pass |
| turning papers with strong/moderate section provenance | 2 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 5 | 1 | pass |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| High-efficiency visible holography | 3 | True | True | pass |
| Large field-of-view holography | 3 | True | True | pass |
| Multiplexed and dynamic holography | 3 | True | True | pass |
| Fabrication-tolerant metasurface design | 2 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| efficiency | True | True | 3 | pass |
| speckle | True | True | 3 | pass |
| field of view | True | True | 3 | pass |
| crosstalk | True | True | 3 | pass |
| fabrication tolerance | True | True | 2 | pass |

## Interpretation

- Key turning papers: 8 total, 8 with access links, 2 with primary local sections, 2 with strong/moderate parser provenance.
- Future candidates: 3 graph candidates, 0 Radar cards, 0 complete cards.
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
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 4 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card; frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence |
