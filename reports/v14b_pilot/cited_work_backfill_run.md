# V14B Cited Work Backfill Run

- generated_at: `2026-05-31T00:21:14Z`
- queue targets considered: 10
- processed targets: 10
- dry_run: `False`
- corpus_id: `optics`

## Status Counts

| status | targets |
| --- | ---: |
| inserted | 6 |
| skip_existing_local_work | 4 |

## Provider Counts

| provider | targets |
| --- | ---: |
| doi | 6 |
| openalex | 4 |

## Exact Relink Apply

```json
{
  "after": {
    "linked_refs": 451905,
    "refs": 3215592
  },
  "apply_result": {
    "link_updates_applied": 2864,
    "norm_updates_applied": 0
  },
  "before": {
    "linked_refs": 449041,
    "refs": 3215592
  },
  "candidate_summary": {
    "provider_status_counts": {
      "arxiv": {
        "no_local_match": 7616
      },
      "doi": {
        "exact_linkable": 1534,
        "no_local_match": 1408747
      },
      "openalex": {
        "exact_linkable": 1330,
        "no_local_match": 1291518
      },
      "s2": {
        "no_local_match": 55806
      }
    },
    "samples": {
      "exact_linkable": [
        {
          "citing_paper_id": "01KRCY3ZVQ25HSKVKMWE3DCWWQ",
          "external": "W4211100070",
          "norm": "W4211100070",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 7374,
          "target_id": "01KSXPEVDM8V5Y5GX0CPSZAR2V"
        },
        {
          "citing_paper_id": "01KRCY438J3RA84CM0D4BXPGVJ",
          "external": "W4211100070",
          "norm": "W4211100070",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 8909,
          "target_id": "01KSXPEVDM8V5Y5GX0CPSZAR2V"
        },
        {
          "citing_paper_id": "01KRCY4TFP542QH4FKPCWNZZ5S",
          "external": "W4211100070",
          "norm": "W4211100070",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 19780,
          "target_id": "01KSXPEVDM8V5Y5GX0CPSZAR2V"
        },
        {
          "citing_paper_id": "01KRCY5HNJMY6D0R2XW20Z5AZK",
          "external": "W2018387403",
          "norm": "W2018387403",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 23394,
          "target_id": "01KSXPF0GB8A119RYD57XBPN9R"
        },
        {
          "citing_paper_id": "01KRCY5HNJMY6D0R2XW20Z5AZK",
          "external": "W2116393805",
          "norm": "W2116393805",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 23411,
          "target_id": "01KSXPF28AYHJ69GFR7MCH7V31"
        },
        {
          "citing_paper_id": "01KRCY5QZ65VT3EDQTYHY7RWSZ",
          "external": "W2018387403",
          "norm": "W2018387403",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 25109,
          "target_id": "01KSXPF0GB8A119RYD57XBPN9R"
        },
        {
          "citing_paper_id": "01KRCY68XXTK5THXR5FYZ6Q42Q",
          "external": "W2038400164",
          "norm": "W2038400164",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 30874,
          "target_id": "01KSXPEYTBGFVCA9WHTYWZ36VQ"
        },
        {
          "citing_paper_id": "01KRCY72AJ8PHRKSNS4XS2QP1R",
          "external": "W4211100070",
          "norm": "W4211100070",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 35365,
          "target_id": "01KSXPEVDM8V5Y5GX0CPSZAR2V"
        },
        {
          "citing_paper_id": "01KRCY72XMRY47296W6SKEF9WA",
          "external": "W4211100070",
          "norm": "W4211100070",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 35589,
          "target_id": "01KSXPEVDM8V5Y5GX0CPSZAR2V"
        },
        {
          "citing_paper_id": "01KRCY7QX0KWZW8MJ4E0453X3S",
          "external": "W2018387403",
          "norm": "W2018387403",
          "old_norm": null,
          "old_provider": null,
          "provider": "openalex",
          "rowid": 36960,
          "target_id": "01KSXPF0GB8A119RYD57XBPN9R"
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
    "scanned_unlinked_refs": 2766551,
    "stale_norm_updates": {},
    "status_counts": {
      "exact_linkable": 2864,
      "no_local_match": 2763687
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
      "unique_ids": 33019
    },
    "openalex": {
      "collision_ids": 0,
      "sample_collisions": {},
      "unique_ids": 35673
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
| inserted | doi | `01KSXPEVDM8V5Y5GX0CPSZAR2V` | Optical microcavities | 116 |
| skip_existing_local_work | openalex | `01KSXPEVDM8V5Y5GX0CPSZAR2V` |  | 0 |
| inserted | doi | `01KSXPEX2XKKJNWT49GFQVE3PR` | Dynamical thermal behavior and thermal self-stability of microcavities | 18 |
| inserted | doi | `01KSXPEYTBGFVCA9WHTYWZ36VQ` | Kerr-Nonlinearity Optical Parametric Oscillation in an Ultrahigh-<mml:math xmlns:mml="http://www.w3. | 29 |
| inserted | doi | `01KSXPF0GB8A119RYD57XBPN9R` | CMOS-compatible multiple-wavelength oscillator for on-chip optical interconnects | 30 |
| inserted | doi | `01KSXPF28AYHJ69GFR7MCH7V31` | Carrier-Envelope Phase Control of Femtosecond Mode-Locked Lasers and Direct Optical Frequency Synthe | 26 |
| inserted | doi | `01KSXPF3YCRVV2BW3PXF7ZMY1H` | Ultra-high-Q toroid microcavity on a chip | 23 |
| skip_existing_local_work | openalex | `01KSXPF3YCRVV2BW3PXF7ZMY1H` |  | 0 |
| skip_existing_local_work | openalex | `01KSXPF28AYHJ69GFR7MCH7V31` |  | 0 |
| skip_existing_local_work | openalex | `01KSXPEYTBGFVCA9WHTYWZ36VQ` |  | 0 |
