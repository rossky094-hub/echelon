# ========================================================
# Echelon V14-B 演化树 Pilot — Makefile
# 平台: macOS Apple Silicon (M1/M2/M3)
#
# 快速开始:
#   make setup           # 安装依赖
#   cp .env.example .env # 配置环境变量
#   make pilot           # 从当前 library 干净重跑图谱
#   make pilot-full      # 包含 enrich 的一键全流程
#
# 查看帮助:
#   make help
# ========================================================

.PHONY: setup id-repair openalex-backfill graph-features embeddings evidence-prep graph-prep reset-pilot quality-audit enrich mainpath keystone subgraph scibert vgae section-evidence limitation \
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
	@echo "   make pilot-full  # 包含 enrich 的全流程"

# -------------------------------------------------------
# 各 Step
# -------------------------------------------------------

## Step 0.2: Provider ID repair + reference relinking
id-repair:
	@echo ">>> Step 0.2: Provider ID repair + reference relinking..."
	$(PYTHON) -m echelon.v14b.step0_id_repair \
		--db $(DB_MAIN) \
		$(CORPUS_ARG)

## Step 0.25: OpenAlex Field/Topic backfill
openalex-backfill:
	@echo ">>> Step 0.25: OpenAlex Field/Topic backfill..."
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
evidence-prep: openalex-backfill section-evidence
	@echo ">>> Evidence prep done: OpenAlex backfill + section evidence are complete for configured scope."

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

## Step 1: OpenAlex enrich 13606 篇 (~1.5h)
enrich:
	@echo ">>> Step 1: OpenAlex Enrich..."
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

## Step 5b: VGAE 训练 + Link Prediction (~4h)
vgae:
	@echo ">>> Step 5b: VGAE 训练..."
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
		$(CORPUS_ARG) \
		$(if $(V14B_LIMIT),--limit $(V14B_LIMIT),)

## Step 5c: Limitation Tracking (~4h, ~$40 LLM 费用)
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
	@echo "   reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
	@echo "   reports/v14b_pilot/未来方向预测_交集报告.md"

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
# 一键流程
# -------------------------------------------------------

## 快速产品链路: 不等待 OpenAlex backfill, 仅用于调试/冒烟验证
product-chain-fast: id-repair graph-features embeddings quality-audit reset-pilot mainpath keystone subgraph scibert vgae section-evidence limitation fusion first-principles mutation layout report visual-graph goal-audit
	@echo ""
	@echo "======================================"
	@echo "✅ V14-B Fast Visual Graph 产品链路完成!"
	@echo "======================================"
	@echo "报告位置:"
	@echo "  reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
	@echo "  reports/v14b_pilot/未来方向预测_交集报告.md"
	@echo "数据库:"
	@echo "  db/v14_pilot.sqlite3"

## 交付目标产物链路: 先补齐 OpenAlex/section 证据，再生成图谱与方向
product-chain: id-repair graph-prep quality-audit reset-pilot mainpath keystone subgraph scibert vgae evidence-prep limitation fusion first-principles mutation layout report visual-graph goal-audit
	@echo ""
	@echo "======================================"
	@echo "✅ V14-B Visual Graph 产品链路完成!"
	@echo "======================================"
	@echo "报告位置:"
	@echo "  reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
	@echo "  reports/v14b_pilot/未来方向预测_交集报告.md"
	@echo "数据库:"
	@echo "  db/v14_pilot.sqlite3"

## 从当前 library 干净重跑图谱 (enrich 已单独完成时使用)
pilot: pilot-graph

## 从当前 library 干净重跑图谱 (enrich 已单独完成时使用)
pilot-graph: id-repair openalex-backfill graph-features embeddings quality-audit reset-pilot mainpath keystone subgraph scibert vgae section-evidence limitation fusion first-principles mutation layout report
	@echo ""
	@echo "======================================"
	@echo "✅ V14-B Pilot 图谱重跑完成!"
	@echo "======================================"
	@echo "报告位置:"
	@echo "  reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
	@echo "  reports/v14b_pilot/未来方向预测_交集报告.md"
	@echo "数据库:"
	@echo "  db/v14_pilot.sqlite3"

## 包含 enrich 的一键全流程 (预计 15-21h, ~$45 LLM)
pilot-full: enrich pilot-visual
	@echo ""
	@echo "======================================"
	@echo "✅ V14-B Pilot 全流程完成!"
	@echo "======================================"

## 干净重跑图谱并构建 2.5D 可视化产品层
pilot-visual: pilot-graph visual-graph goal-audit

# 快速调试流程 (前 100 篇)
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
	@echo "Echelon V14-B 演化树 Pilot"
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
	@echo "  make enrich mainpath keystone  # 逐步运行"
	@echo "  make pilot                     # 从当前 library 干净重跑图谱"
	@echo "  make pilot-visual              # 图谱 + 2.5D 可视化产品层"
	@echo "  make pilot-full                # 包含 enrich 的全流程"
	@echo "  V14B_LIMIT=100 make pilot      # 图谱调试模式"

.DEFAULT_GOAL := help
