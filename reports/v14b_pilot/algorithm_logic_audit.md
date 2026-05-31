# V14B Algorithm Logic Audit

- generated_at: `2026-05-31T02:53:16Z`
- linked_ref_rate: `14.1%`
- openalex_w_rate: `64.4%`
- primary_section_papers: `3,024`
- section_atoms: `61,083`
- section_atom_decision_grade: `9,052`
- section_atoms_fts: `yes`
- section_atom_chains: `4,448`
- section_atom_chain_full: `5`
- section_atom_chain_decision_grade: `2`
- limitation_exact_section_atoms: `1,073`
- limitation_aggregate_section_atoms: `0`
- complete_typed_lineage_triples: `20`
- partial_typed_lineage_triples: `22,064`
- lineage_completeness_counts: `{"attempted_path_partial": 1368, "constraint_failure_only": 5308, "full": 20, "local_fix_partial": 272, "resolution_candidate_partial": 1988, "sparse_stage_partial": 13128}`
- topic_gap_decision_grade_section_rate: `29.0%`
- failed regression topics: `metalens, metasurface holography, photonic crystal cavity, quantum light source`

## Policy

Algorithm fit must be judged before path execution. A step can be algorithmically aligned while live readiness is failing; the correct action is then to improve inputs/evidence, not weaken the algorithm.

## Step Audits

| step | algorithm_fit | readiness | algorithm role | challenge | next tuning |
|---|---|---|---|---|---|
| id-repair / relinking | `aligned` | `fail` | Build an exact provider-ID citation spine; never use fuzzy links as citation truth. | linked refs are 14.1%; the algorithm is conservative but corpus coverage is still thin. | Continue exact cited-work backfill; do not reintroduce fuzzy relinking to inflate coverage. |
| OpenAlex / local field-topic backfill | `aligned` | `warn` | Provide field/topic context as an uncertainty-aware enrichment layer, not a product blocker. | OpenAlex W coverage is 64.4%; frontfill status=stalled_after_cooldown. | Resume conservative OpenAlex repair or strengthen local field-topic fallback before cross-field claims are promoted. |
| graph-features | `aligned` | `pass` | Compute interpretable structural signals for keystone, branch, and fusion weighting. | Feature semantics are useful only if linked citation coverage remains honest. | Add feature freshness checks per corpus and expose feature-default rates in audits. |
| embeddings | `aligned` | `pass` | Support semantic retrieval and neighborhood expansion without replacing citation evidence. | embeddings=55,391; papers=55,401. | Keep semantic layer labeled as retrieval/expansion; require citation/section evidence for claims. |
| quality audit | `aligned` | `warn` | Stop poor coverage from becoming confident product output. | The audit layer exists, but live readiness still depends on citation and section gaps. | Promote quality-audit failures into user-visible uncertainty overlays. |
| Step2 main path | `aligned` | `warn` | Extract historical trunk from citation-flow DAG, with SCC cycles audited instead of deleted. | main_path_core_edges=2,775; linked_ref_rate=14.1%. | Keep uncertainty labels on main path and continue exact citation corpus expansion. |
| Step3 keystone | `aligned` | `pass` | Rank papers as branch/turning-point candidates using structural and temporal signals. | Useful for queue prioritization, risky if interpreted as causal driver by itself. | Add per-feature contribution traces to Topic Dossier driver-paper explanations. |
| Step4 graph/subgraph evidence | `aligned` | `pass` | Create a bounded expensive-model evidence set while preserving full-graph product scope. | subgraph_nodes=5,000; subgraph_edges=38,538. | Keep Step10 full-graph/LOD path separate from Step4 bounded extraction support. |
| Step5a citation function | `aligned` | `warn` | Label citation roles as weak/moderate evidence for fusion, not ground truth. | citation_function_edges=38,538; evidence remains weak without citation sentences. | Prefer deterministic weak labels now; add citation-context extraction before increasing weights. |
| Step5b calibrated future candidate generator | `aligned` | `pass` | Generate future candidates from temporal evidence; never produce conclusions directly. | future_candidate_edges=1,000; calibration_audits=1. | Continue rolling held-out-year calibration and stratified external audit; do not expose VGAE as Radar claims. |
| Step5s section evidence | `aligned` | `fail` | Materialize section-level evidence for limitation, bottleneck, and Claim Card reasoning. | primary_section_papers=3,024; topic_gap_decision_grade=29.0%; no-target parser signal=0. | Do not loosen parser for current no-target bucket; reparse stale-contract rows and process unattempted PDF rows when the active ingest is safe. |
| Step5s-a section atom search | `aligned` | `pass` | Split trusted sections into span-bound retrieval atoms with exact search; keep GNN/VGAE as ranking or expansion only. | section_atoms=61,083; decision_grade_atoms=9,052; exact_atom_fts=yes; GNN/VGAE must not atomize sections. | Add atom embeddings for fuzzy search, then let Step5c/Step13 consume atoms through evidence contracts instead of re-parsing ad hoc text. |
| Step5s-b section atom typed chains | `aligned` | `pass` | Assemble co-located section atoms into typed bottleneck-chain evidence candidates before Step13 claim reasoning. | section_atom_chains=4,448; full_chains=5; decision_grade_chains=2; these chains are evidence substrate, not conclusions. | Wire full/partial section_atom_chains into Step13 so bottleneck_lineage_triples stop relying on placeholder stages. |
| Step5c limitation / resolution extraction | `needs_tuning` | `warn` | Extract unresolved constraints and resolution attempts from trusted sections. | limitation_atoms=1,073; exact_section_atoms=1,073; aggregate_section_atoms=0; section coverage is still the limiting input. | Retune extraction toward typed chains from current-contract sections; keep abstract fallback low scope. |
| Step6 fusion | `aligned` | `warn` | Fuse independent evidence paths into direction candidates with explicit adequacy. | future_directions=5; high_confidence_claim_cards=0. | Raise evidence by improving inputs, not by lowering fusion thresholds. |
| Step13 first-principles + Claim Card engine | `aligned` | `warn` | Turn candidate directions into falsifiable, evidence-scoped research claims. | Claim Cards=5; complete=1; high_confidence=0; complete_typed_lineage_triples=20; partial_typed_lineage_triples=22,064; lineage_completeness={'sparse_stage_partial': 13128, 'constraint_failure_only': 5308, 'attempted_path_partial': 1368, 'local_fix_partial': 272, 'full': 20, 'resolution_candidate_partial': 1988}. | Bind every Claim Card answer to typed bottleneck-chain evidence and minimal validation experiment criteria. |
| Step7 mutation | `needs_tuning` | `warn` | Explore evidence-backed variation paths without inventing scientific conclusions. | Mutation is useful only after Claim Card evidence objects are complete. | Retune mutation generation around minimal validation experiments rather than visual novelty. |
| Step8 layout | `aligned` | `pass` | Lay out graph evidence for inspection, not for discovering lineage by clustering alone. | visual_nodes=55,391; branch_lineages=5,278. | Keep layout_cluster_only separate from weak/evidence-backed splits in UI/API. |
| Step9 report | `aligned` | `warn` | Report evidence boundaries and remaining risk rather than a success narrative. | Current reports expose insufficiency; live product remains below high-confidence threshold. | Make algorithm_logic_audit a required report section before product release. |
| Step10 visual graph / Topic Dossier / Radar | `aligned` | `warn` | Present Topic Dossier first, graph as explain/verify layers, Radar as gated Claim Cards. | failed regression topics=metalens, metasurface holography, photonic crystal cavity, quantum light source. | Prioritize multi-topic dossier failures over single-topic polish. |
| Step12 / value delivery audit | `aligned` | `fail` | Enforce acceptance gates and keep weak evidence from becoming product claims. | evidence_policy depends on linked refs, topic-gap sections, calibration, Claim Cards, and multi-corpus gates. | Use this audit as the release stop/go gate; do not redefine success around passing subsets. |
| quarterly / multi-corpus | `aligned` | `pass` | Preserve corpus-specific builds before cross-corpus bridge graph. | corpus_registry=1; corpus_snapshots=0. | Add per-corpus algorithm-logic audit before building cross-corpus bridge claims. |

## Input / Output Contracts

| step | input contract | output contract | promotion guard |
|---|---|---|---|
| id-repair / relinking | DOI/OpenAlex/S2/arXiv identifiers and raw paper_references. | Exact linked internal references plus explicit no-local-match taxonomy. | If linked refs <30%, main-path/citation-evolution claims must expose uncertainty. |
| OpenAlex / local field-topic backfill | OpenAlex IDs plus local metadata fallback. | Field/topic labels and coverage health. | Cross-field and cross-corpus claims need uncertainty while OpenAlex W coverage is incomplete. |
| graph-features | Exact citation graph and paper metadata. | Centrality, bridge, burst, and corpus-scoped feature columns. | Features are signals, not conclusions; downstream must keep evidence_grade. |
| embeddings | Paper title/abstract/full-text summaries. | Vector embeddings for semantic/co-cite/future candidate support. | Semantic proximity cannot imply lineage or causality. |
| quality audit | Coverage metrics, identifiers, references, embeddings, and corpus scope. | Gate labels and uncertainty reasons. | Quality audit must fail loudly rather than lowering thresholds. |
| Step2 main path | Exact linked citation graph. | Main path edges plus cycle audit. | Main path below 30% linked refs is historical-hypothesis, not field truth. |
| Step3 keystone | Graph features, citations, recency, and field context. | Keystone scores for prioritization and dossier reading paths. | Keystone is an importance prior; branch causality needs lineage evidence. |
| Step4 graph/subgraph evidence | Keystone/main/future/branch candidate paper IDs. | Subgraph nodes/edges and bounded scope audit. | Subgraph-only conclusions must be scoped as bounded evidence. |
| Step5a citation function | Citation edge endpoints plus metadata/context when available. | Citation-function labels, confidence, and evidence level. | No-context labels must remain low weight. |
| Step5b calibrated future candidate generator | Time-forward evolution edges, graph features, embeddings, and calibration split. | Candidate edges with raw/calibrated scores and lifecycle state. | Uncalibrated or unfused edges stay candidate pool only. |
| Step5s section evidence | OA PDFs and prioritized topic/claim/branch queues. | Current-contract decision-grade primary section rows plus failure taxonomy. | No section coverage for key papers means no high-confidence bottleneck/Claim Card. |
| Step5s-a section atom search | paper_sections with parser contract, extraction provenance, pages, and raw-PDF storage URI when available. | section_atoms plus FTS/BM25 retrieval hits labeled retrieval_context_only. | Atom hits can seed Step5c/Step13 evidence work, but cannot become scientific conclusions without typed chains and promotion gates. |
| Step5s-b section atom typed chains | section_atoms with atom_type, section order, parser contract, pages, and source URI. | section_atom_chains carrying typed_chain_completeness, evidence objects, claim_scope, and uncertainty reasons. | Partial chains are exploratory context only; full chains still require Step13 Claim Card promotion. |
| Step5c limitation / resolution extraction | Decision-grade sections first, weak abstract metadata only as scoped fallback. | Typed limitations/resolutions with evidence source, section, and weight. | Abstract-only bottlenecks cannot support high-confidence Claim Cards. |
| Step6 fusion | Main path terminals, calibrated future candidates, limitations, field/topic context. | Future directions with evidence tier, claim scope, and adequacy label. | Sparse fusion should output few/zero directions instead of placeholders. |
| Step13 first-principles + Claim Card engine | Fused directions, bottleneck lineage, section evidence, calibration, and history. | Five-question Claim Cards with evidence objects and uncertainty reasons. | Incomplete cards stay candidate pool; Radar main view requires complete cards. |
| Step7 mutation | Claim-card candidates and graph/section constraints. | Mutation hypotheses scoped to candidate pool. | Mutation outputs must inherit evidence grade and falsification conditions. |
| Step8 layout | Visual nodes/edges with layer contracts. | Coordinates and clusters with lineage_status separation. | Layout cluster alone cannot imply branch lineage. |
| Step9 report | Audits, graph outputs, Claim Cards, and regression results. | Evidence-decision report with uncertainty and next actions. | Reports must not describe low-coverage paths as complete. |
| Step10 visual graph / Topic Dossier / Radar | Evidence layers, lineage, candidates, and Claim Cards. | Dossier, Evidence Map, and Radar views with layer limits. | No naked GNN edges in Radar main view. |
| Step12 / value delivery audit | All reports, live tables, source contracts, and regression outputs. | Gate summary and evidence_policy. | Goal completion requires every explicit gate to be proven by current evidence. |
| quarterly / multi-corpus | Corpus registry, paper_corpora, snapshots, and corpus-scoped runs. | Independent optics/CS/materials snapshots plus later bridge graph. | No optics-only hardwiring in algorithms. |
