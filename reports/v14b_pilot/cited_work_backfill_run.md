# V14B Cited Work Backfill Run

- generated_at: `2026-05-31T00:10:45Z`
- queue targets considered: 5
- processed targets: 5
- dry_run: `False`
- corpus_id: `optics`

## Status Counts

| status | targets |
| --- | ---: |
| fetch_failed | 1 |
| inserted | 4 |

## Provider Counts

| provider | targets |
| --- | ---: |
| doi | 3 |
| openalex | 2 |

## Exact Relink Apply

```json
{
  "after": {
    "linked_refs": 449041,
    "refs": 3215350
  },
  "apply_result": {
    "link_updates_applied": 3084,
    "norm_updates_applied": 0
  },
  "before": {
    "linked_refs": 445957,
    "refs": 3215350
  },
  "candidate_summary": {
    "provider_status_counts": {
      "arxiv": {
        "no_local_match": 7616
      },
      "doi": {
        "exact_linkable": 2205,
        "no_local_match": 1410281
      },
      "openalex": {
        "exact_linkable": 879,
        "no_local_match": 1292606
      },
      "s2": {
        "no_local_match": 55806
      }
    },
    "samples": {
      "exact_linkable": [
        {
          "citing_paper_id": "01KRCY312YN7XCR8K0RSN906A1",
          "external": "W2078171652",
          "norm": "W2078171652",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 1237,
          "target_id": "01KSXNVPMJH24SCTY1ZJJ09Z8J"
        },
        {
          "citing_paper_id": "01KRCY3ZVQ25HSKVKMWE3DCWWQ",
          "external": "W2056908124",
          "norm": "W2056908124",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 7348,
          "target_id": "01KSXNVN2CS1R4KN67RGCXAD7W"
        },
        {
          "citing_paper_id": "01KRCY63Q9FFHEDKEZJXWZH2MB",
          "external": "W2056908124",
          "norm": "W2056908124",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 28803,
          "target_id": "01KSXNVN2CS1R4KN67RGCXAD7W"
        },
        {
          "citing_paper_id": "01KRCY6VK8Z8TDPRPWH2FQPHQT",
          "external": "W2056908124",
          "norm": "W2056908124",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 34964,
          "target_id": "01KSXNVN2CS1R4KN67RGCXAD7W"
        },
        {
          "citing_paper_id": "01KRCY6VK8Z8TDPRPWH2FQPHQT",
          "external": "W2078171652",
          "norm": "W2078171652",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 34967,
          "target_id": "01KSXNVPMJH24SCTY1ZJJ09Z8J"
        },
        {
          "citing_paper_id": "01KRCY7SQWKMA6B0QDV0BFVRCN",
          "external": "W2056908124",
          "norm": "W2056908124",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 38370,
          "target_id": "01KSXNVN2CS1R4KN67RGCXAD7W"
        },
        {
          "citing_paper_id": "01KRCY7WBSEGDPH3EDAX864WJJ",
          "external": "W2078171652",
          "norm": "W2078171652",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 39898,
          "target_id": "01KSXNVPMJH24SCTY1ZJJ09Z8J"
        },
        {
          "citing_paper_id": "01KRCY7XH1R5GX1FSJAWT6671B",
          "external": "W2078171652",
          "norm": "W2078171652",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 41011,
          "target_id": "01KSXNVPMJH24SCTY1ZJJ09Z8J"
        },
        {
          "citing_paper_id": "01KRCY84EYQWECQHV8KCXZM775",
          "external": "W2056908124",
          "norm": "W2056908124",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 46233,
          "target_id": "01KSXNVN2CS1R4KN67RGCXAD7W"
        },
        {
          "citing_paper_id": "01KRCY84SJT2RGTM2GVKV17MGA",
          "external": "W2056908124",
          "norm": "W2056908124",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 46494,
          "target_id": "01KSXNVN2CS1R4KN67RGCXAD7W"
        }
      ],
      "no_local_match": [
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1584473279",
          "norm": "W1584473279",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 1,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1621118049",
          "norm": "W1621118049",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 2,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1638898044",
          "norm": "W1638898044",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 3,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1652183760",
          "norm": "W1652183760",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 4,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1793549306",
          "norm": "W1793549306",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 5,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1931024301",
          "norm": "W1931024301",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 6,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1963728593",
          "norm": "W1963728593",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 7,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1964886550",
          "norm": "W1964886550",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 8,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1974612635",
          "norm": "W1974612635",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 9,
          "target_id": null
        },
        {
          "citing_paper_id": "01KRCY2G6SB9NMY59FPXRE7B8M",
          "external": "W1980113295",
          "norm": "W1980113295",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 10,
          "target_id": null
        }
      ]
    },
    "scanned_unlinked_refs": 2769393,
    "stale_norm_updates": {},
    "status_counts": {
      "exact_linkable": 3084,
      "no_local_match": 2766309
    }
  },
  "paper_id_map_stats": {
    "arxiv": {
      "collision_ids": 0,
      "sample_collisions": {},
      "unique_ids": 55391
    },
    "doi": {
      "collision_ids": 0,
      "sample_collisions": {},
      "unique_ids": 33013
    },
    "openalex": {
      "collision_ids": 0,
      "sample_collisions": {},
      "unique_ids": 35667
    },
    "s2": {
      "collision_ids": 0,
      "sample_collisions": {},
      "unique_ids": 49014
    }
  }
}
```

## Product Interpretation

Inserted cited works strengthen the local evidence corpus only after exact relinking connects them to existing references. They remain evidence acquisition records, not branch, main-path, bottleneck, or Radar conclusions.

## Sample Results

| status | provider | local_paper_id | title | refs |
| --- | --- | --- | --- | ---: |
| fetch_failed | openalex | `` |  | 0 |
| inserted | doi | `01KSXNVKDD9R3QN3GCT42SXM93` | Nonlinear Fiber Optics | 36 |
| inserted | doi | `01KSXNVN2CS1R4KN67RGCXAD7W` | Optical frequency metrology | 65 |
| inserted | openalex | `01KSXNVPMJH24SCTY1ZJJ09Z8J` | Microresonator-Based Optical Frequency Combs | 38 |
| inserted | doi | `01KSXNVR93XRMQ9FWMD1BZXWQX` | Nonlinear Optics | 81 |
