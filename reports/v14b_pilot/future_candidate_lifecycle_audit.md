# Future Candidate Lifecycle Audit

- generated_at: `2026-05-30T17:40:16Z`
- total candidates: 1,000
- radar eligible Claim Cards: 0
- raw edge rows eligible for Radar main view: 0
- run-level calibration audits: 1
- edge-level calibrated candidates: 1,000 / 1,000

## Lifecycle States

| state | count | product meaning |
| --- | ---: | --- |
| candidate_pool_incomplete_claim_card | 21 | Claim Card exists, but at least one of the five hard questions is missing. |
| exploratory_claim_card | 421 | Five-question card is complete, but high-confidence gates are not all satisfied. |
| future_candidate_unfused | 558 | GNN/VGAE candidate only; Step6 has not promoted it to a direction. |

## Calibration Status

| status | count |
| --- | ---: |
| calibrated_with_run_audit | 1,000 |

## Missing Five-Question Gates

| gate | count |
| --- | ---: |
| Step13 Claim Card | 558 |
| Step6 fusion direction | 558 |
| historical attempts and failure evidence | 21 |
| unresolved bottleneck evidence | 4 |

## Top Candidate Pool Samples

- 01KS6F5Z1F33SR77NWE7BDK2J0 -> 01KS6GKQK1Y4S7EMFB2FR9H48M: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6GKPAZPCBT8T8BN9FCY29H -> 01KS6HYJXAN3K8BMTS1K2R6PDB: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6G8NM22XMZXQP6ADT1BKTB -> 01KS6GKPAZPCBT8T8BN9FCY29H: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6HE5D5W71A1GB9G2MXXT75 -> 01KS6HP5WF1X9FFFCHTFYBGTGB: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6HG0RZ7V2A8B99JZ78CD9R -> 01KS6HP5WF1X9FFFCHTFYBGTGB: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6GKPAZPCBT8T8BN9FCY29H -> 01KS6HRQRDVDHA23NJYK7V3X12: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6F5Z1F33SR77NWE7BDK2J0 -> 01KS6HFYZKZMKPZ083T1KHNKNW: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6F6SPEAWZCWHA3N8ZP4R4F -> 01KS6GKPAZPCBT8T8BN9FCY29H: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6GX5A2SX4R0K9P0QNGX9T1 -> 01KS6HE5D5W71A1GB9G2MXXT75: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6FFJZ9VTXHJYCMYQSNNHYK -> 01KS6GKPAZPCBT8T8BN9FCY29H: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6GDDS2EYMDC51Y6RAAVFKZ -> 01KS6HE5D5W71A1GB9G2MXXT75: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open
- 01KS6F5Z1F33SR77NWE7BDK2J0 -> 01KS6J8B2560Y9XZBTDQG45MS0: state=exploratory_claim_card, score=0.833, reason=Claim Card complete but high-confidence gates remain open

## Product Rule

Future candidates are inspection targets.  Even when an edge is covered by a complete Step13 card, Radar must show the Claim Card/direction, not the raw edge row.  The edge table feeds Future/Bottleneck evidence views and the candidate pool only.
