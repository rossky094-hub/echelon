# Topic-Gap Raw PDF Parser Inspection

- audit_ts: `2026-05-31T09:13:09Z`
- triage_json: `reports/v14b_pilot/topic_gap_section_evidence_audit.json`
- store_root: `/Volumes/LaCie/Echelon_Paper_Raw_Data`
- manifest: ``
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `pass`

## Summary

- triage papers: 78
- local PDF available papers: 14
- skipped no local PDF: 64
- parser primary-ready papers: 4
- parser weak-primary papers: 4
- parser primary-ready repair candidates: 2
- parser primary-ready already covered: 2
- parser no-target papers: 6
- parser no-target repair-signal papers: 0
- parser no-target subthreshold-signal papers: 0
- parser exception papers: 0

## Classification Counts

| classification | papers |
|---|---:|
| parser_no_target_sections | 6 |
| parser_success_primary | 4 |
| parser_success_weak_primary | 4 |

## Recommended Action Counts

| action | papers |
|---|---:|
| weak_fulltext_or_metadata_only | 5 |
| weak_primary_context_only | 4 |
| local_cache_ingest_candidate | 2 |
| already_covered_parser_control | 2 |
| heading_taxonomy_review | 1 |

## No-Target Shape Counts

| no_target_classification | papers |
|---|---:|
| sectionless_or_non_target_heading_format | 5 |
| heading_like_but_not_target_section | 1 |

## Local PDF Rows

| paper_id | topics | triage failure | parser classification | no-target shape | recommended action | examples | primary sections | section strategies | title |
|---|---|---|---|---|---|---|---|---|---|
| `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` | `sectionless_or_non_target_heading_format` | `weak_fulltext_or_metadata_only` | An open cavity formed with a photonic crystal of negative; Zhichao Ruan and Sailing He |  |  | An open cavity formed with a photonic crystal of negative refraction |
| `01KS5KVWY6VAA6HXWFJV2SXZ48` | photonic crystal cavity | `lineage_full_chain_missing` | `parser_success_primary` | `` | `local_cache_ingest_candidate` |  | conclusion | conclusion:explicit_heading,heading_continuation | Hybrid photonic crystal cavity and waveguide for coupling to diamond NV-centers |
| `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `current_contract_weak` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Ultra-bright source of polarization-entangled photons |
| `01KS6FC9FHZ35C2GEN43H8ZX7C` | photonic crystal cavity | `unattempted_pdf_available` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Transient chirp in high speed photonic crystal quantum dots lasers with controlled spontaneous emission |
| `01KS6FC9YY3YNHEN46P2ZPB6MA` | photonic crystal cavity | `unattempted_pdf_available` | `parser_no_target_sections` | `sectionless_or_non_target_heading_format` | `weak_fulltext_or_metadata_only` | A picogram and nanometer scale photonic crystal opto-mechanical cavity; California Institute of Technology, Pasadena, CA 91125 |  |  | A picogram and nanometer scale photonic crystal opto-mechanical cavity |
| `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` | `sectionless_or_non_target_heading_format` | `weak_fulltext_or_metadata_only` | All-optical conditional logic with a nonlinear photonic crystal nanocavity; School of Engineering and Applied Sciences, Harvard University, Cambridge, MA 02138 |  |  | All-optical conditional logic with a nonlinear photonic crystal nanocavity |
| `01KS6FFJF6XNCHFY2X589F6QD5` | photonic crystal cavity | `lineage_chains_missing_after_atoms` | `parser_success_primary` | `` | `local_cache_ingest_candidate` |  | conclusion | conclusion:explicit_heading,heading_continuation | Efficient Terahertz Generation in Triply Resonant Nonlinear Photonic Crystal Microcavities |
| `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `no_target_sections_after_current_parser` | `parser_no_target_sections` | `sectionless_or_non_target_heading_format` | `weak_fulltext_or_metadata_only` | Demonstration of an air-slot mode-gap confined photonic crystal; Optical Nanostructures Laboratory, Columbia University, New York, NY 10027 USA |  |  | Demonstration of an air-slot mode-gap confined photonic crystal slab nanocavity with ultrasmall mode volumes |
| `01KS5KVNQ1ZXKCB9HZVTBCE1MW` | metasurface holography | `unattempted_pdf_available` | `parser_no_target_sections` | `sectionless_or_non_target_heading_format` | `weak_fulltext_or_metadata_only` | Chapter 1; IMAGERY OF DIFFUSING MEDIA |  |  | Imagery of Diffusing Media by Heterodyne Holography |
| `01KS5KWR5AT8TAC98X5WRJNYT1` | photonic crystal cavity | `no_target_sections_unknown_contract` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Unidirectional light emission from high-Q modes in optical microcavities |
| `01KS6F6CER6Q6DCD2526C5P0F2` | photonic crystal cavity | `no_target_sections_unknown_contract` | `parser_success_weak_primary` | `` | `weak_primary_context_only` |  | conclusion | conclusion:terminal_cue_summary | Combining directional light output and ultralow loss in deformed microdisks |
| `01KS6F8QEVEAK2PYN62JJKAZVX` | metasurface holography | `unattempted_pdf_available` | `parser_no_target_sections` | `heading_like_but_not_target_section` | `heading_taxonomy_review` | Digital holography with ultimate sensitivity; We propose a variant of the heterodyne holography scheme, which combines the properties of |  |  | Digital holography with ultimate sensitivity |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens, metasurface holography, quantum light source | `decision_grade_current_contract` | `parser_success_primary` | `` | `already_covered_parser_control` |  | results | results:heading_continuation,inline_heading | Optical frequency comb generation from a monolithic microresonator |
| `01KS6F6SPEAWZCWHA3N8ZP4R4F` | quantum light source | `decision_grade_current_contract` | `parser_success_primary` | `` | `already_covered_parser_control` |  | experiments | experiments:heading_continuation,inline_heading | Coherent, multi-heterodyne spectroscopy using stabilized optical frequency combs |

## Policy

This is a read-only parser dry run. Rows with parser_success_primary and candidate_pool_only policy are local-cache candidates for the next safe Step5s ingest boundary; already-covered rows are useful parser controls but not counted as repair lift. Rows with parser_success_weak_primary are weak terminal-cue context only and remain blocked from decision-grade promotion. No row is promoted until paper_sections, section_atoms, and typed chains are rebuilt with provenance.
