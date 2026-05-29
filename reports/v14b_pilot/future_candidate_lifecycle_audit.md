# Future Candidate Lifecycle Audit

- generated_at: `2026-05-29T17:49:21Z`
- total candidates: 1,000
- radar eligible: 0
- run-level calibration audits: 1
- edge-level calibrated candidates: 1,000 / 1,000

## Lifecycle States

| state | count | product meaning |
| --- | ---: | --- |
| future_candidate_unfused | 1,000 | GNN/VGAE candidate only; Step6 has not promoted it to a direction. |

## Calibration Status

| status | count |
| --- | ---: |
| calibrated_with_run_audit | 1,000 |

## Missing Five-Question Gates

| gate | count |
| --- | ---: |
| Step13 Claim Card | 1,000 |
| Step6 fusion direction | 1,000 |

## Top Candidate Pool Samples

- 01KS6F5Z1F33SR77NWE7BDK2J0 -> 01KS6GKQK1Y4S7EMFB2FR9H48M: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6GKPAZPCBT8T8BN9FCY29H -> 01KS6HYJXAN3K8BMTS1K2R6PDB: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6G8NM22XMZXQP6ADT1BKTB -> 01KS6GKPAZPCBT8T8BN9FCY29H: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6HE5D5W71A1GB9G2MXXT75 -> 01KS6HP5WF1X9FFFCHTFYBGTGB: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6HG0RZ7V2A8B99JZ78CD9R -> 01KS6HP5WF1X9FFFCHTFYBGTGB: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6GKPAZPCBT8T8BN9FCY29H -> 01KS6HRQRDVDHA23NJYK7V3X12: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6F5Z1F33SR77NWE7BDK2J0 -> 01KS6HFYZKZMKPZ083T1KHNKNW: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6F6SPEAWZCWHA3N8ZP4R4F -> 01KS6GKPAZPCBT8T8BN9FCY29H: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6GX5A2SX4R0K9P0QNGX9T1 -> 01KS6HE5D5W71A1GB9G2MXXT75: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6FFJZ9VTXHJYCMYQSNNHYK -> 01KS6GKPAZPCBT8T8BN9FCY29H: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6GDDS2EYMDC51Y6RAAVFKZ -> 01KS6HE5D5W71A1GB9G2MXXT75: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6
- 01KS6F5Z1F33SR77NWE7BDK2J0 -> 01KS6J8B2560Y9XZBTDQG45MS0: state=future_candidate_unfused, score=0.833, reason=Step5b model candidate has not been fused by Step6

## Product Rule

Future candidates are inspection targets until they pass Step6 fusion and Step13 Claim Card gates. Rows in `future_candidate_unfused`, `fused_direction_missing_claim_card`, or `candidate_pool_incomplete_claim_card` must not appear in the Radar main view.
