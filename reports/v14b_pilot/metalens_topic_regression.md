# Metalens Topic Regression

- Audit: `2026-05-31T05:55:46Z`
- Topic: `metalens`
- Overall status: **warn**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 6 | 4 | pass |
| expected bottlenecks evidenced | 6 | 6 | pass |
| key turning papers | 13 | 5 | pass |
| turning papers with access links | 13 | 5 | pass |
| turning papers with primary sections | 8 | 3 | pass |
| turning papers with strong/moderate section provenance | 8 | 3 | pass |
| turning papers with decision-grade section evidence | 8 | 3 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 1 | 1 | pass |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| Imaging systems | 3 | True | True | pass |
| Broadband achromatic correction | 3 | True | True | pass |
| High-NA focusing performance | 3 | True | True | pass |
| Tunable and multifunctional optics | 3 | True | True | pass |
| Manufacturing scale-up | 2 | True | True | pass |
| Computational compensation and inverse design | 2 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| efficiency | True | True | 4 | pass |
| chromatic aberration | True | True | 3 | pass |
| field of view | True | True | 5 | pass |
| manufacturing consistency | True | True | 2 | pass |
| system integration | True | True | 4 | pass |
| cost | True | True | 2 | pass |

## Interpretation

- Key turning papers: 13 total, 13 with access links, 8 with primary local sections, 8 with strong/moderate parser provenance, 8 with decision-grade current-contract evidence.
- Future candidates: 3 graph candidates, 0 Radar cards, 0 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: full=1, partial=5, clickable=5/5. Only full typed chains satisfy the lineage gate.
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
| future_candidates_missing_claim_card |  | 85 | 4 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card; frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence. complete Claim Cards found only as weak topic context: 102,103,104,105,106 |
