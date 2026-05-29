# Metasurface Holography Topic Regression

- Audit: `2026-05-29T18:13:09Z`
- Topic: `metasurface holography`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 2 | 5 | fail |
| key turning papers | 80 | 4 | pass |
| turning papers with access links | 80 | 3 | pass |
| turning papers with primary sections | 3 | 2 | pass |
| Claim Cards for Radar | 0 | 1 | fail |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| High-efficiency visible holography | 3 | True | True | pass |
| Large field-of-view holography | 3 | True | True | pass |
| Multiplexed and dynamic holography | 3 | True | True | pass |
| Fabrication-tolerant metasurface design | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Present In Evidence | Status |
| --- | --- | --- |
| efficiency | True | pass |
| speckle | True | pass |
| field of view | False | fail |
| crosstalk | False | fail |
| fabrication tolerance | False | fail |

## Interpretation

- Key turning papers: 80 total, 80 with access links, 3 with primary local sections.
- Future candidates: 0 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.
