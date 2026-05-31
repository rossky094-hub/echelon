# ========================================================
# Echelon V14-B 演化树 Evidence Decision Workflow — Makefile
# 平台: macOS Apple Silicon (M1/M2/M3)
#
# 快速开始:
#   make setup           # 安装依赖
#   cp .env.example .env # 配置环境变量
#   make product-chain   # 当前 V14B 证据约束产品链路
#   make post-frontfill-chain # 前置补齐完成后从证据门槛断点推进
#   make value-delivery-audit # 验证证据边界和交付门槛
#
# Legacy compatibility:
#   make pilot           # LEGACY compatibility only; not current V14B decision workflow
#   make pilot-full      # LEGACY compatibility only; calls enrich and is not an acceptance path
#
# 查看帮助:
#   make help
# ========================================================

.PHONY: setup id-repair reference-relink-audit reference-relink-apply cited-work-backfill-queue cited-work-backfill openalex-backfill graph-features embeddings evidence-prep graph-prep reset-pilot quality-audit product-baseline topic-regression access-audit recover-vgae-calibration-audit future-lifecycle-audit direction-readiness-audit value-delivery-audit evidence-bone-audit algorithm-logic-audit decision-audit topic-gap-repair enrich mainpath keystone subgraph scibert vgae section-evidence section-evidence-delta section-evidence-topic-gaps section-atoms section-atom-embeddings section-atom-chains raw-pdf-store-audit section-queue-audit topic-gap-section-audit topic-gap-no-target-inspect topic-gap-raw-pdf-inspect post-frontfill-chain limitation \
        fusion mutation layout report visual-graph first-principles goal-audit llm-edge-audit-plan llm-edge-audit-run product-chain product-chain-fast pilot pilot-graph pilot-visual pilot-full \
        quarterly-run quarterly-run-optics quarterly-run-cs quarterly-run-materials clean help

# Python 解释器
PYTHON := python3

# 数据库路径
DB_MAIN := db/echelon_library.sqlite3
DB_V14  := db/v14_pilot.sqlite3
CORPUS_ARG := $(if $(V14B_CORPUS_ID),--corpus-id $(V14B_CORPUS_ID),)

# 季度模板资源参数默认值（可覆盖）
V14B_Q_THREADS ?= 4
V14B_Q_EMBED_BATCH ?= 16

# -------------------------------------------------------
# 环境检查
# -------------------------------------------------------

## 安装依赖、检查环境
setup:
	@echo ">>> 安装 V14-B 依赖..."
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-v14b.txt
	@echo ""
	@echo ">>> 检查环境..."
	$(PYTHON) -m echelon.v14b.utils check_env
	@echo ""
	@echo "✅ 安装完成! 下一步:"
	@echo "   cp .env.example .env"
	@echo "   编辑 .env,填入 API Key"
	@echo "   make product-chain  # 当前 V14B 证据约束产品链路"
	@echo "   make post-frontfill-chain  # section/frontfill 完成后的断点推进"

# -------------------------------------------------------
# 各 Step
# -------------------------------------------------------

## Step 0.2: Provider ID repair + reference relinking
id-repair:
	@echo ">>> Step 0.2: Provider ID repair + reference relinking..."
	$(PYTHON) -m echelon.v14b.step0_id_repair \
		--db $(DB_MAIN) \
		$(CORPUS_ARG)

## Reference relink audit: deterministic DOI/OpenAlex/S2/arXiv exact joins
reference-relink-audit:
	@echo ">>> Reference relink audit: deterministic exact joins..."
	$(PYTHON) -m echelon.v14b.reference_relink_audit \
		--db $(DB_MAIN) \
		--out-dir reports/v14b_pilot \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Reference relink apply: only exact unambiguous DOI/OpenAlex/S2/arXiv joins
reference-relink-apply:
	@echo ">>> Reference relink apply: deterministic exact joins only..."
	$(PYTHON) -m echelon.v14b.reference_relink_audit \
		--db $(DB_MAIN) \
		--out-dir reports/v14b_pilot \
		--apply \
		--chunk-size $${V14B_REFERENCE_RELINK_CHUNK_SIZE:-5000} \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Cited-work backfill queue: high-value missing referenced works
cited-work-backfill-queue:
	@echo ">>> Cited-work backfill queue: exact provider-ID missing cited works..."
	$(PYTHON) -m echelon.v14b.cited_work_backfill_queue \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		--queue data/v14b/cited_work_backfill_queue.csv \
		--limit $${V14B_CITED_WORK_QUEUE_LIMIT:-2000}

## Cited-work backfill: fetch exact-ID queue targets through OpenAlex
cited-work-backfill:
	@echo ">>> Cited-work backfill: conservative exact-ID OpenAlex fetch..."
	$(PYTHON) scripts/guard_openalex_backfill.py --repo-root .
	$(PYTHON) -m echelon.v14b.cited_work_backfill \
		--db $(DB_MAIN) \
		--queue data/v14b/cited_work_backfill_queue.csv \
		--out-dir reports/v14b_pilot \
		--limit $${V14B_CITED_WORK_BACKFILL_LIMIT:-25} \
		--providers $${V14B_CITED_WORK_BACKFILL_PROVIDERS:-openalex,doi} \
		--corpus-id $${V14B_CORPUS_ID:-optics} \
		--delay $${V14B_CITED_WORK_BACKFILL_DELAY:-1.2} \
		$${V14B_CITED_WORK_BACKFILL_DRY_RUN:+--dry-run} \
		$${V14B_CITED_WORK_BACKFILL_APPLY_RELINKS:+--apply-relinks}

## Step 0.25: OpenAlex Field/Topic backfill
openalex-backfill:
	@echo ">>> Step 0.25: OpenAlex Field/Topic backfill..."
	$(PYTHON) scripts/guard_openalex_backfill.py --repo-root .
	$(PYTHON) -m echelon.v14b.step0_openalex_backfill \
		--db $(DB_MAIN) \
		--concurrency $${V14B_OPENALEX_BACKFILL_CONCURRENCY:-1} \
		--delay $${V14B_OPENALEX_BACKFILL_DELAY:-1.2} \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 0.3: Paper embeddings for VGAE / UMAP
embeddings:
	@echo ">>> Step 0.3: Paper embeddings..."
	$(PYTHON) -m echelon.v14b.step0_embeddings \
		--db $(DB_MAIN) \
		--model $${V14B_EMBEDDING_MODEL:-sentence-transformers/all-mpnet-base-v2} \
		--batch-size $${V14B_EMBEDDING_BATCH_SIZE:-16} \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 0.4: Graph feature signals for Keystone / Mutation
graph-features:
	@echo ">>> Step 0.4: Graph feature signals..."
	$(PYTHON) -m echelon.v14b.step0_graph_features \
		--db $(DB_MAIN) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 0: Prepare graph-ready data
graph-prep: id-repair openalex-backfill graph-features embeddings
	@echo ">>> Graph prep done."

## Step 0.9: Evidence-ready data before user-facing claims
evidence-prep: openalex-backfill section-evidence section-atoms section-atom-chains
	@echo ">>> Evidence prep done: OpenAlex backfill + section evidence atom chains are complete for configured scope."

## Step 0.1: Reset old derived graph outputs
reset-pilot:
	@echo ">>> Step 0.1: Reset old V14B derived graph outputs..."
	$(PYTHON) -m echelon.v14b.step0_reset_pilot \
		--db-v14 $(DB_V14)

## Step 0.5: Coverage / Quality Audit
quality-audit:
	@echo ">>> Step 0.5: Coverage / Quality Audit..."
	$(PYTHON) -m echelon.v14b.step0_quality_audit \
		--db $(DB_MAIN) \
		--out-dir reports/v14b_pilot \
		$(CORPUS_ARG) \
		--fail-on $${V14B_AUDIT_FAIL_ON:-none}

## Product baseline: 50h task list + multi-topic Topic Dossier value rubric
product-baseline:
	@echo ">>> Product baseline: task backlog + multi-topic Topic Dossier quality snapshot..."
	$(PYTHON) -m echelon.v14b.product_baseline \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		--topic $${V14B_BASELINE_TOPIC:-all} \
		--top-k $${V14B_BASELINE_TOP_K:-80}

## Topic regression: multi-topic value baseline
topic-regression:
	@echo ">>> Topic regression: multi-topic decision-grade dossier audit..."
	$(PYTHON) -m echelon.v14b.topic_regression \
		--topic $${V14B_TOPIC_REGRESSION_TOPIC:-all} \
		--top-k $${V14B_TOPIC_REGRESSION_TOP_K:-80} \
		--out-dir reports/v14b_pilot

## Access audit: key turning / branch driver / future endpoint access gaps
access-audit:
	@echo ">>> Access audit: decision-critical paper links..."
	$(PYTHON) -m echelon.v14b.access_link_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		--limit $${V14B_ACCESS_AUDIT_LIMIT:-12000}

## Step 5b recovery: restore run-level rolling backtest audit from trusted checkpoint
recover-vgae-calibration-audit:
	@echo ">>> Recover Step5b run-level calibration audit from trusted checkpoint..."
	$(PYTHON) -m echelon.v14b.recover_vgae_calibration_audit \
		--db-v14 $(DB_V14) \
		--checkpoint reports/v14b_pilot/checkpoints/step5b_vgae.done.json \
		$${V14B_RECOVER_VGAE_CALIBRATION_FORCE:+--force}

## Future candidate lifecycle audit: GNN edge -> Step6 -> Claim Card -> Radar
future-lifecycle-audit:
	@echo ">>> Future candidate lifecycle audit: candidate generator to Radar gates..."
	$(PYTHON) -m echelon.v14b.future_candidate_lifecycle \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot

## Direction readiness audit: Step5b -> Step6 -> Step13 promotion gates
direction-readiness-audit:
	@echo ">>> Direction readiness audit: future candidates -> Claim Cards..."
	$(PYTHON) -m echelon.v14b.direction_readiness_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot

## Value delivery audit: eight gates from graph demo to decision system
value-delivery-audit:
	@echo ">>> Value delivery audit: evidence, lineage, calibration, Topic Dossier, multi-corpus..."
	$(PYTHON) -m echelon.v14b.value_delivery_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		--repo-root .

## Algorithm logic audit: 逐步审计算法角色、输入输出、promotion guard
algorithm-logic-audit:
	@echo ">>> Algorithm logic audit: step-by-step first-principles fit..."
	$(PYTHON) -m echelon.v14b.algorithm_logic_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		--repo-root .

## Decision audit: current acceptance loop for Topic Dossier / Evidence Map / Claim Card
decision-audit:
	@echo ">>> Decision audit: benchmark regression -> gap queue -> readiness -> value delivery..."
	$(MAKE) topic-regression
	$(MAKE) section-queue-audit
	$(MAKE) topic-gap-section-audit
	$(MAKE) topic-gap-no-target-inspect
	$(MAKE) cited-work-backfill-queue
	$(MAKE) raw-pdf-store-audit
	$(MAKE) topic-gap-raw-pdf-inspect
	$(MAKE) direction-readiness-audit
	$(MAKE) algorithm-logic-audit
	$(MAKE) value-delivery-audit

## Evidence bone audit: unlinked refs + high-value section coverage + frontfill log taxonomy
evidence-bone-audit:
	@echo ">>> Evidence bone audit: reference and section evidence failure taxonomy..."
	$(PYTHON) -m echelon.v14b.evidence_bone_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot

## LEGACY compatibility: Step 1 OpenAlex enrich; not current V14B decision workflow
enrich:
	@echo ">>> LEGACY compatibility target: Step 1 OpenAlex Enrich..."
	@echo ">>> Not current V14B decision workflow; prefer product-chain or post-frontfill-chain."
	$(PYTHON) -m echelon.v14b.step1_enrich \
		--db $(DB_MAIN) \
		--concurrency $${V14B_CONCURRENCY:-10} \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 2: SPC Main Path (~2h)
mainpath:
	@echo ">>> Step 2: SPC Main Path..."
	$(PYTHON) -m echelon.v14b.step2_mainpath \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 3: V14 调权 KeystoneScore (~1h)
keystone:
	@echo ">>> Step 3: V14 KeystoneScore..."
	$(PYTHON) -m echelon.v14b.step3_keystone_v14 \
		--db $(DB_MAIN) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 4: 子图构建 (~0.5h)
subgraph:
	@echo ">>> Step 4: 子图构建..."
	$(PYTHON) -m echelon.v14b.step4_subgraph \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5a: SciBERT 引用功能分类 (~4h)
scibert:
	@echo ">>> Step 5a: SciBERT 引用功能分类..."
	$(PYTHON) -m echelon.v14b.step5a_scibert \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5b: VGAE 训练 + calibrated future candidate generator (~4h)
vgae:
	@echo ">>> Step 5b: VGAE future candidate generator..."
	$(PYTHON) -m echelon.v14b.step5b_vgae \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s: 章节证据入库 (paper_sections)
section-evidence:
	@echo ">>> Step 5s: Section evidence ingestion..."
	$(PYTHON) -m echelon.v14b.step5s_section_ingest \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--top-n $${V14B_SECTION_INGEST_TOP_N:-1200} \
		--raw-pdf-store-root "$${V14B_RAW_PDF_STORE_ROOT:-/Volumes/LaCie/Echelon_Paper_Raw_Data}" \
		--raw-pdf-manifest "$${V14B_RAW_PDF_MANIFEST:-/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3}" \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s-delta: 从高价值 delta queue 精准补 section
section-evidence-delta:
	@echo ">>> Step 5s: Section evidence delta queue ingestion..."
	$(PYTHON) -m echelon.v14b.step5s_section_ingest \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--top-n $${V14B_SECTION_DELTA_TOP_N:-12000} \
		--candidate-file $${V14B_SECTION_DELTA_QUEUE:-data/v14b/section_delta_queue.csv} \
		--raw-pdf-store-root "$${V14B_RAW_PDF_STORE_ROOT:-/Volumes/LaCie/Echelon_Paper_Raw_Data}" \
		--raw-pdf-manifest "$${V14B_RAW_PDF_MANIFEST:-/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3}" \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s-topic-gaps: 从 multi-topic regression 缺口精准补 section
section-evidence-topic-gaps:
	@echo ">>> Step 5s: Topic evidence-gap section ingestion..."
	$(PYTHON) -m echelon.v14b.step5s_section_ingest \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--top-n $${V14B_TOPIC_GAP_SECTION_TOP_N:-1000} \
		--candidate-file $${V14B_TOPIC_GAP_SECTION_QUEUE:-reports/v14b_pilot/multi_topic_evidence_gap_queue.csv} \
		--raw-pdf-store-root "$${V14B_RAW_PDF_STORE_ROOT:-/Volumes/LaCie/Echelon_Paper_Raw_Data}" \
		--raw-pdf-manifest "$${V14B_RAW_PDF_MANIFEST:-/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3}" \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s-topic-gaps-local: 只消费外接盘/本地 raw PDF, 不触发网络下载
section-evidence-topic-gaps-local:
	@echo ">>> Step 5s: Topic evidence-gap local raw PDF ingestion..."
	$(PYTHON) -m echelon.v14b.step5s_section_ingest \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--top-n $${V14B_TOPIC_GAP_SECTION_TOP_N:-1000} \
		--candidate-file $${V14B_TOPIC_GAP_SECTION_QUEUE:-reports/v14b_pilot/multi_topic_evidence_gap_queue.csv} \
		--raw-pdf-store-root "$${V14B_RAW_PDF_STORE_ROOT:-/Volumes/LaCie/Echelon_Paper_Raw_Data}" \
		--raw-pdf-manifest "$${V14B_RAW_PDF_MANIFEST:-/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3}" \
		--local-raw-pdf-only \
		--refresh-local-raw-pdf \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s-a: section evidence atoms + exact FTS search substrate
section-atoms:
	@echo ">>> Step 5s-a: Section evidence atoms and exact search..."
	$(PYTHON) -m echelon.v14b.section_atoms \
		--db $(DB_MAIN) \
		--max-atoms-per-section $${V14B_SECTION_ATOM_MAX_PER_SECTION:-12} \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s-a2: section atom deterministic vector embeddings for fuzzy candidate recall
section-atom-embeddings:
	@echo ">>> Step 5s-a2: Section atom fuzzy recall embeddings..."
	$(PYTHON) -m echelon.v14b.section_atoms \
		--db $(DB_MAIN) \
		--skip-atom-build \
		--build-embeddings \
		--embedding-rebuild \
		--embedding-dim $${V14B_SECTION_ATOM_EMBEDDING_DIM:-256} \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5s-b: section atom typed chain substrate
section-atom-chains:
	@echo ">>> Step 5s-b: Section atom typed chains..."
	$(PYTHON) -m echelon.v14b.section_atom_chains \
		--db $(DB_MAIN) \
		--max-chains-per-section $${V14B_SECTION_ATOM_CHAIN_MAX_PER_SECTION:-3} \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Raw PDF store audit: 外接盘下载库 -> section ingest 复用状态
raw-pdf-store-audit:
	@echo ">>> Raw PDF store audit: manifest progress and section reuse..."
	$(PYTHON) -m echelon.v14b.raw_pdf_store_audit \
		--db $(DB_MAIN) \
		--store-root $${V14B_RAW_PDF_STORE_ROOT:-/Volumes/LaCie/Echelon_Paper_Raw_Data} \
		--manifest $${V14B_RAW_PDF_MANIFEST:-/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3} \
		--candidate-file $${V14B_TOPIC_GAP_SECTION_QUEUE:-reports/v14b_pilot/multi_topic_evidence_gap_queue.csv} \
		--out-dir reports/v14b_pilot \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Topic gap repair: regression gaps -> queue refresh -> targeted ingest -> re-audit
topic-gap-repair:
	@echo ">>> Topic gap repair: refresh gaps, ingest targeted sections, then re-audit..."
	$(PYTHON) scripts/guard_topic_gap_repair.py
	$(MAKE) topic-regression
	$(MAKE) section-queue-audit
	$(MAKE) topic-gap-section-audit
	$(MAKE) section-evidence-topic-gaps
	$(MAKE) topic-regression
	$(MAKE) section-queue-audit
	$(MAKE) topic-gap-section-audit
	$(MAKE) direction-readiness-audit
	$(MAKE) value-delivery-audit

## Step 5s-audit: 高价值 section 队列覆盖审计 + delta queue
section-queue-audit:
	@echo ">>> Step 5s audit: high-value section queue coverage..."
	$(PYTHON) -m echelon.v14b.step5s_section_queue_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--top-n $${V14B_SECTION_INGEST_TOP_N:-12000} \
		$${V14B_SECTION_AUDIT_TOPIC_ARGS:-}

## Topic-gap section audit: 将 multi-topic section 缺口分类成可行动桶
topic-gap-section-audit:
	@echo ">>> Topic-gap section evidence audit: classify benchmark-topic section blockers..."
	$(PYTHON) -m echelon.v14b.topic_gap_section_evidence_audit \
		--db $(DB_MAIN) \
		--topic-gap-queue $${V14B_TOPIC_GAP_SECTION_QUEUE:-reports/v14b_pilot/multi_topic_evidence_gap_queue.csv} \
		--out-dir reports/v14b_pilot

## Topic-gap no-target inspect: 只读检查当前 parser no-target PDF 是否真有目标 heading
topic-gap-no-target-inspect:
	@echo ">>> Topic-gap no-target inspection: check PDF heading signals without writing DB..."
	$(PYTHON) -m echelon.v14b.topic_gap_no_target_inspection \
		--db $(DB_MAIN) \
		--triage-json reports/v14b_pilot/topic_gap_section_evidence_audit.json \
		--out-dir reports/v14b_pilot \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Topic-gap raw PDF inspect: 只读解析外接盘已命中的 topic-gap PDF
topic-gap-raw-pdf-inspect:
	@echo ">>> Topic-gap raw PDF parser inspection: local cache dry run..."
	$(PYTHON) -m echelon.v14b.topic_gap_raw_pdf_inspection \
		--db $(DB_MAIN) \
		--triage-json reports/v14b_pilot/topic_gap_section_evidence_audit.json \
		--store-root $${V14B_RAW_PDF_STORE_ROOT:-/Volumes/LaCie/Echelon_Paper_Raw_Data} \
		--manifest $${V14B_RAW_PDF_MANIFEST:-/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3} \
		--out-dir reports/v14b_pilot \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## 前置补齐完成后，从证据门槛断点推进产品链
post-frontfill-chain:
	@echo ">>> Post-frontfill product chain gate..."
	$(PYTHON) scripts/run_after_frontfill_product_chain.py \
		--repo-root . \
		--db-main $(DB_MAIN) \
		--db-v14 $(DB_V14)

## Step 5c: section-first limitation tracking; LLM opt-in only for weak traced assistance
limitation:
	@echo ">>> Step 5c: Limitation Tracking..."
	$(PYTHON) -m echelon.v14b.step5c_limitation \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 6: 三路融合 (~1h)
fusion:
	@echo ">>> Step 6: 三路融合..."
	$(PYTHON) -m echelon.v14b.step6_fusion \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG)

## Step 7: 三色突变标记 (~0.5h)
mutation:
	@echo ">>> Step 7: 三色突变标记..."
	$(PYTHON) -m echelon.v14b.step7_mutation \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG)

## Step 8: UMAP-3D 布局 (~2h)
layout:
	@echo ">>> Step 8: UMAP-3D 布局..."
	$(PYTHON) -m echelon.v14b.step8_layout \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG)

## Step 9: 生成验证报告
report:
	@echo ">>> Step 9: 生成报告..."
	$(PYTHON) -m echelon.v14b.step9_report \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG)
	@echo ""
	@echo "✅ 报告生成完成:"
	@echo "   reports/v14b_pilot/V14B_Evidence_Decision_算法验证报告.md"
	@echo "   reports/v14b_pilot/未来候选方向_证据合同报告.md"

## Step 10: 构建 2.5D visual graph product layer
visual-graph:
	@echo ">>> Step 10: Visual graph builder..."
	$(PYTHON) -m echelon.v14b.step10_visual_graph_builder \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)
	@echo ">>> Visual graph tables ready: visual_nodes / visual_edges / visual_clusters / branch_lineages / visual_tiles / visual_search_fts"

## Step 13: 第一性原理 + 卡点历史脉络
first-principles:
	@echo ">>> Step 13: 第一性原理 + 卡点历史脉络..."
	$(PYTHON) -m echelon.v14b.step13_first_principles_history \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		$(CORPUS_ARG)

## Step 12: 目标对齐审计报告
goal-audit:
	@echo ">>> Step 12: Goal alignment audit..."
	$(PYTHON) -m echelon.v14b.step12_goal_alignment_audit \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--out-dir reports/v14b_pilot \
		$(CORPUS_ARG)

## Step 11a: 分层 LLM/Doubao 审边计划与预算,不调用 API
llm-edge-audit-plan:
	@echo ">>> Step 11a: Stratified LLM edge audit plan (no API calls)..."
	$(PYTHON) -m echelon.v14b.step11_llm_edge_audit \
		--db-v14 $(DB_V14) \
		--sample-per-layer $${V14B_LLM_EDGE_AUDIT_LAYER_SAMPLE:-2000} \
		--extra-sample $${V14B_LLM_EDGE_AUDIT_EXTRA_SAMPLE:-8000} \
		--branch-mode $${V14B_LLM_EDGE_AUDIT_BRANCH_MODE:-all} \
		--branch-sample $${V14B_LLM_EDGE_AUDIT_BRANCH_SAMPLE:-3000}

## Step 11b: 执行分层 LLM/Doubao 审边,默认最多 100 条; V14B_LLM_EDGE_AUDIT_MAX_CALLS=0 表示跑完
llm-edge-audit-run:
	@echo ">>> Step 11b: Execute stratified LLM edge audit..."
	$(PYTHON) -m echelon.v14b.step11_llm_edge_audit \
		--db-v14 $(DB_V14) \
		--job-id "$${V14B_LLM_EDGE_AUDIT_JOB_ID:?Set V14B_LLM_EDGE_AUDIT_JOB_ID from llm-edge-audit-plan}" \
		--provider $${LLM_PROVIDER:-doubao} \
		--execute \
		--max-calls $${V14B_LLM_EDGE_AUDIT_MAX_CALLS:-100}

# -------------------------------------------------------
# 当前证据约束产品链路与 legacy 兼容入口
# -------------------------------------------------------

## 快速产品链路: 不等待 OpenAlex backfill, 仅用于调试/冒烟验证
product-chain-fast: id-repair graph-features embeddings quality-audit reset-pilot mainpath keystone subgraph scibert vgae section-evidence section-atoms section-atom-chains limitation fusion first-principles mutation layout report visual-graph goal-audit
	@echo ""
	@echo "======================================"
	@echo "✅ V14-B Fast Visual Graph 产品链路完成!"
	@echo "======================================"
	@echo "报告位置:"
	@echo "  reports/v14b_pilot/V14B_Evidence_Decision_算法验证报告.md"
	@echo "  reports/v14b_pilot/未来候选方向_证据合同报告.md"
	@echo "数据库:"
	@echo "  db/v14_pilot.sqlite3"

## 交付目标产物链路: 先补齐 OpenAlex/section 证据，再生成图谱与方向
product-chain: id-repair graph-prep quality-audit reset-pilot mainpath keystone subgraph scibert vgae evidence-prep limitation fusion first-principles mutation layout report visual-graph goal-audit
	$(MAKE) decision-audit
	@echo ""
	@echo "======================================"
	@echo "✅ V14-B Evidence Decision 产品链路完成!"
	@echo "======================================"
	@echo "报告位置:"
	@echo "  reports/v14b_pilot/V14B_Evidence_Decision_算法验证报告.md"
	@echo "  reports/v14b_pilot/未来候选方向_证据合同报告.md"
	@echo "数据库:"
	@echo "  db/v14_pilot.sqlite3"

## LEGACY compatibility: old pilot graph rerun; not current V14B decision workflow
pilot: pilot-graph
	@echo ">>> LEGACY compatibility alias finished; prefer product-chain or post-frontfill-chain for acceptance."

## LEGACY compatibility: old pilot graph rerun; not current V14B decision workflow
pilot-graph: id-repair openalex-backfill graph-features embeddings quality-audit reset-pilot mainpath keystone subgraph scibert vgae section-evidence limitation fusion first-principles mutation layout report
	@echo ""
	@echo "LEGACY compatibility target; not current V14B decision workflow."
	@echo "======================================"
	@echo "✅ V14-B Pilot 图谱重跑完成!"
	@echo "======================================"
	@echo "报告位置:"
	@echo "  reports/v14b_pilot/V14B_Evidence_Decision_算法验证报告.md"
	@echo "  reports/v14b_pilot/未来候选方向_证据合同报告.md"
	@echo "数据库:"
	@echo "  db/v14_pilot.sqlite3"

## LEGACY compatibility: old enrich + pilot visual full flow; not current V14B decision workflow
pilot-full: enrich pilot-visual
	@echo ""
	@echo "LEGACY compatibility target; not current V14B decision workflow."
	@echo "======================================"
	@echo "✅ V14-B Pilot 全流程完成!"
	@echo "======================================"

## LEGACY compatibility: old pilot visual rerun; not current V14B decision workflow
pilot-visual: pilot-graph visual-graph goal-audit

# LEGACY compatibility: old quick debug pilot; not current V14B decision workflow
pilot-debug:
	V14B_LIMIT=100 $(MAKE) pilot-graph

## 季度增量更新 + 全链路重跑 + snapshot 对比
quarterly-run:
	@if [ -z "$${V14B_CORPUS_ID}" ]; then echo "❌ 请先设置 V14B_CORPUS_ID (如 optics/cs/materials)"; exit 2; fi
	@set_spec="$${V14B_CORPUS_SET_SPEC:-}"; \
	if [ -z "$$set_spec" ]; then \
		case "$${V14B_CORPUS_ID}" in \
			optics) set_spec="physics:physics:optics" ;; \
			cs) set_spec="cs:cs" ;; \
			materials) set_spec="cond-mat:cond-mat.mtrl-sci" ;; \
			*) set_spec="physics:physics:optics" ;; \
		esac; \
	fi; \
	echo ">>> quarterly-run corpus=$${V14B_CORPUS_ID} set_spec=$$set_spec threads=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} embed_batch=$${V14B_Q_EMBED_BATCH:-$(V14B_Q_EMBED_BATCH)}"; \
	OMP_NUM_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	VECLIB_MAXIMUM_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	MKL_NUM_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	NUMEXPR_NUM_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	V14B_EMBEDDING_BATCH_SIZE=$${V14B_Q_EMBED_BATCH:-$(V14B_Q_EMBED_BATCH)} \
	$(PYTHON) -m echelon.v14b.quarterly_run \
		--corpus-id $${V14B_CORPUS_ID} \
		--corpus-name $${V14B_CORPUS_NAME:-$${V14B_CORPUS_ID}} \
		--provider $${V14B_CORPUS_PROVIDER:-arxiv} \
		--set-spec "$$set_spec" \
		--db $(DB_MAIN) \
		--db-v14 $(DB_V14) \
		--report-dir reports/v14b_pilot \
		$(if $(V14B_QUARTER_ID),--quarter-id $(V14B_QUARTER_ID),) \
		$(if $(V14B_FROM_DATE),--from-date $(V14B_FROM_DATE),) \
		$(if $(V14B_TO_DATE),--to-date $(V14B_TO_DATE),) \
		$(if $(V14B_MAX_RESULTS),--max-results $(V14B_MAX_RESULTS),) \
		$(if $(V14B_SKIP_CRAWL),--skip-crawl,)

## 季度模板: optics（默认 set-spec + 资源参数）
quarterly-run-optics:
	@V14B_CORPUS_ID=optics \
	V14B_CORPUS_NAME=optics \
	V14B_CORPUS_PROVIDER=arxiv \
	V14B_CORPUS_SET_SPEC=$${V14B_CORPUS_SET_SPEC:-physics:physics:optics} \
	V14B_Q_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	V14B_Q_EMBED_BATCH=$${V14B_Q_EMBED_BATCH:-$(V14B_Q_EMBED_BATCH)} \
	$(MAKE) quarterly-run

## 季度模板: cs（默认 set-spec + 资源参数）
quarterly-run-cs:
	@V14B_CORPUS_ID=cs \
	V14B_CORPUS_NAME=computer_science \
	V14B_CORPUS_PROVIDER=arxiv \
	V14B_CORPUS_SET_SPEC=$${V14B_CORPUS_SET_SPEC:-cs:cs} \
	V14B_Q_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	V14B_Q_EMBED_BATCH=$${V14B_Q_EMBED_BATCH:-$(V14B_Q_EMBED_BATCH)} \
	$(MAKE) quarterly-run

## 季度模板: materials（默认 set-spec + 资源参数）
quarterly-run-materials:
	@V14B_CORPUS_ID=materials \
	V14B_CORPUS_NAME=materials_science \
	V14B_CORPUS_PROVIDER=arxiv \
	V14B_CORPUS_SET_SPEC=$${V14B_CORPUS_SET_SPEC:-cond-mat:cond-mat.mtrl-sci} \
	V14B_Q_THREADS=$${V14B_Q_THREADS:-$(V14B_Q_THREADS)} \
	V14B_Q_EMBED_BATCH=$${V14B_Q_EMBED_BATCH:-$(V14B_Q_EMBED_BATCH)} \
	$(MAKE) quarterly-run

# -------------------------------------------------------
# 清理
# -------------------------------------------------------

## 清理 checkpoint 和日志 (允许重跑)
clean:
	@echo ">>> 清理 checkpoints 和日志..."
	rm -rf logs/v14b/
	rm -rf reports/v14b_pilot/checkpoints/
	@echo "✅ 清理完成 (DB 和报告已保留)"

## 清理所有 V14-B 数据 (慎用)
clean-all: clean
	rm -f $(DB_V14)
	rm -f reports/v14b_pilot/*.md
	@echo "✅ 全部清理完成"

# -------------------------------------------------------
# 测试
# -------------------------------------------------------

## 运行 V14-B 测试套件
test:
	$(PYTHON) -m pytest tests/v14b/ -v --tb=short

## 运行测试 (快速,跳过慢测试)
test-fast:
	$(PYTHON) -m pytest tests/v14b/ -v --tb=short -m "not slow"

# -------------------------------------------------------
# 帮助
# -------------------------------------------------------

## 显示此帮助
help:
	@echo "Echelon V14-B Evidence Decision Workflow"
	@echo ""
	@echo "可用命令:"
	@awk '/^## / {help=substr($$0, 4); next} /^[a-zA-Z_-]+:/ && help {split($$1, target, ":"); printf "  %-20s %s\n", target[1], help; help=""}' $(MAKEFILE_LIST)
	@echo ""
	@echo "环境变量:"
	@echo "  V14B_LIMIT=100     只跑前 N 条 (调试)"
	@echo "  V14B_CONCURRENCY=5 降低并发 (慢但稳)"
	@echo ""
	@echo "例子:"
	@echo "  make setup"
	@echo "  make product-chain             # 当前证据约束产品链路"
	@echo "  make post-frontfill-chain      # section/frontfill 完成后的断点推进"
	@echo "  make decision-audit            # 当前验收闭环: regression/gap/readiness/value"
	@echo "  make topic-gap-repair          # 精准修复 multi-topic evidence gap"
	@echo "  make topic-gap-section-audit   # 分类 multi-topic section evidence 缺口"
	@echo "  make topic-gap-no-target-inspect # 只读检查 no-target PDF heading 信号"
	@echo "  make raw-pdf-store-audit # 检查外接盘 raw PDF 库及 section 复用状态"
	@echo "  make topic-gap-raw-pdf-inspect # 只读解析本地 topic-gap PDF"
	@echo "  make section-atoms             # 从 paper_sections 生成可检索证据 atoms"
	@echo "  make section-atom-chains       # 从 section atoms 生成 typed bottleneck chains"
	@echo "  make algorithm-logic-audit     # 逐步审计算法角色、输入输出和 promotion guard"
	@echo "  make cited-work-backfill-queue # 精准生成 missing cited-work 补齐队列"
	@echo "  make cited-work-backfill       # 小批量处理 exact-ID missing cited works"
	@echo "  make value-delivery-audit      # 证据边界与交付门槛审计"
	@echo ""
	@echo "Legacy compatibility (not current acceptance path):"
	@echo "  make pilot                     # old graph rerun compatibility target"
	@echo "  make pilot-full                # old enrich + pilot flow; not current V14B decision workflow"

.DEFAULT_GOAL := help
