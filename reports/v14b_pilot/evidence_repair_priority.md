# V14B Evidence Repair Priority

- generated_at: `2026-05-31T12:25:35Z`
- overall_status: `evidence_first_repair_required`
- claim_scope: `evidence_repair_queue_only`
- promotion_policy: `no_direct_promotion`
- items: `6`; P0: `3`

## Contract

- Section atomization remains deterministic/rules-first and traceable to PDF page/span.
- Exact search is hard retrieval evidence; fuzzy vector search is candidate recall only.
- GNN/VGAE may expand or rank candidates only; it cannot create atoms or promote claims.

## Safe Boundary

- current_target_is_read_only: `true`
- do_not_start_competing_db_writers: `true`

## Priority Queue

| rank | priority | action | command | safe while broad ingest active | DB writer boundary |
|---:|---|---|---|---|---|
| 1 | `P0` | Close benchmark-topic evidence gaps before promotion. | `make topic-gap-repair` | no | yes |
| 2 | `P0` | Materialize section-level fuzzy context and rebuild downstream gates. | `make post-frontfill-chain` | no | yes |
| 3 | `P0` | Use exact/fuzzy atom recall to inspect missing typed-chain stages. | `make topic-gap-stage-candidate-recall` | yes | no |
| 4 | `P1` | Repair the citation backbone with exact provider IDs. | `make cited-work-backfill && make reference-relink-apply && make graph-features` | no | yes |
| 5 | `P2` | Continue conservative field/topic coverage repair. | `make openalex-backfill` | no | yes |
| 6 | `P2` | Keep the external raw PDF crawler as a background substrate. | `make raw-pdf-store-audit` | yes | no |

## Why These Actions

### 1. topic_gap_evidence_repair

- priority: `P0`
- pipeline_stage: `raw_pdf_local_store_to_section_atom_chains`
- why: Topic Dossier and Radar output are still gated by decision-grade section/atom/chain coverage for benchmark topics.
- immediate_safe_action: Keep the broad crawler/ingest running; review the generated topic-gap repair plan now, then run the DB-writing repair command at the next safe section-ingest boundary.
- evidence: `{"closure_state_counts": {"closed_decision_grade_section": 16, "closed_typed_chain_available": 1, "open_section_evidence_not_decision_grade": 118, "partial_atoms_available_no_chain": 12, "partial_chain_incomplete": 68}, "local_raw_pdf_ingest_contracts": 52, "open_repair_contracts": 198, "quick_close_contracts": 12, "raw_pdf_candidate_queue_available_rate": 0.23076923076923078, "topic_gap_decision_grade_section_rate": 0.5769230769230769, "topic_gap_gate_status": "fail"}`

### 2. post_frontfill_retrieval_rebuild

- priority: `P0`
- pipeline_stage: `section_atoms_to_Step5c_Step13`
- why: Atom exact/fuzzy search is available, but section-level fuzzy context is not materialized in the live DB; Step5c/Step13 should consume the rebuilt retrieval substrate together.
- immediate_safe_action: Wait for active section ingest to reach a safe boundary; the post-frontfill runner rebuilds section embeddings, atom chains, Step5c/Step6/Step13, and the audit loop.
- evidence: `{"release_check_section_embeddings": false, "section_atom_embeddings": 61708, "section_atoms": 61708, "section_embeddings": null}`

### 3. typed_stage_candidate_review

- priority: `P0`
- pipeline_stage: `exact_fts_bm25_plus_atom_embeddings_fuzzy_recall`
- why: Partial chains already have candidate atoms; reviewer/parser tuning can focus on the missing constraint/failure/attempt/local-fix/new-constraint stages.
- immediate_safe_action: This is read-only candidate recall; it can be refreshed while ingest runs, but any chain rebuild still waits for the DB-writer safe boundary.
- evidence: `{"candidate_tasks": 219, "cross_paper_templates_enabled": false, "missing_stage_counts": {"attempted_path": 39, "constraint": 30, "failure_mechanism": 32, "local_fix": 57, "new_constraint": 61}, "same_paper_candidate_hits": 452, "tasks_with_same_paper_candidates": 150}`

### 4. exact_cited_work_backfill

- priority: `P1`
- pipeline_stage: `citation_backbone`
- why: Main-path and branch-history claims remain weak while no-local-match references dominate; the repair path is exact cited-work backfill followed by exact relinking.
- immediate_safe_action: Keep the exact-ID queue ready; run small batches when no competing SQLite writer is active.
- evidence: `{"cited_work_queue_rows": 2000, "linked_ref_rate": 0.14053874866242644, "provider_counts": {"arxiv": 5, "doi": 1067, "openalex": 876, "s2": 52}, "threshold": 0.3}`

### 5. openalex_field_topic_repair

- priority: `P2`
- pipeline_stage: `field_topic_context`
- why: OpenAlex/local field-topic context is useful for uncertainty-aware filtering, but it cannot substitute for section evidence or linked citations.
- immediate_safe_action: Run only after checking provider cooldown and local DB writer status; keep cross-field claims uncertainty-labeled until coverage improves.
- evidence: `{"openalex_w_rate": 0.6440497463944694, "threshold": 0.7}`

### 6. raw_pdf_background_substrate

- priority: `P2`
- pipeline_stage: `raw_pdf_local_store`
- why: The crawler improves local-first section ingest, but broad crawling is supportive; benchmark-topic evidence repair remains the promotion bottleneck.
- immediate_safe_action: Refresh the read-only raw PDF store audit; do not treat crawler progress as release readiness.
- evidence: `{"candidate_queue_papers": 78, "candidate_queue_raw_pdf_available_papers": 18, "candidate_queue_raw_pdf_available_rate": 0.23076923076923078, "manifest_status": "ok", "queued_papers": 50088, "status": "pass", "success_papers": 5243, "success_probable_pdf_rate": 1.0, "total_manifest_rows": 55391}`
