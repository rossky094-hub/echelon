# V14B Reference Relink Audit

- generated_at: `2026-05-30T23:58:01Z`
- mode: `dry_run`
- scanned unlinked refs: 2,769,173
- exact linkable refs: 4
- ambiguous local matches: 0
- no local match: 2,769,169
- unclassifiable: 0

## Provider Breakdown

| provider | exact | ambiguous | no local | unclassifiable | stale norm |
| --- | ---: | ---: | ---: | ---: | ---: |
| arxiv | 0 | 0 | 7,616 | 0 | 0 |
| doi | 0 | 0 | 1,412,486 | 0 | 0 |
| openalex | 4 | 0 | 1,293,261 | 0 | 0 |
| s2 | 0 | 0 | 55,806 | 0 | 0 |

## Paper ID Collision Summary

| provider | unique local IDs | collision IDs |
| --- | ---: | ---: |
| doi | 33,009 | 0 |
| openalex | 35,663 | 0 |
| arxiv | 55,391 | 0 |
| s2 | 49,014 | 0 |

## Product Interpretation

Exact relinks strengthen the citation evidence bone without inventing edges. Ambiguous matches must stay unlinked until duplicate papers are resolved. No-local-match references are external context, not missing internal graph edges.
