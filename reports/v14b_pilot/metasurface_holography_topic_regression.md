# Metasurface Holography Topic Regression

- Audit: `2026-05-30T14:35:35Z`
- Topic: `metasurface holography`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 5 | 5 | pass |
| key turning papers | 8 | 4 | pass |
| turning papers with access links | 8 | 3 | pass |
| turning papers with primary sections | 3 | 2 | pass |
| turning papers with strong/moderate section provenance | 2 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 5 | 1 | pass |
| auditable reading path | 4 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | fail |

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

- Key turning papers: 8 total, 8 with access links, 3 with primary local sections, 2 with strong/moderate parser provenance.
- Future candidates: 0 graph candidates, 0 Radar cards, 0 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: 5/5 constraints have typed/clickable evidence contracts.
- Reading path contracts: 4/4 steps are auditable; modes=bottleneck, branch_driver, starter, turning.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_weak_section_provenance |  | 90 | 1 | key turning paper has only weak section parser provenance |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidate_generation_missing |  | 87 | 8 | No Step5b future candidates matched this topic, so Radar must stay empty. Frontfill branch-driver, bottleneck, and turning-paper sections so the next Step5b/Step6/Step13 run can test whether this is a true absence or an evidence gap. |
