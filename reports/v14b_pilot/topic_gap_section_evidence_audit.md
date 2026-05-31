# Topic-Gap Section Evidence Audit

- audit_ts: `2026-05-31T00:42:42Z`
- queue: `data/v14b/topic_evidence_gap_delta_queue.csv`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `fail`
- decision-grade current-contract coverage: `0/31` (0.0%)

## Failure Modes

| failure_mode | papers |
|---|---:|
| no_target_sections_after_current_parser | 22 |
| stale_parser_contract | 6 |
| unattempted_pdf_available | 3 |

## Next Actions

| failure_mode | papers | action |
|---|---:|---|
| no_target_sections_after_current_parser | 22 | inspect parser misses or alternate full text; keep abstract-only claims weak. |
| stale_parser_contract | 6 | reparse with the current section parser contract before evidence promotion. |
| unattempted_pdf_available | 3 | run targeted topic-gap section ingest after active broad ingest is safe. |

## Topic Coverage

| topic | papers | decision-grade | rate | top failure modes |
|---|---:|---:|---:|---|
| metalens | 7 | 0 | 0.0% | no_target_sections_after_current_parser:5, stale_parser_contract:2 |
| metasurface holography | 6 | 0 | 0.0% | no_target_sections_after_current_parser:4, stale_parser_contract:2 |
| photonic crystal cavity | 11 | 0 | 0.0% | no_target_sections_after_current_parser:9, stale_parser_contract:2 |
| quantum light source | 11 | 0 | 0.0% | no_target_sections_after_current_parser:8, unattempted_pdf_available:3 |

## Queued Papers

| pos | paper_id | topics | failure_mode | latest_attempt | title |
|---:|---|---|---|---|---|
| 1 | `01KS6HE5D5W71A1GB9G2MXXT75` | photonic crystal cavity, quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Microresonator Soliton Dual-Comb Spectroscopy |
| 2 | `01KS6GKQK1Y4S7EMFB2FR9H48M` | photonic crystal cavity, quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Modeling of octave-spanning Kerr frequency combs using a generalized mean-field Lugiato-Lefever model |
| 3 | `01KS6HRQRDVDHA23NJYK7V3X12` | photonic crystal cavity, quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Monolithic Ultrahigh-Q Lithium Niobate Microring Resonator |
| 4 | `01KS5KVWY6VAA6HXWFJV2SXZ48` | photonic crystal cavity | `stale_parser_contract` | `success_primary` | Hybrid photonic crystal cavity and waveguide for coupling to diamond NV-centers |
| 5 | `01KS5KMDAC6220S2FEJCB6XVTB` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Silicon-based photonic crystal nanocavity light emitters |
| 6 | `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | An open cavity formed with a photonic crystal of negative refraction |
| 7 | `01KS5KM369VWG4F2AV2MS14S3E` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Surface state photonic bandgap cavities |
| 8 | `01KS5KWKMCV3DHKBFJH2Z0JN6A` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Fabrication-tolerant high quality factor photonic crystal microcavities |
| 9 | `01KS6HJEXQGTKP950NRDA3CVT2` | metalens, metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | A Reconfigurable Active Huygens' Metalens |
| 10 | `01KS6GYEHTKSM99P2N7GPYZEX7` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Deterministic photon-emitter coupling in chiral photonic circuits |
| 11 | `01KS6HEPDK5G604MQCB4RTXK57` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Chiral Quantum Optics |
| 12 | `01KS6GW09MSPBB2H90HQYJ3JCK` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Near-unity coupling efficiency of a quantum emitter to a photonic-crystal waveguide |
| 13 | `01KS6HMZS9ACM80N6QJ22RAHGV` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Topology Optimized Multi-layered Meta-optics |
| 14 | `01KS6HNKKTN0P5DTSRMS86C3GR` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Generating Spatial Spectrum with Metasurfaces |
| 15 | `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | Demonstration of an air-slot mode-gap confined photonic crystal slab nanocavity with ultrasmall mode volumes |
| 16 | `01KS6HVAB876FC1S19KQ8ZP1G5` | metalens | `stale_parser_contract` | `success_primary` | An Ultra-high Numerical Aperture Metalens at Visible Wavelengths |
| 17 | `01KS6GND5KCR5HPW1YFZYW5ANY` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Characterization of a Quantum Light Source Based on Spontaneous Parametric Down-Conversion |
| 18 | `01KS6FK557AWZRGP7QFMMBVT17` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Quantum interface between frequency-uncorrelated down-converted entanglement and atomic-ensemble quantum memory |
| 19 | `01KS6GKT1AN2MQ1NXP1ZJY5EKA` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Ultra-broadband continuously-tunable polarization entangled photon pair source covering the C+L telecom bands based on a single type-II PPKTP crystal |
| 20 | `01KS6H25PCS743PEWJ8HF8YGEH` | quantum light source | `unattempted_pdf_available` | `not_attempted` | Tunable narrow band source via the strong coupling between optical emitter and nanowire surface plasmons |
| 21 | `01KS6HGSMCY03E789TEE3B0FCT` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | A Dual Field-of-View Zoom Metalens |
| 22 | `01KS6HPP3KS1MWWYWQ6GW64AV7` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Silicon nitride metalenses for unpolarized high-NA visible imaging |
| 23 | `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `no_target_sections_after_current_parser` | `no_target_sections` | Ultra-bright source of polarization-entangled photons |
| 24 | `01KS6HDG6MYN3Y7HPYW7KRRKQJ` | metalens | `stale_parser_contract` | `success_primary` | Broadband Multifocal Conic-Shaped Metalens |
| 25 | `01KS6HX81HS8PYCYKDM0Z285J8` | metasurface holography | `stale_parser_contract` | `success_primary` | Direct phase mapping of broadband Laguerre-Gaussian metasurfaces |
| 26 | `01KS6FFJF6XNCHFY2X589F6QD5` | photonic crystal cavity | `stale_parser_contract` | `success_primary` | Efficient Terahertz Generation in Triply Resonant Nonlinear Photonic Crystal Microcavities |
| 27 | `01KS6HR11SMNBNHF2EH7HQD1B8` | metasurface holography | `stale_parser_contract` | `success_primary` | Designing high-transmission and wide angle all-dielectric flat metasurfaces at telecom wavelengths |
| 28 | `01KS6HVY4CKH0GP6VQK7MXRXEK` | metalens | `no_target_sections_after_current_parser` | `no_target_sections` | Solid-Immersion Metalenses for Infrared Focal Plane Arrays |
| 29 | `01KS6FQ18T1VR46Z69BXKVAYYJ` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Specular holography |
| 30 | `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `no_target_sections_after_current_parser` | `no_target_sections` | All-optical conditional logic with a nonlinear photonic crystal nanocavity |
| 31 | `01KS6GE0HVC9YGPS7H9S0G3FXM` | metasurface holography | `no_target_sections_after_current_parser` | `no_target_sections` | Numerical heterodyne holography with two-dimensional photodetector arrays |

## Promotion Policy

Benchmark-topic papers below the decision-grade current-contract threshold must stay out of high-confidence Topic Dossier, bottleneck lineage, and Radar Claim Card promotion.
