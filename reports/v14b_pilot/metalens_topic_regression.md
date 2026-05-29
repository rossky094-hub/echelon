# Metalens Topic Regression

- Audit: `2026-05-29T18:27:34Z`
- Topic: `metalens`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 6 | 4 | pass |
| expected bottlenecks evidenced | 6 | 6 | pass |
| key turning papers | 13 | 5 | pass |
| turning papers with access links | 13 | 5 | pass |
| turning papers with primary sections | 0 | 3 | fail |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| Imaging systems | 3 | True | True | pass |
| Broadband achromatic correction | 3 | True | True | pass |
| High-NA focusing performance | 3 | True | True | pass |
| Tunable and multifunctional optics | 3 | True | True | pass |
| Manufacturing scale-up | 3 | True | True | pass |
| Computational compensation and inverse design | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| efficiency | True | True | 4 | pass |
| chromatic aberration | True | True | 3 | pass |
| field of view | True | True | 5 | pass |
| manufacturing consistency | True | True | 3 | pass |
| system integration | True | True | 4 | pass |
| cost | True | True | 3 | pass |

## Interpretation

- Key turning papers: 13 total, 13 with access links, 0 with primary local sections.
- Future candidates: 3 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- key turning papers lack primary local section evidence
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
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 0 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card for this topic |
