# V14B First-Principles Path Challenge Audit

- generated_at: `2026-05-31T12:44:12Z`
- overall_status: `redirect_evidence_first`
- verdict_counts: `{"hold": 5, "redirect": 1}`

## Challenge Matrix

| Area | Verdict | First-principles test | Risk | Better path |
| --- | --- | --- | --- | --- |
| release_go_no_go | hold | A decision system is release-ready only when evidence gates, multi-topic regression, and high-confidence Claim Card gates are closed. | Graph/demo progress can be mistaken for scientific readiness. | Treat release_readiness as the go/no-go surface; keep user-visible claims evidence-scoped until it clears. |
| evidence_acquisition_strategy | redirect | Evidence acquisition should maximize decision lift per parsed paper, especially for benchmark-topic turning papers, future endpoints, and Claim Card inputs. | Full-corpus crawling can consume time while the benchmark-topic decision gaps remain open. | Keep broad crawling alive, but route engineering attention to topic-gap-repair and stale-contract/unattempted-PDF queues before promoting Dossier/Radar output. |
| retrieval_substrate | hold | Fuzzy retrieval can widen recall, but every retrieved context must remain candidate-only and must be available before downstream Claim Cards rely on it. | Long-section semantic recall is code-complete but absent from the live DB; Step13 may miss context until post-frontfill rebuild. | At the first safe section-ingest boundary, run post-frontfill-chain so section-embeddings, chains, Step5c/6/13, and audits rebuild together. |
| citation_backbone | hold | Citation evolution and main-path claims require enough linked references to distinguish field history from local-corpus sampling artifacts. | Main path can look causal while actually reflecting missing cited works. | Keep main-path output as low-linked-ref context and prioritize exact cited-work backfill plus relinking. |
| future_to_radar | hold | A future edge is only an inspection target until calibrated evidence, Step6 fusion, and a complete/high-confidence Step13 Claim Card exist. | Candidate ranking can be misread as investable direction confidence. | Keep raw future edges in candidate_pool and focus repair on complete five-question Claim Cards with falsifiable experiments. |
| openalex_field_context | hold | Field/topic context is useful only as uncertainty-aware context; it cannot substitute for local section evidence or linked citation evidence. | Cross-field claims may look broader than the current metadata support allows. | Continue conservative OpenAlex/local field-topic repair and label cross-field claims with uncertainty until coverage improves. |

## Evidence Snapshot

- **release_go_no_go**: `{"acceptance_ready": false, "multi_topic_status_counts": {"fail": 3, "warn": 1}, "release_status": "evidence_gated_not_release_ready", "value_delivery_summary": {"fail": 1, "pass": 13, "warn": 1}}`
- **evidence_acquisition_strategy**: `{"raw_pdf_store_status": "pass", "section_atoms": 61708, "topic_gap_blocking": true, "topic_gap_decision_grade_section_rate": 0.5769230769230769}`
- **retrieval_substrate**: `{"release_check_section_embeddings": false, "section_atom_embeddings": 61708, "section_embeddings": null}`
- **citation_backbone**: `{"linked_ref_rate": 0.14053874866242644, "threshold": 0.3}`
- **future_to_radar**: `{"direction_claim_cards": 5, "high_confidence_claim_cards": 0}`
- **openalex_field_context**: `{"openalex_w_rate": 0.6440497463944694, "threshold": 0.7}`

## Policy

This audit challenges the current route before more execution. It cannot promote claims; it only redirects effort toward the evidence path most likely to produce auditable Topic Dossiers, Evolution Evidence Maps, and Claim Cards.
