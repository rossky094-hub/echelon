# Topic-Gap No-Target PDF Inspection

- audit_ts: `2026-05-31T00:51:54Z`
- triage_json: `reports/v14b_pilot/topic_gap_section_evidence_audit.json`
- parser_contract: `v14b_section_parser_contract_v3_toc_guard`
- status: `pass`
- inspected papers: `22`

## Classification Counts

| classification | papers |
|---|---:|
| sectionless_or_non_target_heading_format | 11 |
| heading_like_but_not_target_section | 9 |
| target_heading_signal_subthreshold | 2 |

## Papers

| paper_id | topics | classification | target signals | non-target examples | title |
|---|---|---|---:|---|---|
| `01KS6HE5D5W71A1GB9G2MXXT75` | photonic crystal cavity, quantum light source | `heading_like_but_not_target_section` | 0 |  | Microresonator Soliton Dual-Comb Spectroscopy |
| `01KS6GKQK1Y4S7EMFB2FR9H48M` | photonic crystal cavity, quantum light source | `sectionless_or_non_target_heading_format` | 0 | References | Modeling of octave-spanning Kerr frequency combs using a generalized mean-field Lugiato-Lefever model |
| `01KS6HRQRDVDHA23NJYK7V3X12` | photonic crystal cavity, quantum light source | `heading_like_but_not_target_section` | 0 |  | Monolithic Ultrahigh-Q Lithium Niobate Microring Resonator |
| `01KS5KMDAC6220S2FEJCB6XVTB` | photonic crystal cavity | `sectionless_or_non_target_heading_format` | 0 | Abstract; References: | Silicon-based photonic crystal nanocavity light emitters |
| `01KS5KM2ECB6AESTQYWAX0M8SF` | photonic crystal cavity | `sectionless_or_non_target_heading_format` | 0 | Abstract; Acknowledgments | An open cavity formed with a photonic crystal of negative refraction |
| `01KS5KM369VWG4F2AV2MS14S3E` | photonic crystal cavity | `heading_like_but_not_target_section` | 0 |  | Surface state photonic bandgap cavities |
| `01KS5KWKMCV3DHKBFJH2Z0JN6A` | photonic crystal cavity | `heading_like_but_not_target_section` | 0 |  | Fabrication-tolerant high quality factor photonic crystal microcavities |
| `01KS6HJEXQGTKP950NRDA3CVT2` | metalens, metasurface holography | `sectionless_or_non_target_heading_format` | 0 | Supporting Information; Acknowledgements; References | A Reconfigurable Active Huygens' Metalens |
| `01KS6GYEHTKSM99P2N7GPYZEX7` | quantum light source | `target_heading_signal_subthreshold` | 1 |  | Deterministic photon-emitter coupling in chiral photonic circuits |
| `01KS6HEPDK5G604MQCB4RTXK57` | quantum light source | `target_heading_signal_subthreshold` | 1 |  | Chiral Quantum Optics |
| `01KS6GW09MSPBB2H90HQYJ3JCK` | quantum light source | `heading_like_but_not_target_section` | 0 |  | Near-unity coupling efficiency of a quantum emitter to a photonic-crystal waveguide |
| `01KS6HMZS9ACM80N6QJ22RAHGV` | metalens | `heading_like_but_not_target_section` | 0 |  | Topology Optimized Multi-layered Meta-optics |
| `01KS6HNKKTN0P5DTSRMS86C3GR` | metasurface holography | `heading_like_but_not_target_section` | 0 |  | Generating Spatial Spectrum with Metasurfaces |
| `01KS6FGD433ZJXYBXPYVZ727SG` | photonic crystal cavity | `sectionless_or_non_target_heading_format` | 0 | References | Demonstration of an air-slot mode-gap confined photonic crystal slab nanocavity with ultrasmall mode volumes |
| `01KS6GND5KCR5HPW1YFZYW5ANY` | quantum light source | `sectionless_or_non_target_heading_format` | 0 | Bibliography; Bibliography; Bibliography | Characterization of a Quantum Light Source Based on Spontaneous Parametric Down-Conversion |
| `01KS6HGSMCY03E789TEE3B0FCT` | metalens | `sectionless_or_non_target_heading_format` | 0 | References | A Dual Field-of-View Zoom Metalens |
| `01KS6HPP3KS1MWWYWQ6GW64AV7` | metalens | `sectionless_or_non_target_heading_format` | 0 | Abstract; REFERENCES | Silicon nitride metalenses for unpolarized high-NA visible imaging |
| `01KS5KW8C34R9WN637BH5ABW1R` | quantum light source | `heading_like_but_not_target_section` | 0 |  | Ultra-bright source of polarization-entangled photons |
| `01KS6HVY4CKH0GP6VQK7MXRXEK` | metalens | `sectionless_or_non_target_heading_format` | 0 | Abstract; References | Solid-Immersion Metalenses for Infrared Focal Plane Arrays |
| `01KS6FQ18T1VR46Z69BXKVAYYJ` | metasurface holography | `sectionless_or_non_target_heading_format` | 0 | Abstract; References | Specular holography |
| `01KS6FG0VYNT6MYBBYMX8TBYDR` | photonic crystal cavity | `sectionless_or_non_target_heading_format` | 0 | Acknowledgements | All-optical conditional logic with a nonlinear photonic crystal nanocavity |
| `01KS6GE0HVC9YGPS7H9S0G3FXM` | metasurface holography | `heading_like_but_not_target_section` | 0 |  | Numerical heterodyne holography with two-dimensional photodetector arrays |

## Policy

Current-parser no-target papers are not decision-grade section evidence. Only rows with target_heading_signal_present should be treated as parser repair candidates; subthreshold target signals and sectionless/non-target-heading papers remain weak full-text or metadata evidence.
