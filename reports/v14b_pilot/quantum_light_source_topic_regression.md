# Quantum Light Source Topic Regression

- Audit: `2026-05-29T17:40:32Z`
- Topic: `quantum light source`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 2 | 5 | fail |
| key turning papers | 80 | 4 | pass |
| turning papers with access links | 80 | 3 | pass |
| turning papers with primary sections | 0 | 2 | fail |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| Single-photon emitters | 3 | True | True | pass |
| Entangled photon-pair sources | 3 | True | True | pass |
| Integrated quantum photonics | 3 | True | True | pass |
| Deterministic coupling and collection | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Present In Evidence | Status |
| --- | --- | --- |
| brightness | False | fail |
| indistinguishability | False | fail |
| collection efficiency | False | fail |
| scalability | True | pass |
| integration | True | pass |

## Interpretation

- Key turning papers: 80 total, 80 with access links, 0 with primary local sections.
- Future candidates: 320 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- key turning papers lack primary local section evidence
- future candidates exist but no complete Claim Cards are promoted
