# V14B Optics Step1-Step6 Algorithm Audit

Generated: 2026-05-27

This audit checks whether Step1-Step6 can support the updated project target:
an explainable optics evolution graph that answers "why did it grow this way"
and "where may it grow next". The conclusion is that Step1-Step4 now provide
a usable graph-ready base, while Step5a-Step6 required corrections before they
could be trusted as future-growth evidence.

## Current Data Baseline

- Papers: 55,391
- OpenAlex W IDs: 30,574
- Invalid OpenAlex IDs: 0
- Primary Field IDs: 30,575
- References: 3,016,141
- Linked internal references: 413,737
- Paper embeddings: 55,391
- Step2 main_path_edges: 277,195
- Step2 is_main_path edges: 2,771
- Step2 SCC cycle components: 66
- Step2 cyclic nodes: 138
- Step2 intra-cycle edges: 148
- Step4 subgraph nodes: 5,000
- Step4 subgraph edges: 38,778
- Step5a classified edges: 38,778
- Step5b predicted future edges: 1,000
- Step5b cross-field predicted edges: 41
- Step5c limitation atoms: 1,063
- Step5c limitation resolutions: 1,743
- Step6 future directions: 6

## Step1 Enrich

Purpose:
Build provider-clean paper metadata, references, identifiers, fields/topics, and
signals needed by later graph construction.

Audit result:
Usable as the graph-ready metadata base, provided that provider IDs remain
separated. The current library has repaired OpenAlex ID pollution: invalid
OpenAlex IDs are now 0, while S2 IDs are kept in `s2_paper_id`.

Fix/status:
The default provider order is now S2 -> Crossref -> OpenAlex when keys and
rate limits allow it. OpenAlex backfill is treated as a non-blocking quality
supplement rather than a blocker for the whole product chain.

Remaining risk:
OpenAlex Field/Topic coverage is still partial at 30,575 / 55,391 papers. That
is enough to continue, but uncertainty must be visible in visual graph outputs.

## Step2 Main Path

Purpose:
Compute the citation-flow backbone that explains the historical trunk of the
field.

Audit result:
The new SCC condensation DAG approach is the correct fix for circular citation
components. It preserves cycle evidence in audit tables instead of deleting
edges by arbitrary ULID/order. This is aligned with SPC/main-path literature:
the main path should run over a DAG, while cycles should be explicitly audited.

Fix/status:
`main_path_cycle_audit` and `main_path_edge_audit` are now required outputs.
The current run has 66 SCC cycle components and 2,771 main-path edges.

Remaining risk:
Column names in `main_path_edges` still use historical `citing_id/cited_id`
names even when the Step2 graph is stored as time-forward flow. This is not a
runtime blocker, but should be renamed or documented before the API layer is
treated as stable.

## Step3 KeystoneScore

Purpose:
Score papers that likely shape branch formation or field evolution.

Audit result:
Usable as a node-importance signal after Step0 graph features are populated.
It is not by itself a future-direction algorithm; it is an evidence layer.

Fix/status:
Step3 now writes run metadata into `v14b_run_meta`, so monitors can distinguish
completed scoring from stale pilot artifacts.

Remaining risk:
Fresh/growing/mature behavior depends on the quality of feature columns such as
bridging centrality, recent burst, co-citation breadth, and semantic outlier.
If those columns regress to defaults, KeystoneScore loses discriminative power.

## Step4 Subgraph

Purpose:
Select a tractable pilot subgraph for expensive algorithms such as citation
function classification, VGAE, limitation tracking, mutation/layout/report.

Audit result:
Valid for pilot computation, not sufficient as the final visual graph product.
The product visual graph must later use all 55,391 papers with LOD/tile exports,
while Step4 can remain the expensive-model working set.

Fix/status:
Current subgraph contains 5,000 nodes and 38,778 internal edges.

Remaining risk:
Any conclusion generated only from the 5,000-node subgraph must be labeled as
pilot/evidence, not as the complete optics graph.

## Step5a Citation Function

Purpose:
Classify citation edges into evidence types such as usage, motivation,
extension, similarity, background, and future_work.

Audit result:
The old implementation was not acceptable for the product chain because it
used a zero-shot NLI model without real citation sentence context and then
attempted a huge LLM fallback for low-confidence edges.

Fix/status:
Default mode is now deterministic heuristic classification over title/abstract
metadata. Heavy zero-shot/LLM modes are opt-in only. Step5a now completes fast,
writes all 38,778 subgraph edge classifications, and records run metadata.

Remaining risk:
Without full-text citation contexts, citation function remains a weak evidence
layer. It should influence fusion weights, not act as ground truth.

## Step5b VGAE Future Growth

Purpose:
Predict likely future growth links using graph structure and paper features.

Audit result:
This was the highest-risk algorithm. The previous direction semantics trained
on raw citation edges as `citing -> cited` but interpreted predicted edges as
future growth. Since the decoder is symmetric, it could turn reverse historical
citations into "future" predictions.

Fix/status:
Step5b now converts raw citations into time-forward evolution records:
older cited paper -> newer citing paper. Same-year, unknown-year, and
time-inverted references are excluded from training. Validation/test splits are
chronological, and negative sampling respects temporal direction. Predicted
future edges exclude known historical pairs in either orientation.

Remaining risk:
After the semantic fix, predicted edge counts may be lower. That is preferable
to producing misleading future links. If confidence is weak, the next fix should
improve candidate generation/calibration, not lower thresholds blindly.

## Step5c Limitation Tracking

Purpose:
Extract unresolved limitations and test whether later papers appear to resolve
them.

Audit result:
The previous path was too LLM-heavy for the main pipeline and could not serve
as the algorithmic audit backbone requested by the project owner.

Fix/status:
Default extraction and resolution are now heuristic/algorithmic. LLM usage is
opt-in for semantic sampling. Resolution candidates are capped by default.
If a previous checkpoint only skipped resolution, Step5c can now resume into
Phase3 resolution tracking without duplicating existing atoms.

Remaining risk:
Abstract-only limitations are weaker than structured section-level evidence.
The visual graph should mark limitation evidence quality and later ingest
`paper_sections` / Sci-Bot sections when available.

## Step6 Fusion

Purpose:
Fuse main-path terminal evidence, VGAE predictions, unresolved limitations,
and high-impact fields into future direction candidates.

Audit result:
The previous fusion could count weak VGAE paths unconditionally and could write
a placeholder direction when evidence was empty. That would contaminate the
visual graph and downstream recommendations.

Fix/status:
Fusion now counts VGAE evidence only above the configured confidence threshold,
uses corrected time-forward terminal logic, avoids merging all unknown-field
records into one bucket, and writes zero directions instead of a fake `TBD`
direction when evidence is insufficient.
Direction naming is deterministic by default, so an external LLM failure cannot
block the product chain. LLM naming is optional via `V14B_FUSION_USE_LLM_NAMING`.
Evidence paper IDs and limitation keywords are stable-deduplicated before
writing `future_directions`.

Remaining risk:
If Step5b/Step5c produce sparse evidence after the fixes, Step6 may output few
or zero directions. That is an honest signal that branch-lineage and calibrated
future-growth algorithms need strengthening before user-facing claims.

## Overall Goal Fit

Step1-Step4 now support the historical backbone and pilot evidence set.
Step5a-Step6 have been corrected so they no longer silently generate misleading
future evidence. This makes the current chain suitable for an honest alpha run:
it can produce a stronger optics evolution graph base, and it can reveal whether
future-growth evidence is currently strong enough.

The remaining project-level gap is not a single step bug. The system still needs
the Step10 visual graph builder and branch-lineage layer to convert these
signals into the final product form: full graph tiles, 2.5D coordinates, branch
parent-child lineage, searchable paper details, recommendation modes, and
uncertainty overlays.

## Post-Fix Rerun

After the fixes, Step5b-Step6 were rerun on the current V14B pilot database.

- Step5b temporal evolution edges: 36,240 from 38,778 raw subgraph edges
- Step5b skipped same-year edges: 2,128
- Step5b skipped time-inverted edges: 356
- Step5b skipped missing-node edges: 54
- Step5b validation AUC: 0.8861
- Step5b test AUC: 0.8981
- Step5b predicted edges written: 1,000
- Step5b cross-field predicted edges: 41
- Step5c limitation atoms: 1,063
- Step5c resolution records: 1,743
- Step6 future directions: 6

The rerun supports a more honest alpha output: future-growth evidence is now
time-forward and no longer derived from reversed historical citation direction.
However, Step6 directions should still be treated as evidence-backed candidates,
not final scientific claims, until branch-lineage and Step10 visual graph
validation are complete.
