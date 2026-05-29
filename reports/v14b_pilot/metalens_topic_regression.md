# Metalens Topic Regression

- Audit: `2026-05-29T17:40:30Z`
- Topic: `metalens`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 6 | 4 | pass |
| expected bottlenecks evidenced | 5 | 6 | fail |
| key turning papers | 80 | 5 | pass |
| turning papers with access links | 80 | 5 | pass |
| turning papers with primary sections | 1 | 3 | fail |
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

| Bottleneck | Present In Evidence | Status |
| --- | --- | --- |
| efficiency | True | pass |
| chromatic aberration | True | pass |
| field of view | False | fail |
| manufacturing consistency | True | pass |
| system integration | True | pass |
| cost | True | pass |

## Interpretation

- Key turning papers: 80 total, 80 with access links, 1 with primary local sections.
- Future candidates: 10 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- future candidates exist but no complete Claim Cards are promoted
