# Topic-Gap Section Evidence Audit

- audit_ts: `2026-05-31T05:46:21Z`
- queue: `reports/v14b_pilot/multi_topic_evidence_gap_queue.csv`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `fail`
- decision-grade current-contract coverage: `16/38` (42.1%)
- promotion-ready coverage: `14/38` (36.8%)

## Failure Modes

| failure_mode | papers |
|---|---:|
| no_target_sections_after_current_parser | 18 |
| decision_grade_current_contract | 14 |
| current_contract_weak | 4 |
| lineage_full_chain_missing | 1 |
| lineage_chains_missing_after_atoms | 1 |

## Typed Chain Triage

| failure_mode | papers |
|---|---:|
| lineage_full_chain_missing | 1 |
| lineage_chains_missing_after_atoms | 1 |

## Next Actions

| failure_mode | papers | action |
|---|---:|---|
| no_target_sections_after_current_parser | 18 | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| current_contract_weak | 4 | manual or alternate-parser review before high-confidence promotion. |
| lineage_full_chain_missing | 1 | inspect missing typed stages and improve atom classification/chain assembly for this bottleneck. |
| lineage_chains_missing_after_atoms | 1 | run section-atom-chains or tune atom ordering before Step13 promotion. |

## Topic Coverage

| topic | papers | decision-grade | rate | top failure modes |
|---|---:|---:|---:|---|
| metalens | 9 | 4 | 44.4% | no_target_sections_after_current_parser:5, decision_grade_current_contract:4 |
| metasurface holography | 8 | 4 | 50.0% | no_target_sections_after_current_parser:4, decision_grade_current_contract:4 |
| photonic crystal cavity | 8 | 2 | 25.0% | no_target_sections_after_current_parser:3, current_contract_weak:3, lineage_full_chain_missing:1 |
| quantum light source | 20 | 12 | 60.0% | decision_grade_current_contract:12, no_target_sections_after_current_parser:7, current_contract_weak:1 |

## Queued Papers

| pos | paper_id | topics | failure_mode | latest_attempt | title |
|---:|---|---|---|---|---|
| 1 | `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | An open cavity formed with a photonic crystal of negative refraction |
| 2 | `01KS5KM369VWG4F2AV2MS14S3E` | photonic crystal cavity | `current_contract_weak` | `success_primary` | Surface state photonic bandgap cavities |
| 3 | `01KS5KMDAC6220S2FEJCB6XVTB` | photonic crystal cavity | `current_contract_weak` | `success_primary` | Silicon-based photonic crystal nanocavity light emitters |
| 4 | `01KS5KVWY6VAA6HXWFJV2SXZ48` | photonic crystal cavity | `lineage_full_chain_missing` | `already_has_primary` | Hybrid photonic crystal cavity and waveguide for coupling to diamond NV-centers |
| 5 | `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `current_contract_weak` | `success_primary` | Ultra-bright source of polarization-entangled photons |
| 6 | `01KS5KWKMCV3DHKBFJH2Z0JN6A` | photonic crystal cavity | `current_contract_weak` | `success_primary` | Fabrication-tolerant high quality factor photonic crystal microcavities |
| 7 | `01KS6FFJF6XNCHFY2X589F6QD5` | photonic crystal cavity | `lineage_chains_missing_after_atoms` | `already_has_primary` | Efficient Terahertz Generation in Triply Resonant Nonlinear Photonic Crystal Microcavities |
| 8 | `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | All-optical conditional logic with a nonlinear photonic crystal nanocavity |
| 9 | `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Demonstration of an air-slot mode-gap confined photonic crystal slab nanocavity with ultrasmall mode volumes |
| 10 | `01KS6FK557AWZRGP7QFMMBVT17` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Quantum interface between frequency-uncorrelated down-converted entanglement and atomic-ensemble quantum memory |
| 11 | `01KS6GKT1AN2MQ1NXP1ZJY5EKA` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Ultra-broadband continuously-tunable polarization entangled photon pair source covering the C+L telecom bands based on a single type-II PPKTP crystal |
| 12 | `01KS6GND5KCR5HPW1YFZYW5ANY` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Characterization of a Quantum Light Source Based on Spontaneous Parametric Down-Conversion |
| 13 | `01KS6H25PCS743PEWJ8HF8YGEH` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Tunable narrow band source via the strong coupling between optical emitter and nanowire surface plasmons |
| 14 | `01KS6FQ18T1VR46Z69BXKVAYYJ` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Specular holography |
| 15 | `01KS6GE0HVC9YGPS7H9S0G3FXM` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Numerical heterodyne holography with two-dimensional photodetector arrays |
| 16 | `01KS6GW09MSPBB2H90HQYJ3JCK` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Near-unity coupling efficiency of a quantum emitter to a photonic-crystal waveguide |
| 17 | `01KS6GYEHTKSM99P2N7GPYZEX7` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Deterministic photon-emitter coupling in chiral photonic circuits |
| 18 | `01KS6HEPDK5G604MQCB4RTXK57` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Chiral Quantum Optics |
| 19 | `01KS6HGSMCY03E789TEE3B0FCT` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | A Dual Field-of-View Zoom Metalens |
| 20 | `01KS6HJEXQGTKP950NRDA3CVT2` | metalens, metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | A Reconfigurable Active Huygens' Metalens |
| 21 | `01KS6HMZS9ACM80N6QJ22RAHGV` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Topology Optimized Multi-layered Meta-optics |
| 22 | `01KS6HNKKTN0P5DTSRMS86C3GR` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Generating Spatial Spectrum with Metasurfaces |
| 23 | `01KS6HPP3KS1MWWYWQ6GW64AV7` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Silicon nitride metalenses for unpolarized high-NA visible imaging |
| 24 | `01KS6HVY4CKH0GP6VQK7MXRXEK` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Solid-Immersion Metalenses for Infrared Focal Plane Arrays |
| 25 | `01KS6F5Z1F33SR77NWE7BDK2J0` | metalens, metasurface holography, quantum light source | `decision_grade_current_contract` | `success_primary` | Optical frequency comb generation from a monolithic microresonator |
| 26 | `01KS6F6SPEAWZCWHA3N8ZP4R4F` | quantum light source | `decision_grade_current_contract` | `success_primary` | Coherent, multi-heterodyne spectroscopy using stabilized optical frequency combs |
| 27 | `01KS6G8NM22XMZXQP6ADT1BKTB` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Generation of Ultrastable Microwaves via Optical Frequency Division |
| 28 | `01KS6GKPAZPCBT8T8BN9FCY29H` | metalens, metasurface holography, quantum light source | `decision_grade_current_contract` | `already_has_primary` | Temporal solitons in optical microresonators |
| 29 | `01KS6GKQK1Y4S7EMFB2FR9H48M` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Modeling of octave-spanning Kerr frequency combs using a generalized mean-field Lugiato-Lefever model |
| 30 | `01KS6GX5A2SX4R0K9P0QNGX9T1` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Mode interaction aided excitation of dark solitons in microresonators constructed of normal dispersion waveguides |
| 31 | `01KS6HE5D5W71A1GB9G2MXXT75` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Microresonator Soliton Dual-Comb Spectroscopy |
| 32 | `01KS6HFYZKZMKPZ083T1KHNKNW` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Soliton crystals in Kerr resonators |
| 33 | `01KS6HG0RZ7V2A8B99JZ78CD9R` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Microresonator solitons for massively parallel coherent optical communications |
| 34 | `01KS6HP5WF1X9FFFCHTFYBGTGB` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | An Integrated-Photonics Optical-Frequency Synthesizer |
| 35 | `01KS6HRQRDVDHA23NJYK7V3X12` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Monolithic Ultrahigh-Q Lithium Niobate Microring Resonator |
| 36 | `01KS6HYJXAN3K8BMTS1K2R6PDB` | quantum light source | `decision_grade_current_contract` | `already_has_primary` | Broadband electro-optic frequency comb generation in an integrated microring resonator |
| 37 | `01KS6JAG0F75K83A2GANBQXPHF` | metalens, metasurface holography | `decision_grade_current_contract` | `already_has_primary` | Parallel convolution processing using an integrated photonic tensor core |
| 38 | `01KS6JHJDZQ233PSMCNT7S0T2N` | metalens, metasurface holography | `decision_grade_current_contract` | `already_has_primary` | 11 TeraFLOPs per second photonic convolutional accelerator for deep learning optical neural networks |

## Promotion Policy

Benchmark-topic papers below the decision-grade current-contract threshold must stay out of high-confidence Topic Dossier, bottleneck lineage, and Radar Claim Card promotion.
