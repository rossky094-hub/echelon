# Raw PDF Store Audit

- generated_at: `2026-05-31T04:28:23Z`
- status: **warn**
- store_root: `/Volumes/LaCie/Echelon_Paper_Raw_Data`
- manifest: `/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3`

## Manifest

| status | papers | GB |
|---|---:|---:|
| failed | 1 | 0.00 |
| http_error | 36 | 0.00 |
| queued | 53242 | 0.00 |
| success | 2112 | 0.66 |

- success probable PDFs: 2112/2112 (100.0%)
- success existing paths: 2112

## Section Reuse

- section rows from local raw PDF cache: 0
- papers from local raw PDF cache: 0
- successful local-cache section attempts: 0

## Candidate Queue Coverage

- candidate_file: `reports/v14b_pilot/multi_topic_evidence_gap_queue.csv`
- queue papers: 47
- raw PDF available papers: 7 (14.9%)
- sample missing paper_ids: 01KS5KVWY6VAA6HXWFJV2SXZ48, 01KS6FG0VYNT6MYBBYMX8TBYDR, 01KS6FFJF6XNCHFY2X589F6QD5, 01KS6FGD433ZJXYBXPYVZ727SG, 01KS6FK557AWZRGP7QFMMBVT17, 01KS6GND5KCR5HPW1YFZYW5ANY, 01KS6H25PCS743PEWJ8HF8YGEH, 01KS6GKT1AN2MQ1NXP1ZJY5EKA, 01KS6HDG6MYN3Y7HPYW7KRRKQJ, 01KS6HGSMCY03E789TEE3B0FCT

## Warnings

- raw PDF cache has successful downloads but section ingest has not consumed local-cache PDFs yet

## Next Actions

- Restart or launch the next section ingest with local raw PDF cache env vars after the active run reaches a safe stop.
- Prioritize queue papers with local raw PDFs for low-latency parser tuning and atom/chain rebuilds.
