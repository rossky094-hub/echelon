# Topic-Gap Raw PDF Parser Inspection

- audit_ts: `2026-05-31T05:48:18Z`
- triage_json: `reports/v14b_pilot/topic_gap_section_evidence_audit.json`
- store_root: `/Volumes/LaCie/Echelon_Paper_Raw_Data`
- manifest: `/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `warn`

## Summary

- triage papers: 38
- local PDF available papers: 7
- skipped no local PDF: 31
- parser primary-ready papers: 2
- parser weak-primary papers: 4
- parser primary-ready repair candidates: 0
- parser primary-ready already covered: 2
- parser no-target papers: 1
- parser no-target repair-signal papers: 0
- parser no-target subthreshold-signal papers: 0
- parser exception papers: 0

## Classification Counts

| classification | papers |
|---|---:|
| parser_success_weak_primary | 4 |
| parser_success_primary | 2 |
| parser_no_target_sections | 1 |

## Recommended Action Counts

| action | papers |
|---|---:|
| weak_primary_context_only | 4 |
| already_covered_parser_control | 2 |
| weak_fulltext_or_metadata_only | 1 |

## No-Target Shape Counts

| no_target_classification | papers |
|---|---:|
| sectionless_or_non_target_heading_format | 1 |

## Local PDF Rows

| paper_id | topics | triage failure | parser classification | no-target shape | recommended action | examples | primary sections | section strategies | title |
|---|---|---|---|---|---|---|---|---|---|
| `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` | `sectionless_or_non_target_heading_format` | `weak_fulltext_or_metadata_only` | An open cavity formed with a photonic crystal of negative; Zhichao Ruan and Sailing He |  |  | An open cavity formed with a photonic crystal of negative refraction |
| `01KS5KM369VWG4F2AV2MS14S3E` | photonic crystal cavity | `current_contract_weak` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Surface state photonic bandgap cavities |
| `01KS5KMDAC6220S2FEJCB6XVTB` | photonic crystal cavity | `current_contract_weak` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Silicon-based photonic crystal nanocavity light emitters |
| `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `current_contract_weak` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Ultra-bright source of polarization-entangled photons |
| `01KS5KWKMCV3DHKBFJH2Z0JN6A` | photonic crystal cavity | `current_contract_weak` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Fabrication-tolerant high quality factor photonic crystal microcavities |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens, metasurface holography, quantum light source | `decision_grade_current_contract` | `parser_success_primary` | `` | `already_covered_parser_control` |  | results | results:heading_continuation,inline_heading | Optical frequency comb generation from a monolithic microresonator |
| `01KS6F6SPEAWZCWHA3N8ZP4R4F` | quantum light source | `decision_grade_current_contract` | `parser_success_primary` | `` | `already_covered_parser_control` |  | experiments | experiments:heading_continuation,inline_heading | Coherent, multi-heterodyne spectroscopy using stabilized optical frequency combs |

## Policy

This is a read-only parser dry run. Rows with parser_success_primary and candidate_pool_only policy are local-cache candidates for the next safe Step5s ingest boundary; already-covered rows are useful parser controls but not counted as repair lift. Rows with parser_success_weak_primary are weak terminal-cue context only and remain blocked from decision-grade promotion. No row is promoted until paper_sections, section_atoms, and typed chains are rebuilt with provenance.
