# Quantum Light Source Topic Regression

- Audit: `2026-05-29T14:28:36Z`
- Topic: `quantum light source`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 0.00 | 1.0 | fail |
| branches with driver papers | 0 | 3 | fail |
| expected bottlenecks evidenced | 0 | 5 | fail |
| key turning papers | 80 | 4 | pass |
| turning papers with access links | 80 | 3 | pass |
| turning papers with primary sections | 0 | 2 | fail |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| Single-photon emitters | 0 | False | False | fail |
| Entangled photon-pair sources | 0 | False | False | fail |
| Integrated quantum photonics | 0 | False | False | fail |
| Deterministic coupling and collection | 0 | False | False | fail |

## Expected Bottlenecks

| Bottleneck | Present In Evidence | Status |
| --- | --- | --- |
| brightness | False | fail |
| indistinguishability | False | fail |
| collection efficiency | False | fail |
| scalability | False | fail |
| integration | False | fail |

## Interpretation

- Key turning papers: 80 total, 80 with access links, 0 with primary local sections.
- Future candidates: 320 graph candidates, 0 Radar cards, 0 complete cards.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- bottleneck conclusions have no clickable limitation/section evidence
- key turning papers lack primary local section evidence
- future candidates exist but no complete Claim Cards are promoted
