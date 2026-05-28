# V14B Stratified LLM Edge Audit Plan

- Job ID: `edgeaudit-20260528000743`
- Selected items: **22,458**
- Estimated input tokens: **19,106,554**
- Estimated output tokens: **4,042,440**
- Estimated Doubao cost: **¥47.62**

## Buckets

| bucket | n |
|---|---:|
| `all_branch_lineage` | 5,443 |
| `all_future_growth` | 1,000 |
| `all_main_path` | 2,837 |
| `cross_cluster` | 2,000 |
| `cross_field` | 2,000 |
| `high_centrality` | 2,000 |
| `low_confidence` | 2,000 |
| `sample_citation` | 2,000 |
| `sample_cocitation` | 2,000 |
| `sample_semantic_similarity` | 2,000 |

## Types

| type | n |
|---|---:|
| `branch_lineage` | 5,443 |
| `citation` | 4,665 |
| `cocitation` | 6,454 |
| `future_growth` | 1,000 |
| `main_path` | 2,837 |
| `semantic_similarity` | 2,059 |

## Execution

Default execution is capped. Increase `V14B_LLM_EDGE_AUDIT_MAX_CALLS` deliberately.

```bash
LLM_PROVIDER=doubao python3 -m echelon.v14b.step11_llm_edge_audit --db-v14 db/v14_pilot.sqlite3 --job-id edgeaudit-20260528000743 --execute --max-calls 100
```
