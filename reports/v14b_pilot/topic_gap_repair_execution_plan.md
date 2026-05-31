# Topic-Gap Repair Execution Plan

- plan_ts: `2026-05-31T11:42:06Z`
- source_triage: `reports/v14b_pilot/topic_gap_section_evidence_audit.json`
- status: `ready`
- contracts: `215`; papers: `78`
- quick-close contracts: `12`
- local raw-PDF ingest contracts: `52`

## Execution Contract

- Section atomization is deterministic/rules-first and traceable to PDF page/span.
- Exact search is hard retrieval evidence; fuzzy embedding search is candidate recall only.
- Graph/GNN expansion may rank or widen candidates only; it cannot create atoms or promote claims.
- Step5c/Step13 Claim Card gates control promotion.

## Action Groups

| group | contracts | papers | missing stages | command sequence |
|---|---:|---:|---|---|
| rebuild_section_atom_chains_quick_close | 12 | 8 | - | `make section-atom-chains`<br>`make topic-gap-section-audit`<br>`make topic-gap-repair-plan` |
| targeted_local_raw_pdf_ingest_when_safe | 52 | 16 | - | `python scripts/guard_topic_gap_repair.py`<br>`make section-evidence-topic-gaps-local`<br>`make section-atoms`<br>`make section-atom-embeddings`<br>`make section-embeddings`<br>`make section-atom-chains`<br>`make topic-gap-section-audit`<br>`make topic-gap-repair-plan` |
| inspect_typed_chain_stage_gaps | 68 | 33 | new_constraint:220, local_fix:180, failure_mechanism:124, attempted_path:94, constraint:56 | `make topic-gap-stage-candidate-recall`<br>`inspect missing chain stages in reports/v14b_pilot/topic_gap_section_evidence_audit.csv`<br>`make section-atoms`<br>`make section-embeddings`<br>`make section-atom-chains`<br>`make topic-gap-section-audit`<br>`make topic-gap-repair-plan` |
| inspect_current_parser_no_target | 66 | 17 | - | `make topic-gap-no-target-inspect`<br>`make topic-gap-repair-plan` |
| closed_waiting_step13_gate | 17 | 13 | - | `make post-frontfill-chain`<br>`make direction-readiness-audit`<br>`make value-delivery-audit` |

## Top Examples

### rebuild_section_atom_chains_quick_close

- policy: `no_direct_promotion`; claim_scope: `evidence_repair_queue_only`

| paper_id | topic | closure_state | failure_mode | missing_stages | next_action |
|---|---|---|---|---|---|
| `01KS6HK2C4GYG2KSM1BA314XPY` | metasurface holography | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6FFJF6XNCHFY2X589F6QD5` | photonic crystal cavity | `partial_atoms_available_no_chain` | `lineage_chains_missing_after_atoms` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6JEPWST4RGHPNR4YHKEDEJ` | photonic crystal cavity | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6VGWRXZH3F6ANJ253V64HF` | metasurface holography | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metasurface holography | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | quantum light source | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6GKPAZPCBT8T8BN9FCY29H` | metalens | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6GKPAZPCBT8T8BN9FCY29H` | metasurface holography | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |
| `01KS6GKPAZPCBT8T8BN9FCY29H` | quantum light source | `partial_atoms_available_no_chain` | `decision_grade_current_contract` | - | run section-atom-chains for this repair contract before Step13 promotion. |

### targeted_local_raw_pdf_ingest_when_safe

- policy: `no_direct_promotion`; claim_scope: `evidence_repair_queue_only`

| paper_id | topic | closure_state | failure_mode | missing_stages | next_action |
|---|---|---|---|---|---|
| `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `open_section_evidence_not_decision_grade` | `current_contract_weak` | - | manual or alternate-parser review before high-confidence promotion. |
| `01KS6FC9FHZ35C2GEN43H8ZX7C` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `unattempted_pdf_available` | - | run targeted topic-gap section ingest after active broad ingest is safe. |
| `01KS6FC9YY3YNHEN46P2ZPB6MA` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `unattempted_pdf_available` | - | run targeted topic-gap section ingest after active broad ingest is safe. |
| `01KS6GG3QQ4KDB4CAS1PMND5FV` | quantum light source | `open_section_evidence_not_decision_grade` | `unattempted_pdf_available` | - | run targeted topic-gap section ingest after active broad ingest is safe. |
| `01KS6GQGRRD3AR4MY361CME1HG` | quantum light source | `open_section_evidence_not_decision_grade` | `unattempted_pdf_available` | - | run targeted topic-gap section ingest after active broad ingest is safe. |
| `01KS5KVNQ1ZXKCB9HZVTBCE1MW` | metasurface holography | `open_section_evidence_not_decision_grade` | `unattempted_pdf_available` | - | run targeted topic-gap section ingest after active broad ingest is safe. |
| `01KS5KWR5AT8TAC98X5WRJNYT1` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `no_target_sections_unknown_contract` | - | re-run with current parser contract before treating the miss as structural. |
| `01KS6F6CER6Q6DCD2526C5P0F2` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `no_target_sections_unknown_contract` | - | re-run with current parser contract before treating the miss as structural. |
| `01KS6F8QEVEAK2PYN62JJKAZVX` | metasurface holography | `open_section_evidence_not_decision_grade` | `unattempted_pdf_available` | - | run targeted topic-gap section ingest after active broad ingest is safe. |
| `01KS6FM0NPYW5AARJ2CBTGCY1Y` | quantum light source | `open_section_evidence_not_decision_grade` | `no_target_sections_unknown_contract` | - | re-run with current parser contract before treating the miss as structural. |

### inspect_typed_chain_stage_gaps

- policy: `no_direct_promotion`; claim_scope: `evidence_repair_queue_only`

| paper_id | topic | closure_state | failure_mode | missing_stages | next_action |
|---|---|---|---|---|---|
| `01KS5KVWY6VAA6HXWFJV2SXZ48` | photonic crystal cavity | `partial_chain_incomplete` | `lineage_full_chain_missing` | constraint:1, attempted_path:1, local_fix:1 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KRCY44MWMZW2SYX8DPDD5N1G` | metasurface holography | `partial_chain_incomplete` | `decision_grade_current_contract` | constraint:3, local_fix:3, new_constraint:3 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KRCY9W6P4V47CG5P522FKDM2` | metalens | `partial_chain_incomplete` | `decision_grade_current_contract` | local_fix:4, attempted_path:3, failure_mechanism:2, new_constraint:2 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KRCYNPNPRZPNKDBEVR7MHQGY` | metalens | `partial_chain_incomplete` | `decision_grade_current_contract` | attempted_path:1, local_fix:1, new_constraint:1 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KS5KJCBGJHW0SBAYKJNV7AXV` | metalens | `partial_chain_incomplete` | `decision_grade_current_contract` | constraint:1, new_constraint:1 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KS6HSYXF1CKNBRY6YP85WH87` | metalens | `partial_chain_incomplete` | `decision_grade_current_contract` | failure_mechanism:5, attempted_path:4, new_constraint:4, local_fix:1 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KS6HSYXF1CKNBRY6YP85WH87` | metasurface holography | `partial_chain_incomplete` | `decision_grade_current_contract` | failure_mechanism:5, attempted_path:4, new_constraint:4, local_fix:1 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KS6J1D349TJRE6H8JHY8EAR2` | photonic crystal cavity | `partial_chain_incomplete` | `decision_grade_current_contract` | attempted_path:3, local_fix:3 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KS6J46S3XN9VGZ83WRAPYB6P` | metasurface holography | `partial_chain_incomplete` | `decision_grade_current_contract` | local_fix:5, new_constraint:5, failure_mechanism:3, constraint:2 | inspect missing typed stages and improve chain completeness for this repair contract. |
| `01KS6JK6A32S7KEBBJZ646VWJQ` | metalens | `partial_chain_incomplete` | `decision_grade_current_contract` | failure_mechanism:3, local_fix:3, new_constraint:3 | inspect missing typed stages and improve chain completeness for this repair contract. |

### inspect_current_parser_no_target

- policy: `no_direct_promotion`; claim_scope: `evidence_repair_queue_only`

| paper_id | topic | closure_state | failure_mode | missing_stages | next_action |
|---|---|---|---|---|---|
| `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6GND5KCR5HPW1YFZYW5ANY` | quantum light source | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6H23DPA3GB6AYCZYA8X08T` | quantum light source | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6HJEXQGTKP950NRDA3CVT2` | metalens | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6HJEXQGTKP950NRDA3CVT2` | metasurface holography | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6FQ18T1VR46Z69BXKVAYYJ` | metasurface holography | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6GE0HVC9YGPS7H9S0G3FXM` | metasurface holography | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| `01KS6GW09MSPBB2H90HQYJ3JCK` | quantum light source | `open_section_evidence_not_decision_grade` | `no_target_sections_after_current_parser` | - | inspect parser misses or alternate full text; keep abstract-only claims weak. |

### closed_waiting_step13_gate

- policy: `no_direct_promotion`; claim_scope: `evidence_repair_queue_only`

| paper_id | topic | closure_state | failure_mode | missing_stages | next_action |
|---|---|---|---|---|---|
| `01KS6HK2C4GYG2KSM1BA314XPY` | metasurface holography | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6JHFY91AR59BAD4FWGN10A` | metasurface holography | `closed_typed_chain_available` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | metasurface holography | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6F5Z1F33SR77NWE7BDK2J0` | quantum light source | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6F6SPEAWZCWHA3N8ZP4R4F` | quantum light source | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6G8NM22XMZXQP6ADT1BKTB` | quantum light source | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6GKPAZPCBT8T8BN9FCY29H` | metalens | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6GKPAZPCBT8T8BN9FCY29H` | metasurface holography | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |
| `01KS6GKPAZPCBT8T8BN9FCY29H` | quantum light source | `closed_decision_grade_section` | `decision_grade_current_contract` | - | repair contract evidence substrate is available; Step13/Claim Card gates still control promotion. |

## Forbidden Shortcuts

- do not use GNN/VGAE to create section atoms
- do not loosen parser thresholds for current-parser no-target rows without inspection
- do not treat fuzzy vector recall as a conclusion
- do not mark Radar or high-confidence Claim Cards without Step13 gates
