# Topic-Gap Section Evidence Audit

- audit_ts: `2026-05-31T04:12:23Z`
- queue: `reports/v14b_pilot/multi_topic_evidence_gap_queue.csv`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `fail`
- decision-grade current-contract coverage: `23/47` (48.9%)
- promotion-ready coverage: `11/47` (23.4%)

## Failure Modes

| failure_mode | papers |
|---|---:|
| no_target_sections_after_current_parser | 22 |
| decision_grade_current_contract | 11 |
| lineage_chains_missing_after_atoms | 5 |
| lineage_full_chain_missing | 4 |
| lineage_atoms_missing_after_section_evidence | 3 |
| unattempted_pdf_available | 2 |

## Typed Chain Triage

| failure_mode | papers |
|---|---:|
| lineage_chains_missing_after_atoms | 5 |
| lineage_full_chain_missing | 4 |
| lineage_atoms_missing_after_section_evidence | 3 |

## Next Actions

| failure_mode | papers | action |
|---|---:|---|
| no_target_sections_after_current_parser | 22 | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| lineage_chains_missing_after_atoms | 5 | run section-atom-chains or tune atom ordering before Step13 promotion. |
| lineage_full_chain_missing | 4 | inspect missing typed stages and improve atom classification/chain assembly for this bottleneck. |
| lineage_atoms_missing_after_section_evidence | 3 | run section-atoms for topic-gap papers, then rebuild section-atom chains. |
| unattempted_pdf_available | 2 | run targeted topic-gap section ingest after active broad ingest is safe. |

## Topic Coverage

| topic | papers | decision-grade | rate | top failure modes |
|---|---:|---:|---:|---|
| metalens | 12 | 7 | 58.3% | no_target_sections_after_current_parser:5, decision_grade_current_contract:4, lineage_full_chain_missing:3 |
| metasurface holography | 12 | 8 | 66.7% | no_target_sections_after_current_parser:4, lineage_chains_missing_after_atoms:4, decision_grade_current_contract:4 |
| photonic crystal cavity | 20 | 11 | 55.0% | no_target_sections_after_current_parser:9, decision_grade_current_contract:9, lineage_full_chain_missing:1 |
| quantum light source | 22 | 12 | 54.5% | decision_grade_current_contract:9, no_target_sections_after_current_parser:8, lineage_atoms_missing_after_section_evidence:3 |

## Queued Papers

| pos | paper_id | topics | failure_mode | latest_attempt | title |
|---:|---|---|---|---|---|
| 1 | `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | An open cavity formed with a photonic crystal of negative refraction |
| 2 | `01KS5KM369VWG4F2AV2MS14S3E` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Surface state photonic bandgap cavities |
| 3 | `01KS5KMDAC6220S2FEJCB6XVTB` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Silicon-based photonic crystal nanocavity light emitters |
| 4 | `01KS5KVWY6VAA6HXWFJV2SXZ48` | photonic crystal cavity | `lineage_full_chain_missing` | `success_primary` | Hybrid photonic crystal cavity and waveguide for coupling to diamond NV-centers |
| 5 | `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Ultra-bright source of polarization-entangled photons |
| 6 | `01KS5KWKMCV3DHKBFJH2Z0JN6A` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Fabrication-tolerant high quality factor photonic crystal microcavities |
| 7 | `01KS6FFJF6XNCHFY2X589F6QD5` | photonic crystal cavity | `lineage_chains_missing_after_atoms` | `success_primary` | Efficient Terahertz Generation in Triply Resonant Nonlinear Photonic Crystal Microcavities |
| 8 | `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | All-optical conditional logic with a nonlinear photonic crystal nanocavity |
| 9 | `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Demonstration of an air-slot mode-gap confined photonic crystal slab nanocavity with ultrasmall mode volumes |
| 10 | `01KS6FK557AWZRGP7QFMMBVT17` | quantum light source | `lineage_atoms_missing_after_section_evidence` | `success_primary` | Quantum interface between frequency-uncorrelated down-converted entanglement and atomic-ensemble quantum memory |
| 11 | `01KS6GKT1AN2MQ1NXP1ZJY5EKA` | quantum light source | `lineage_atoms_missing_after_section_evidence` | `success_primary` | Ultra-broadband continuously-tunable polarization entangled photon pair source covering the C+L telecom bands based on a single type-II PPKTP crystal |
| 12 | `01KS6GND5KCR5HPW1YFZYW5ANY` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Characterization of a Quantum Light Source Based on Spontaneous Parametric Down-Conversion |
| 13 | `01KS6H25PCS743PEWJ8HF8YGEH` | quantum light source | `lineage_atoms_missing_after_section_evidence` | `success_primary` | Tunable narrow band source via the strong coupling between optical emitter and nanowire surface plasmons |
| 14 | `01KS5KJ583SB217NBQYZSWC42R` | metalens | `lineage_full_chain_missing` | `success_primary` | Metalens With Artificial Focus Pattern |
| 15 | `01KS6FNC3F3SNBJ0QH1E8PRPRV` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Classification of light sources and their interaction with active and passive environments |
| 16 | `01KS6FQ18T1VR46Z69BXKVAYYJ` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Specular holography |
| 17 | `01KS6GE0HVC9YGPS7H9S0G3FXM` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Numerical heterodyne holography with two-dimensional photodetector arrays |
| 18 | `01KS6GG3QQ4KDB4CAS1PMND5FV` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Scalable fiber integrated source for higher-dimensional path-entangled photonic quNits |
| 19 | `01KS6GH1AHNF1EQ3V7VRZ28RPP` | metasurface holography | `lineage_chains_missing_after_atoms` | `success_primary` | Exploring shot noise and Laser Doppler imagery with heterodyne holography |
| 20 | `01KS6HDG6MYN3Y7HPYW7KRRKQJ` | metalens | `lineage_full_chain_missing` | `success_primary` | Broadband Multifocal Conic-Shaped Metalens |
| 21 | `01KS6HGSMCY03E789TEE3B0FCT` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | A Dual Field-of-View Zoom Metalens |
| 22 | `01KS6HJEXQGTKP950NRDA3CVT2` | metalens, metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | A Reconfigurable Active Huygens' Metalens |
| 23 | `01KS6HK2C4GYG2KSM1BA314XPY` | metasurface holography | `lineage_chains_missing_after_atoms` | `success_primary` | Implementation of radiating aperture field distribution using tensorial metasurfaces |
| 24 | `01KS6HMZS9ACM80N6QJ22RAHGV` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Topology Optimized Multi-layered Meta-optics |
| 25 | `01KS6HNKKTN0P5DTSRMS86C3GR` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Generating Spatial Spectrum with Metasurfaces |
| 26 | `01KS6HPP3KS1MWWYWQ6GW64AV7` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Silicon nitride metalenses for unpolarized high-NA visible imaging |
| 27 | `01KS6HR11SMNBNHF2EH7HQD1B8` | metasurface holography | `lineage_chains_missing_after_atoms` | `success_primary` | Designing high-transmission and wide angle all-dielectric flat metasurfaces at telecom wavelengths |
| 28 | `01KS6HX81HS8PYCYKDM0Z285J8` | metasurface holography | `lineage_chains_missing_after_atoms` | `success_primary` | Direct phase mapping of broadband Laguerre-Gaussian metasurfaces |
| 29 | `01KS6J1DE5H1JYZ15HXF8CC6CF` | metalens | `lineage_full_chain_missing` | `success_primary` | Near-IR wide field-of-view Huygens metalens for outdoor imaging applications |
| 30 | `01KS6GW09MSPBB2H90HQYJ3JCK` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Near-unity coupling efficiency of a quantum emitter to a photonic-crystal waveguide |
| 31 | `01KS6GYEHTKSM99P2N7GPYZEX7` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Deterministic photon-emitter coupling in chiral photonic circuits |
| 32 | `01KS6HEPDK5G604MQCB4RTXK57` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Chiral Quantum Optics |
| 33 | `01KS6HVY4CKH0GP6VQK7MXRXEK` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Solid-Immersion Metalenses for Infrared Focal Plane Arrays |
| 34 | `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens, metasurface holography, photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `already_has_primary` | Optical frequency comb generation from a monolithic microresonator |
| 35 | `01KS6F6SPEAWZCWHA3N8ZP4R4F` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `success_primary` | Coherent, multi-heterodyne spectroscopy using stabilized optical frequency combs |
| 36 | `01KS6G8NM22XMZXQP6ADT1BKTB` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `success_primary` | Generation of Ultrastable Microwaves via Optical Frequency Division |
| 37 | `01KS6GKPAZPCBT8T8BN9FCY29H` | metalens, metasurface holography, photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `already_has_primary` | Temporal solitons in optical microresonators |
| 38 | `01KS6GKQK1Y4S7EMFB2FR9H48M` | photonic crystal cavity, quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Modeling of octave-spanning Kerr frequency combs using a generalized mean-field Lugiato-Lefever model |
| 39 | `01KS6GX5A2SX4R0K9P0QNGX9T1` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `already_has_primary` | Mode interaction aided excitation of dark solitons in microresonators constructed of normal dispersion waveguides |
| 40 | `01KS6HE5D5W71A1GB9G2MXXT75` | photonic crystal cavity, quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Microresonator Soliton Dual-Comb Spectroscopy |
| 41 | `01KS6HFYZKZMKPZ083T1KHNKNW` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `success_primary` | Soliton crystals in Kerr resonators |
| 42 | `01KS6HG0RZ7V2A8B99JZ78CD9R` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `already_has_primary` | Microresonator solitons for massively parallel coherent optical communications |
| 43 | `01KS6HP5WF1X9FFFCHTFYBGTGB` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `already_has_primary` | An Integrated-Photonics Optical-Frequency Synthesizer |
| 44 | `01KS6HRQRDVDHA23NJYK7V3X12` | photonic crystal cavity, quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Monolithic Ultrahigh-Q Lithium Niobate Microring Resonator |
| 45 | `01KS6HYJXAN3K8BMTS1K2R6PDB` | photonic crystal cavity, quantum light source | `decision_grade_current_contract` | `success_primary` | Broadband electro-optic frequency comb generation in an integrated microring resonator |
| 46 | `01KS6JAG0F75K83A2GANBQXPHF` | metalens, metasurface holography | `decision_grade_current_contract` | `success_primary` | Parallel convolution processing using an integrated photonic tensor core |
| 47 | `01KS6JHJDZQ233PSMCNT7S0T2N` | metalens, metasurface holography | `decision_grade_current_contract` | `success_primary` | 11 TeraFLOPs per second photonic convolutional accelerator for deep learning optical neural networks |

## Promotion Policy

Benchmark-topic papers below the decision-grade current-contract threshold must stay out of high-confidence Topic Dossier, bottleneck lineage, and Radar Claim Card promotion.
