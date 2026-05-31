# Metasurface Holography Topic Regression

- Audit: `2026-05-31T12:21:21Z`
- Topic: `metasurface holography`
- Overall status: **fail**

## Gates

| Gate | Actual | Required | Status |
| --- | ---: | ---: | --- |
| expected branches found | 1.00 | 1.0 | pass |
| branches with driver papers | 4 | 3 | pass |
| expected bottlenecks evidenced | 4 | 5 | fail |
| key turning papers | 8 | 4 | pass |
| turning papers with access links | 8 | 3 | pass |
| turning papers with primary sections | 2 | 2 | pass |
| turning papers with strong/moderate section provenance | 2 | 2 | pass |
| turning papers with decision-grade section evidence | 2 | 2 | pass |
| five-question evidence contracts | 5 | 5 | pass |
| bottleneck lineage typed contracts | 1 | 1 | pass |
| auditable reading path | 5 | 4 | pass |
| Claim Cards for Radar | 0 | 1 | warn |

## Expected Branches

| Branch | Drivers | Bottleneck | Enabler | Status |
| --- | ---: | --- | --- | --- |
| High-efficiency visible holography | 3 | True | True | pass |
| Large field-of-view holography | 3 | True | True | pass |
| Multiplexed and dynamic holography | 2 | True | True | pass |
| Fabrication-tolerant metasurface design | 2 | True | True | pass |

## Expected Bottlenecks

| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |
| --- | --- | --- | ---: | --- |
| efficiency | True | True | 3 | pass |
| speckle | True | True | 3 | pass |
| field of view | True | True | 3 | pass |
| crosstalk | False | True | 2 | fail |
| fabrication tolerance | True | True | 2 | pass |

## Interpretation

- Key turning papers: 8 total, 8 with access links, 2 with primary local sections, 2 with strong/moderate parser provenance, 2 with decision-grade current-contract evidence.
- Future candidates: 4 graph candidates, 0 Radar cards, 0 complete cards.
- Five-question evidence contracts: 5/5 have claim scope, evidence grade, uncertainty, and clickable evidence.
- Bottleneck lineage contracts: full=1, partial=5, clickable=5/5. Only full typed chains satisfy the lineage gate.
- Reading path contracts: 5/5 steps are auditable; modes=bottleneck, branch_driver, future_candidate, starter, turning.
- Benchmark topics are regression fixtures, not a product allowlist or an LLM cost-control boundary.
- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.

## Quality Gaps

- future candidates exist but no complete Claim Cards are promoted

## Evidence Gap Queue

| Gap | Bottleneck | Priority | Candidate Papers | Why |
| --- | --- | ---: | ---: | --- |
| missing_bottleneck_section_evidence | crosstalk | 100 | 2 | Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| key_turning_paper_missing_primary_section |  | 90 | 1 | key turning paper lacks local primary section evidence |
| future_candidates_missing_claim_card |  | 85 | 4 | Future candidates exist but Step6/Step13 has not produced a complete Claim Card; frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence. complete Claim Cards found only as weak topic context: 127,128,129,130,131 |
| key_turning_paper_missing_primary_section |  | 95 | 6 | Topic turning papers cannot support lineage or Claim Card interpretation until their local primary sections are parsed. |
| bottleneck_lineage_or_resolution_evidence_gap |  | 95 | 5 | Bottleneck claims need unresolved and resolved section atoms linked into typed chains before they can constrain Step13 decisions. |
| bottleneck_lineage_or_resolution_evidence_gap |  | 95 | 5 | Bottleneck claims need unresolved and resolved section atoms linked into typed chains before they can constrain Step13 decisions. |
| bottleneck_lineage_or_resolution_evidence_gap |  | 95 | 5 | Bottleneck claims need unresolved and resolved section atoms linked into typed chains before they can constrain Step13 decisions. |
| branch_lineage_needs_evidence |  | 85 | 3 | Branch splits remain weak/layout candidates until driver papers and section-level constraint shifts are parsed. |
| branch_lineage_needs_evidence |  | 85 | 3 | Branch splits remain weak/layout candidates until driver papers and section-level constraint shifts are parsed. |
| branch_lineage_needs_evidence |  | 85 | 2 | Branch splits remain weak/layout candidates until driver papers and section-level constraint shifts are parsed. |
| future_candidates_missing_claim_card |  | 85 | 4 | GNN/VGAE future edges are useful for recall, but they need fusion evidence and complete five-question Claim Cards before decision use. |
