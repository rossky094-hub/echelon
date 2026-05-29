# Quantum Light Source Topic Regression

- Audit: `2026-05-29T18:27:35Z`
- Topic: `quantum light source`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 4 | 5 | fail |
| key turning papers | 11 | 4 | pass |
| turning papers with access links | 11 | 3 | pass |
| turning papers with primary sections | 0 | 2 | fail |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| Single-photon emitters | 1 | True | True | pass |
| Entangled photon-pair sources | 3 | True | True | pass |
| Integrated quantum photonics | 3 | True | True | pass |
| Deterministic coupling and collection | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| brightness | True | True | 4 | pass |
| indistinguishability | False | True | 4 | fail |
| collection efficiency | True | True | 4 | pass |
| scalability | True | True | 3 | pass |
| integration | True | True | 4 | pass |

## Interpretation

- Key turning papers: 11 total, 11 with access links, 0 with primary local sections.
- Future candidates: 320 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- key turning papers lack primary local section evidence
- future candidates exist but no complete Claim Cards are promoted

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| missing_bottleneck_section_evidence | indistinguishability | 100 | 4 | Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 0 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card for this topic |
