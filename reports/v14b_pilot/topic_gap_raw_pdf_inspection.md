# Topic-Gap Raw PDF Parser Inspection

- audit_ts: `2026-05-31T04:27:52Z`
- triage_json: `reports/v14b_pilot/topic_gap_section_evidence_audit.json`
- store_root: `/Volumes/LaCie/Echelon_Paper_Raw_Data`
- manifest: `/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `warn`

## Summary

- triage papers: 47
- local PDF available papers: 7
- skipped no local PDF: 40
- parser primary-ready papers: 2
- parser primary-ready repair candidates: 0
- parser primary-ready already covered: 2
- parser no-target papers: 5
- parser exception papers: 0

## Classification Counts

| classification | papers |
|---|---:|
| parser_no_target_sections | 5 |
| parser_success_primary | 2 |

## Local PDF Rows

| paper_id | topics | triage failure | parser classification | primary sections | section strategies | title |
|---|---|---|---|---|---|---|
| `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` |  |  | An open cavity formed with a photonic crystal of negative refraction |
| `01KS5KM369VWG4F2AV2MS14S3E` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` |  |  | Surface state photonic bandgap cavities |
| `01KS5KMDAC6220S2FEJCB6XVTB` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` |  |  | Silicon-based photonic crystal nanocavity light emitters |
| `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `no_target_sections_after_current_parser` | `parser_no_target_sections` |  |  | Ultra-bright source of polarization-entangled photons |
| `01KS5KWKMCV3DHKBFJH2Z0JN6A` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` |  |  | Fabrication-tolerant high quality factor photonic crystal microcavities |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens, metasurface holography, photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `parser_success_primary` | results | results:heading_continuation,inline_heading | Optical frequency comb generation from a monolithic microresonator |
| `01KS6F6SPEAWZCWHA3N8ZP4R4F` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `parser_success_primary` | experiments | experiments:heading_continuation,inline_heading | Coherent, multi-heterodyne spectroscopy using stabilized optical frequency combs |

## Policy

This is a read-only parser dry run. Rows with parser_success_primary and candidate_pool_only policy are local-cache candidates for the next safe Step5s ingest boundary; already-covered rows are useful parser controls but not counted as repair lift. No row is promoted until paper_sections, section_atoms, and typed chains are rebuilt with provenance.
