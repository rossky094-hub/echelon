# Photonic Crystal Cavity Topic Regression

- Audit: `2026-05-29T17:40:32Z`
- Topic: `photonic crystal cavity`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 1 | 5 | fail |
| key turning papers | 80 | 4 | pass |
| turning papers with access links | 80 | 3 | pass |
| turning papers with primary sections | 2 | 2 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| High-Q nanocavities | 3 | True | True | pass |
| Cavity quantum electrodynamics | 3 | True | True | pass |
| On-chip coupling and integration | 3 | True | True | pass |
| Tunable and nonlinear cavity devices | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Present In Evidence | Status |
| --- | --- | --- |
| quality factor | False | fail |
| mode volume | False | fail |
| coupling loss | True | pass |
| fabrication disorder | False | fail |
| thermal stability | False | fail |

## Interpretation

- Key turning papers: 80 total, 80 with access links, 2 with primary local sections.
- Future candidates: 320 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- future candidates exist but no complete Claim Cards are promoted
