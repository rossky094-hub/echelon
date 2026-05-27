# Active V14B Tooling Manifest

Canonical project root:

`/Users/r/Documents/New project/echelon/echelon-v14b`

Active V14B entrypoints:

- `Makefile`
- `echelon/v14b/step0_id_repair.py`
- `echelon/v14b/step0_openalex_backfill.py`
- `echelon/v14b/step0_graph_features.py`
- `echelon/v14b/step0_embeddings.py`
- `echelon/v14b/step0_reset_pilot.py`
- `scripts/monitor_optics_full_pipeline.sh`
- `scripts/diff_arxiv_optics_vs_db.py`
- `scripts/fetch_missing_arxiv_optics.sh`
- `scripts/run_step1_arxiv_enrich.sh`
- `scripts/run_arxiv_optics_harvest.sh`
- `scripts/run_arxiv_optics_incremental.sh`
- `echelon/v14b/*.py`

Required support packages kept active:

- `echelon/core`
- `echelon/crawler`
- `echelon/library`
- `echelon/seeds`

Legacy tools removed from active paths:

- `pilot/`
- `scibot/`
- older e2e monitor scripts
- V11/V12/V13 reports
- old pilot databases and embedding files
- old `CONFIG.md`

They are archived under:

`legacy_archive/legacy_tools_20260525_220529`

Step1 enrich has an import-origin guard. It refuses to run unless
`echelon.v14b.step1_enrich`, `echelon.v14b.enrich_providers`, and
`echelon.v14b.config` resolve inside the canonical project root.

Graph-readiness hardening:

- Provider IDs are split by semantic field (`openalex_id`, `s2_paper_id`, DOI, arXiv).
- Reference rows are normalized with provider/type metadata before internal linking.
- Clean graph reruns should use `make reset-pilot pilot` after enrich completion.
