# Topic-Gap Section Evidence Audit

- audit_ts: `2026-05-31T10:25:33Z`
- queue: `reports/v14b_pilot/multi_topic_evidence_gap_queue.csv`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `fail`
- decision-grade current-contract coverage: `43/78` (55.1%)
- promotion-ready coverage: `41/78` (52.6%)

## Failure Modes

| failure_mode | papers |
|---|---:|
| decision_grade_current_contract | 41 |
| no_target_sections_after_current_parser | 17 |
| unattempted_pdf_available | 8 |
| no_target_sections_unknown_contract | 5 |
| stale_parser_contract | 4 |
| lineage_full_chain_missing | 1 |
| current_contract_weak | 1 |
| lineage_chains_missing_after_atoms | 1 |

## Typed Chain Triage

| failure_mode | papers |
|---|---:|
| lineage_full_chain_missing | 1 |
| lineage_chains_missing_after_atoms | 1 |

| missing_stage | chains |
|---|---:|
| constraint | 1 |
| attempted_path | 1 |
| local_fix | 1 |

## Repair Contract Closure

- closed: `17/215` (7.9%)

| closure_state | contracts |
|---|---:|
| open_section_evidence_not_decision_grade | 120 |
| partial_chain_incomplete | 66 |
| closed_decision_grade_section | 16 |
| partial_atoms_available_no_chain | 12 |
| closed_typed_chain_available | 1 |

## Next Actions

| failure_mode | papers | action |
|---|---:|---|
| no_target_sections_after_current_parser | 17 | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| unattempted_pdf_available | 8 | run targeted topic-gap section ingest after active broad ingest is safe. |
| no_target_sections_unknown_contract | 5 | re-run with current parser contract before treating the miss as structural. |
| stale_parser_contract | 4 | reparse with the current section parser contract before evidence promotion. |
| lineage_full_chain_missing | 1 | inspect missing typed stages (constraint:1, attempted_path:1, local_fix:1) and improve atom classification/chain assembly for this bottleneck. |
| current_contract_weak | 1 | manual or alternate-parser review before high-confidence promotion. |
| lineage_chains_missing_after_atoms | 1 | run section-atom-chains or tune atom ordering before Step13 promotion. |

## Topic Coverage

| topic | papers | decision-grade | rate | top failure modes |
|---|---:|---:|---:|---|
| metalens | 20 | 14 | 70.0% | decision_grade_current_contract:14, no_target_sections_after_current_parser:5, stale_parser_contract:1 |
| metasurface holography | 25 | 14 | 56.0% | decision_grade_current_contract:14, no_target_sections_after_current_parser:3, unattempted_pdf_available:3 |
| photonic crystal cavity | 24 | 16 | 66.7% | decision_grade_current_contract:14, no_target_sections_after_current_parser:3, unattempted_pdf_available:3 |
| quantum light source | 33 | 22 | 66.7% | decision_grade_current_contract:22, no_target_sections_after_current_parser:7, unattempted_pdf_available:2 |

## Queued Papers

| pos | paper_id | topics | failure_mode | latest_attempt | title |
|---:|---|---|---|---|---|
| 1 | `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | An open cavity formed with a photonic crystal of negative refraction |
| 2 | `01KS5KVWY6VAA6HXWFJV2SXZ48` | photonic crystal cavity | `lineage_full_chain_missing` | `already_has_primary` | Hybrid photonic crystal cavity and waveguide for coupling to diamond NV-centers |
| 3 | `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `current_contract_weak` | `success_primary` | Ultra-bright source of polarization-entangled photons |
| 4 | `01KS6FC9FHZ35C2GEN43H8ZX7C` | photonic crystal cavity | `unattempted_pdf_available` | `not_attempted` | Transient chirp in high speed photonic crystal quantum dots lasers with controlled spontaneous emission |
| 5 | `01KS6FC9YY3YNHEN46P2ZPB6MA` | photonic crystal cavity | `unattempted_pdf_available` | `not_attempted` | A picogram and nanometer scale photonic crystal opto-mechanical cavity |
| 6 | `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | All-optical conditional logic with a nonlinear photonic crystal nanocavity |
| 7 | `01KS6GG3QQ4KDB4CAS1PMND5FV` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Scalable fiber integrated source for higher-dimensional path-entangled photonic quNits |
| 8 | `01KS6GND5KCR5HPW1YFZYW5ANY` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Characterization of a Quantum Light Source Based on Spontaneous Parametric Down-Conversion |
| 9 | `01KS6GQGRRD3AR4MY361CME1HG` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Two-color narrowband photon pair source with high brightness based on clustering in a monolithic waveguide resonator |
| 10 | `01KS6H23DPA3GB6AYCZYA8X08T` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Phonon-tuned bright single-photon source |
| 11 | `01KS6HJEXQGTKP950NRDA3CVT2` | metalens, metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | A Reconfigurable Active Huygens' Metalens |
| 12 | `01KS6HK2C4GYG2KSM1BA314XPY` | metasurface holography | `decision_grade_current_contract` | `success_primary` | Implementation of radiating aperture field distribution using tensorial metasurfaces |
| 13 | `01KS6FFJF6XNCHFY2X589F6QD5` | photonic crystal cavity | `lineage_chains_missing_after_atoms` | `already_has_primary` | Efficient Terahertz Generation in Triply Resonant Nonlinear Photonic Crystal Microcavities |
| 14 | `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Demonstration of an air-slot mode-gap confined photonic crystal slab nanocavity with ultrasmall mode volumes |
| 15 | `01KRCY44MWMZW2SYX8DPDD5N1G` | metasurface holography | `decision_grade_current_contract` | `success_primary` | Revealing the long-range coupling for multi-dimensional metasurface multiplexer |
| 16 | `01KRCY9W6P4V47CG5P522FKDM2` | metalens | `decision_grade_current_contract` | `success_primary` | Deep-learning-driven end-to-end metalens imaging |
| 17 | `01KRCYNPNPRZPNKDBEVR7MHQGY` | metalens | `decision_grade_current_contract` | `success_primary` | Deep-learning-enabled inverse design of large-scale metasurfaces with full-wave accuracy |
| 18 | `01KS5KJCBGJHW0SBAYKJNV7AXV` | metalens | `decision_grade_current_contract` | `success_primary` | Inverse designed metalenses with extended depth of focus |
| 19 | `01KS5KVNQ1ZXKCB9HZVTBCE1MW` | metasurface holography | `unattempted_pdf_available` | `not_attempted` | Imagery of Diffusing Media by Heterodyne Holography |
| 20 | `01KS5KWR5AT8TAC98X5WRJNYT1` | photonic crystal cavity | `no_target_sections_unknown_contract` | `no_target_sections` | Unidirectional light emission from high-Q modes in optical microcavities |
| 21 | `01KS6F6CER6Q6DCD2526C5P0F2` | photonic crystal cavity | `no_target_sections_unknown_contract` | `no_target_sections` | Combining directional light output and ultralow loss in deformed microdisks |
| 22 | `01KS6F8QEVEAK2PYN62JJKAZVX` | metasurface holography | `unattempted_pdf_available` | `not_attempted` | Digital holography with ultimate sensitivity |
| 23 | `01KS6FM0NPYW5AARJ2CBTGCY1Y` | quantum light source | `no_target_sections_unknown_contract` | `no_target_sections` | Multi-scale Optics for Enhanced Light Collection from a Point Source |
| 24 | `01KS6FQ0QWZMENZ0PDQJ2KMXC3` | photonic crystal cavity | `unattempted_pdf_available` | `not_attempted` | Deterministic integrated tuning of multi-cavity resonances and phase for slow-light in coupled photonic crystal cavities |
| 25 | `01KS6FQ18T1VR46Z69BXKVAYYJ` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Specular holography |
| 26 | `01KS6GE0HVC9YGPS7H9S0G3FXM` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Numerical heterodyne holography with two-dimensional photodetector arrays |
| 27 | `01KS6GW09MSPBB2H90HQYJ3JCK` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Near-unity coupling efficiency of a quantum emitter to a photonic-crystal waveguide |
| 28 | `01KS6GYEHTKSM99P2N7GPYZEX7` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Deterministic photon-emitter coupling in chiral photonic circuits |
| 29 | `01KS6H520F87MZXD1GH695W4F0` | metasurface holography | `unattempted_pdf_available` | `not_attempted` | Direct Inversion of Digital 3D Fraunhofer Holography Maps |
| 30 | `01KS6HGSMCY03E789TEE3B0FCT` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | A Dual Field-of-View Zoom Metalens |
| 31 | `01KS6HMZS9ACM80N6QJ22RAHGV` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Topology Optimized Multi-layered Meta-optics |
| 32 | `01KS6HPP3KS1MWWYWQ6GW64AV7` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Silicon nitride metalenses for unpolarized high-NA visible imaging |
| 33 | `01KS6HSYXF1CKNBRY6YP85WH87` | metalens, metasurface holography | `decision_grade_current_contract` | `success_primary` | Metasurface Optics for Full-color Computational Imaging |
| 34 | `01KS6HVY4CKH0GP6VQK7MXRXEK` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Solid-Immersion Metalenses for Infrared Focal Plane Arrays |
| 35 | `01KS6J1D349TJRE6H8JHY8EAR2` | photonic crystal cavity | `decision_grade_current_contract` | `success_primary` | Thermo-refractive noise in silicon nitride microresonators |
| 36 | `01KS6J46S3XN9VGZ83WRAPYB6P` | metasurface holography | `decision_grade_current_contract` | `success_primary` | Global optimization of dielectric metasurfaces using a physics-driven neural network |
| 37 | `01KS6JEPWST4RGHPNR4YHKEDEJ` | photonic crystal cavity | `decision_grade_current_contract` | `already_has_primary` | Tantala Kerr-nonlinear integrated photonics |
| 38 | `01KS6JHFY91AR59BAD4FWGN10A` | metasurface holography | `decision_grade_current_contract` | `success_primary` | Image transmission through a flexible multimode fiber by deep learning |
| 39 | `01KS6JK6A32S7KEBBJZ646VWJQ` | metalens | `decision_grade_current_contract` | `success_primary` | Large-scale parameterized metasurface design using adjoint optimization |
| 40 | `01KS6JNYQG06AWPKWZM8A0YKV4` | metasurface holography | `stale_parser_contract` | `not_attempted` | Addressable metasurfaces for dynamic holography and optical information encryption |
| 41 | `01KS6JQF1Z6S24T2QNHY86PME6` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Quantum holography with undetected light |
| 42 | `01KS6V3QKP3ARRQ6SND9DKZ7KW` | photonic crystal cavity | `decision_grade_current_contract` | `already_has_primary` | Observation of Temporal Reflections and Broadband Frequency Translations at Photonic Time-Interfaces |
| 43 | `01KS6V4QR92475GKNRP0STAXJB` | metalens | `decision_grade_current_contract` | `success_primary` | Arbitrary structured quantum emission with a multifunctional imaging metalens |
| 44 | `01KS6V9QJDHD8J1F96M20VQ0FT` | metasurface holography, photonic crystal cavity | `decision_grade_current_contract` | `success_primary` | Hybrid bound states in the continuum in terahertz metasurfaces |
| 45 | `01KS6VBZMHP7DCAGSHHDXAHRQ1` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `success_primary` | Parametrically driven pure-Kerr temporal solitons in a chip-integrated microcavity |
| 46 | `01KS6VC0TXWGM4M7Y1ZM55TE5R` | quantum light source | `decision_grade_current_contract` | `success_primary` | Spectral-temporal-spatial customization via modulating multimodal nonlinear pulse propagation |
| 47 | `01KS6VCY969FNTVD1590J5JCF6` | photonic crystal cavity | `decision_grade_current_contract` | `already_has_primary` | Programmable Integrated Photonics for Topological Hamiltonians |
| 48 | `01KS6VD2S4WZB2WN3FF8SJ7VT4` | metasurface holography | `stale_parser_contract` | `already_has_primary` | Electrochemically-controlled metasurfaces with high-contrast switching at visible frequencies |
| 49 | `01KS6VD3391WKPAQ70D3078XB8` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `already_has_primary` | GaAs nano-ridge laser diodes fully fabricated in a 300 mm CMOS pilot line |
| 50 | `01KS6VD3NAZ5E6GXMPNANGG8EK` | metalens, metasurface holography, photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `success_primary` | Broadband Thermal Imaging using Meta-Optics |

## Promotion Policy

Benchmark-topic papers below the decision-grade current-contract threshold must stay out of high-confidence Topic Dossier, bottleneck lineage, and Radar Claim Card promotion.
