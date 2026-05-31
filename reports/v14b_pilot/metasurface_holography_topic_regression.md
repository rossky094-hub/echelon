# Metasurface Holography Topic Regression

- Audit: `2026-05-31T04:48:53Z`
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
| turning papers with primary sections | 4 | 2 | pass |
| turning papers with strong/moderate section provenance | 4 | 2 | pass |
| turning papers with decision-grade section evidence | 4 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 0 | 1 | fail |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

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

- Key turning papers: 8 total, 8 with access links, 4 with primary local sections, 4 with strong/moderate parser provenance, 4 with decision-grade current-contract evidence.
- Future candidates: 3 graph candidates, 0 Radar cards, 0 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: full=0, partial=5, clickable=5/5. Only full typed chains satisfy the lineage gate.
- Reading path contracts: 5/5 steps are auditable; modes=bottleneck, branch_driver, future_candidate, starter, turning.
- Benchmark topics are regression fixtures, not a product allowlist or an LLM cost-control boundary.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- future candidates exist but no complete Claim Cards are promoted

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 4 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card; frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence. missing five-question gates: historical attempts and failure evidence=4, unresolved bottleneck evidence=3; missing high-confidence gates: complete five-question Claim Card=4, current parser-contract decision-grade section evidence=3, strong or moderate section parser provenance=3, strong section-level evidence=3, triangulated Step6 fusion evidence=4; incomplete direction ids: 83,84,85,86; complete Claim Cards found only as weak topic context: 82 |
| bottleneck_lineage_missing_topic_specific_typed_chain | efficiency | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=1, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | speckle | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=1, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | field of view | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=1, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | crosstalk | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=1, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | fabrication tolerance | 97 | 2 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=1, but none matched both this topic context and this bottleneck. |
