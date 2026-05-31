# Photonic Crystal Cavity Topic Regression

- Audit: `2026-05-31T06:33:54Z`
- Topic: `photonic crystal cavity`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 3 | 5 | fail |
| key turning papers | 9 | 4 | pass |
| turning papers with access links | 9 | 3 | pass |
| turning papers with primary sections | 6 | 2 | pass |
| turning papers with strong/moderate section provenance | 3 | 2 | pass |
| turning papers with decision-grade section evidence | 3 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 0 | 1 | fail |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 1 | 1 | pass |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| High-Q nanocavities | 3 | True | True | pass |
| Cavity quantum electrodynamics | 2 | True | True | pass |
| On-chip coupling and integration | 3 | True | True | pass |
| Tunable and nonlinear cavity devices | 3 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| quality factor | True | True | 3 | pass |
| mode volume | False | True | 5 | fail |
| coupling loss | True | True | 3 | pass |
| fabrication disorder | True | True | 3 | pass |
| thermal stability | False | True | 3 | fail |

## Interpretation

- Key turning papers: 9 total, 9 with access links, 6 with primary local sections, 3 with strong/moderate parser provenance, 3 with decision-grade current-contract evidence.
- Future candidates: 320 graph candidates, 1 Radar cards, 1 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: full=0, partial=5, clickable=5/5. Only full typed chains satisfy the lineage gate.
- Reading path contracts: 5/5 steps are auditable; modes=bottleneck, branch_driver, claim_card, starter, turning.
- Benchmark topics are regression fixtures, not a product allowlist or an LLM cost-control boundary.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| missing_bottleneck_section_evidence | mode volume | 100 | 5 | Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence |
| missing_bottleneck_section_evidence | thermal stability | 100 | 3 | Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence |
| key_turning_paper_weak_section_provenance |  | 90 | 1 | key turning paper has only weak section parser provenance |
| key_turning_paper_weak_section_provenance |  | 90 | 1 | key turning paper has only weak section parser provenance |
| key_turning_paper_weak_section_provenance |  | 90 | 1 | key turning paper has only weak section parser provenance |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| bottleneck_lineage_missing_topic_specific_typed_chain | quality factor | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | mode volume | 94 | 5 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | coupling loss | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | fabrication disorder | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | thermal stability | 94 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
