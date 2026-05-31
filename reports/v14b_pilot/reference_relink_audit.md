# V14B Reference Relink Audit

- generated_at: `2026-05-31T00:11:58Z`
- mode: `dry_run`
- scanned unlinked refs: 2,766,309
- exact linkable refs: 0
- ambiguous local matches: 0
- no local match: 2,766,309
- unclassifiable: 0

## Provider Breakdown

| provider | exact | ambiguous | no local | unclassifiable | stale norm |
| --- | ---: | ---: | ---: | ---: | ---: |
| arxiv | 0 | 0 | 7,616 | 0 | 0 |
| doi | 0 | 0 | 1,410,281 | 0 | 0 |
| openalex | 0 | 0 | 1,292,606 | 0 | 0 |
| s2 | 0 | 0 | 55,806 | 0 | 0 |

## Paper ID Collision Summary

| provider | unique local IDs | collision IDs |
| --- | ---: | ---: |
| doi | 33,013 | 0 |
| openalex | 35,667 | 0 |
| arxiv | 55,391 | 0 |
| s2 | 49,014 | 0 |

## Product Interpretation

Exact relinks strengthen the citation evidence bone without inventing edges. Ambiguous matches must stay unlinked until duplicate papers are resolved. No-local-match references are external context, not missing internal graph edges.
