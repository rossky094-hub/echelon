# Photonic Crystal Cavity Topic Regression

- Audit: `2026-05-31T09:47:51Z`
- Topic: `photonic crystal cavity`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 4 | 5 | fail |
| key turning papers | 11 | 4 | pass |
| turning papers with access links | 11 | 3 | pass |
| turning papers with primary sections | 3 | 2 | pass |
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
| thermal stability | True | True | 3 | pass |

## Interpretation

- Key turning papers: 11 total, 11 with access links, 3 with primary local sections, 3 with strong/moderate parser provenance, 3 with decision-grade current-contract evidence.
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
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| bottleneck_lineage_missing_topic_specific_typed_chain | quality factor | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | mode volume | 94 | 5 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | coupling loss | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | fabrication disorder | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| bottleneck_lineage_missing_topic_specific_typed_chain | thermal stability | 97 | 3 | Expected bottleneck lacks a topic-specific full typed section chain (constraint -> failure mechanism -> attempted path -> local fix -> new constraint). Promotable full chains available globally=2, but none matched both this topic context and this bottleneck. |
| key_turning_paper_missing_primary_section |  | 95 | 8 | Topic turning papers cannot support lineage or Claim Card interpretation until their local primary sections are parsed. |
| bottleneck_lineage_or_resolution_evidence_gap |  | 95 | 5 | Bottleneck claims need unresolved and resolved section atoms linked into typed chains before they can constrain Step13 decisions. |
| bottleneck_lineage_or_resolution_evidence_gap |  | 95 | 5 | Bottleneck claims need unresolved and resolved section atoms linked into typed chains before they can constrain Step13 decisions. |
| bottleneck_lineage_or_resolution_evidence_gap |  | 95 | 5 | Bottleneck claims need unresolved and resolved section atoms linked into typed chains before they can constrain Step13 decisions. |
| branch_lineage_needs_evidence |  | 85 | 3 | Branch splits remain weak/layout candidates until driver papers and section-level constraint shifts are parsed. |
| branch_lineage_needs_evidence |  | 85 | 2 | Branch splits remain weak/layout candidates until driver papers and section-level constraint shifts are parsed. |
| branch_lineage_needs_evidence |  | 85 | 3 | Branch splits remain weak/layout candidates until driver papers and section-level constraint shifts are parsed. |
