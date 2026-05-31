# Raw PDF Store Audit

- generated_at: `2026-05-31T12:25:00Z`
- status: **pass**
- store_root: `/Volumes/LaCie/Echelon_Paper_Raw_Data`
- manifest: `/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3`

## Manifest

| status | papers | GB |
|---|---:|---:|
| failed | 6 | 0.00 |
| http_error | 54 | 0.00 |
| queued | 50088 | 0.00 |
| success | 5243 | 2.75 |

- success probable PDFs: 5243/5243 (100.0%)
- success existing paths: 5243

## Section Reuse

- section rows from local raw PDF cache: 6
- papers from local raw PDF cache: 6
- successful local-cache section attempts: 8

## Candidate Queue Coverage

- candidate_file: `reports/v14b_pilot/multi_topic_evidence_gap_queue.csv`
- queue papers: 78
- raw PDF available papers: 18 (23.1%)
- sample missing paper_ids: 01KS6HJEXQGTKP950NRDA3CVT2, 01KS6HK2C4GYG2KSM1BA314XPY, 01KS6GND5KCR5HPW1YFZYW5ANY, 01KS6H23DPA3GB6AYCZYA8X08T, 01KS6GG3QQ4KDB4CAS1PMND5FV, 01KS6GQGRRD3AR4MY361CME1HG, 01KS6HGSMCY03E789TEE3B0FCT, 01KS6HMZS9ACM80N6QJ22RAHGV, 01KS6HPP3KS1MWWYWQ6GW64AV7, 01KS6HVY4CKH0GP6VQK7MXRXEK

## Next Actions

- Prioritize queue papers with local raw PDFs for low-latency parser tuning and atom/chain rebuilds.
