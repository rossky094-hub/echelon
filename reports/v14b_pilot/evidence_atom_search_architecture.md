# Evidence Atom Search Architecture

## First-Principles Boundary

V14B should not use GNN/VGAE to create section atoms. GNN/VGAE is a future candidate generator and graph prior: it can rank where to inspect next, expand from known evidence through citation/co-citation/semantic neighborhoods, and propose candidate paths. It must not invent evidence atoms or promote claims.

Section atomization belongs to the evidence extraction layer:

1. Raw PDF cache provides stable bytes and repeatable parsing.
2. Section parser creates section-level provenance with page/contract metadata.
3. Atomizer splits sections into auditable evidence atoms.
4. Relation extractor links atoms into typed chains.
5. Step6/Step13 consume atoms and relations to build Claim Cards and bottleneck lineage.

## Atom Schema Target

The next durable object should be a general `section_atoms` / `evidence_atoms` layer, not only `limitation_atoms`.

Required fields:

- `atom_id`, `paper_id`, `section_name`, `page_start`, `page_end`
- `atom_type`: `constraint`, `failure_mechanism`, `attempted_path`, `local_fix`, `new_constraint`, `metric_result`, `validation_setup`, `cost_or_scaling_signal`
- `atom_text`, `normalized_entities_json`, `metrics_json`
- `source_url`, `source_storage_uri`, `parser_contract_version`
- `evidence_grade`, `claim_scope`, `uncertainty_reasons_json`
- `extractor_method`: deterministic / classifier / llm_span_checked

LLM may help classify or normalize atoms only when it returns span-bound evidence. It cannot generate atoms without source spans.

## Search Model

V14B needs both exact and fuzzy search, but they must have different semantics.

Exact search:

- SQL filters: `paper_id`, DOI/arXiv/S2/OpenAlex ID, year, topic, section, atom type, evidence grade.
- FTS/BM25 over `atom_text`, `section_text`, title, abstract.
- Phrase and keyword search for reproducible audits.
- Output semantics: retrieval hit, not automatically a scientific conclusion.

Fuzzy search:

- Embeddings over atom text and section text, not just whole paper abstracts.
- Hybrid retrieval: exact filters first, vector similarity second, graph expansion last.
- Graph expansion can add citation/co-citation/semantic neighbors as context, but must label them as expansion evidence.
- Output semantics: exploratory retrieval unless Step6/Step13 attach evidence contracts.

## GNN Role

Correct uses:

- Future candidate generator over paper/atom/direction graph.
- Active-learning queue: which raw PDFs, sections, or atoms need parsing or review next.
- Retrieval prior: expand from exact atoms to likely related historical attempts.
- Weak path proposal: suggest possible `constraint -> attempted_path -> local_fix -> new_constraint` chains for verification.

Incorrect uses:

- Directly atomizing sections.
- Treating predicted edges as evidence.
- Promoting fuzzy/semantic neighbors into Claim Cards without section atoms and quality gates.

## Immediate Implementation Direction

1. Keep raw PDF full download running on the external store.
2. Make Step5s prefer local raw PDFs so parsing becomes repeatable and cheaper.
3. Add `section_atoms` as the next extraction substrate.
4. Add exact FTS index over atoms.
5. Add atom embeddings and hybrid search.
6. Let Step5c/Step13 consume atom search results only through evidence contracts.

## Implemented Substrate

Current implementation:

- `echelon.v14b.section_atoms` builds `section_atoms` from `paper_sections`.
- `make section-atoms` materializes the atom table and exact FTS/BM25 index.
- Search hits carry `claim_scope=retrieval_context_only`; they are retrieval context, not product claims.
- `algorithm_logic_audit` now reports `section_atoms`, decision-grade atom count, and whether exact atom FTS is present.

Next layer:

- Add atom-level embeddings for fuzzy search.
- Add hybrid retrieval: exact filters -> atom vectors -> graph/GNN expansion.
- Wire Step5c/Step13 to consume atom hits through typed evidence-chain contracts.
