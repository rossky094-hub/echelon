# Photonic Crystal Cavity Topic Regression

- Audit: `2026-05-29T18:13:10Z`
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
| turning papers with primary sections | 1 | 2 | fail |
| Claim Cards for Radar | 1 | 1 | pass |

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

- Key turning papers: 80 total, 80 with access links, 1 with primary local sections.
- Future candidates: 320 graph candidates, 1 Radar cards, 1 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.
