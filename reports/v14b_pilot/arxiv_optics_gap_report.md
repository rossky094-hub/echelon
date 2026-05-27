# arXiv physics.optics gap report

- Generated: 2026-05-24
- API totalResults (cat:physics.optics): **56251**
- Enumeration window: 1991-01-01 .. 2026-05-24
- Unique arXiv IDs fetched (window): **53723**
- DB papers with arxiv_id: **54135**
- In arXiv window but not in DB: **1294**
- In DB but not in arXiv window fetch: **1706**
- In both but monitor optics tag missing: **0**

## Root cause notes

1. **True crawl gap**: IDs in `arxiv_optics_missing_ids.txt`.
2. **Filter artifact**: monitor uses `primary_topic_id LIKE '%optics%'` OR `raw_jsonb` contains `physics.optics`.
3. **Backfill 10k cap**: `cat:physics.optics` without monthly `submittedDate` hits API start=10000 (500 errors in logs).
4. **Worker `failed` counter**: often `UNIQUE constraint failed: papers.arxiv_id` on version collisions during refresh, not absent rows.
5. **Target 56000**: approximate; live API total drifts (e.g. 56251).

## Sample missing IDs (first 30)

- `0711.3064`
- `0805.4496`
- `0810.0903`
- `1004.3586`
- `1007.2033`
- `1009.3709`
- `1104.0110`
- `1110.3024`
- `1207.2272`
- `1310.0882`
- `1311.7158`
- `1312.6020`
- `1403.4857`
- `1406.3723`
- `1409.1853`
- `1410.4008`
- `1509.08592`
- `1510.01768`
- `1602.03352`
- `1610.00045`
- `1612.03499`
- `1612.06474`
- `1704.04662`
- `1704.04700`
- `1705.09526`
- `1709.04512`
- `1904.09597`
- `1912.05151`
- `2006.04274`
- `2007.15173`

## Enumeration vs API totalResults

Yearly `submittedDate` windows returned **53723** unique IDs vs API **56251** totalResults (~**2528** not seen in yearly enumeration — arXiv index/query quirk or cross-listed edge cases). After directed fetch of the **1294** confirmed missing IDs, expect DB **~55429** unique arxiv_id (54135+1294), still below API total until enumeration gap is closed.

## Actions taken (2026-05-24)

- Stopped redundant `backfill` worker (API `start=10000` 500 errors).
- Ran `scripts/diff_arxiv_optics_vs_db.py` (yearly windows).
- Started `scripts/fetch_missing_arxiv_optics.sh` for 1294 IDs (3s/paper, background).
- Updated monitor `CRAWL_TARGET` default to **56251**.

