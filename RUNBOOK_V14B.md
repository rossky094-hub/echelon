# Echelon V14-B 演化树 Pilot — 运行手册

**版本**: V14-B-runbook-1.0  
**适用平台**: macOS Apple Silicon (M1/M2/M3)  
**Python 版本**: 3.11+

---

## 目录

1. [系统需求](#1-系统需求)
2. [安装步骤](#2-安装步骤)
3. [环境变量配置](#3-环境变量配置)
4. [一键运行](#4-一键运行)
5. [逐步运行](#5-逐步运行)
6. [每个 Step 详情](#6-每个-step-详情)
7. [Checkpoint 恢复](#7-checkpoint-恢复)
8. [常见错误诊断](#8-常见错误诊断)
9. [调优手册](#9-调优手册)
10. [报告解读](#10-报告解读)
11. [预估成本](#11-预估成本)
12. [多 Corpus 与季度更新](#12-多-corpus-与季度更新)
13. [Topic Lens 查询接口](#13-topic-lens-查询接口)

---

## 1. 系统需求

| 项目 | 最低要求 | 推荐 |
|---|---|---|
| 操作系统 | macOS 13+ (Ventura) | macOS 14+ (Sonoma) |
| 芯片 | Apple M1 | Apple M2/M3 |
| RAM | 16 GB | 32 GB |
| 磁盘 | 10 GB 可用 | 20 GB 可用 |
| Python | 3.11 | 3.12 |
| 网络 | 需要访问 OpenAlex / LLM API | - |

**注**: 代码已针对 MPS (Metal Performance Shaders) 优化,无需 NVIDIA GPU。

---

## 2. 安装步骤

### 2.1 准备 Python 环境

```bash
# 建议使用虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 确认 Python 版本
python --version  # 应为 3.11.x 或 3.12.x
```

### 2.2 安装依赖

```bash
cd "/Users/r/Documents/New project/echelon/echelon-v14b"
make setup
```

`make setup` 自动执行:
1. `pip install -r requirements-v14b.txt`
2. `python -m echelon.v14b.utils check_env` (环境检查)

### 2.3 验证安装

```bash
python -m echelon.v14b.utils check_env
```

预期输出:
```
✅ Python 3.11.x (需要 >= 3.11)
✅ Apple Silicon 检测到
✅ PyTorch 2.x.x
✅ MPS 可用
✅ DB: db/echelon_library.sqlite3 (84.3 MB)
```

---

## 3. 环境变量配置

```bash
cp .env.example .env
```

编辑 `.env` 文件:

### 方案 A: Anthropic (推荐)

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
OPENALEX_EMAIL=your_email@example.com
```

### 方案 B: OpenAI

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
OPENALEX_EMAIL=your_email@example.com
```

### 方案 C: Ollama 本地 (零成本)

```bash
# 先安装 Ollama: https://ollama.ai/
# 拉取模型:
ollama pull qwen2.5:14b

# .env 配置:
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OPENALEX_EMAIL=your_email@example.com
```

**激活环境变量**:
```bash
# 手动加载 (或用 python-dotenv 自动加载)
export $(cat .env | grep -v '^#' | xargs)
```

---

## 4. 一键运行

```bash
make pilot
```

预计总耗时(Mac M2, 16GB RAM):
- **全量** (13606 篇): ~15-21 小时
- **调试模式** (前 100 篇): ~30 分钟

调试模式:
```bash
V14B_LIMIT=100 make pilot
# 或
make pilot-debug
```

---

## 5. 逐步运行

推荐顺序(必须按此顺序):

```bash
make enrich      # Step 1: ~1.5h
make mainpath    # Step 2: ~2h  (需 Step 1 完成)
make keystone    # Step 3: ~1h  (需 Step 1 完成)
make subgraph    # Step 4: ~0.5h (需 Steps 1,2,3 完成)
make scibert     # Step 5a: ~4h  (需 Step 4 完成)
make vgae        # Step 5b: ~4h  (需 Step 4 完成)
make section-atoms           # Step 5s-a: section atoms + exact FTS/BM25
make section-atom-embeddings # Step 5s-a2: atom fuzzy recall embeddings
make section-atom-chains     # Step 5s-b: typed evidence chains
make limitation  # Step 5c: ~4h  (需 Step 4 完成)
make fusion      # Step 6: ~1h  (需 Steps 5a,5b,5c 完成)
make mutation    # Step 7: ~0.5h (需 Step 4 完成)
make layout      # Step 8: ~2h  (需 Step 4 完成)
make report      # Step 9: ~0.1h (需所有 Steps 完成)
```

---

## 6. 每个 Step 详情

### Step 1: OpenAlex Enrich

```bash
make enrich
# 或
python -m echelon.v14b.step1_enrich --db db/echelon_library.sqlite3 --concurrency 10
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~1.5h (10 并发) |
| LLM 成本 | $0 (OpenAlex 免费) |
| 输出表 | papers (更新), paper_references, topics_hierarchy, affiliations |
| Checkpoint | checkpoints/step1_enrich.done.json |
| 验收标准 | enrich 成功率 > 95%, paper_references 非空率 > 90% |

**输出文件**:
- `db/echelon_library.sqlite3` (更新 papers 表的 openalex_id, cited_by_count 等列)

---

### Step 2: SPC Main Path

```bash
make mainpath
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | 全量通常为分钟级到小时级,取决于 linked refs |
| LLM 成本 | $0 |
| 算法 | Batagelj 2003 SPC + SCC condensation DAG + V13 边权乘积 |
| 输出表 | main_path_edges, main_path_cycle_audit, main_path_edge_audit (v14_pilot.sqlite3) |
| 验收标准 | 主干道节点 100-200 个,连接从 1991 到 2026 |

**算法约束**:
- SPC 依赖 DAG,不得用逐环 `remove_edge` 或 paper id / ULID 排序强行制造时间顺序。
- 真实引用边方向为 `cited -> citing`。明确时间倒置的边跳过。
- 同年、同日、未知精度造成的循环引用保留为强连通分量,先压缩为 condensation DAG 后计算 SPC。
- 循环分量写入 `main_path_cycle_audit`; 组件边展开到论文边的审计写入 `main_path_edge_audit`。

**当前全量参考结果**: 55,391 nodes, 277,343 time-forward edges, 66 cyclic SCCs / 138 nodes / 148 intra-cycle edges, 277,195 written main path candidate edges.

**内存预估**: ~1-2GB (55k 节点 + 27 万级 time-forward edges)

如果 OOM:
```bash
V14B_LIMIT=5000 make mainpath
```

---

### Step 3: V14 调权 KeystoneScore

```bash
make keystone
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~1h |
| 算法 | V14 生命周期自适应加权调和均值 |
| 输出 | papers.keystone_score_v14, papers.lifecycle_v14 |
| V14 vs V13 | V14 加重 bridging + cd_subdomain,弱化 recency |

---

### Step 4: 子图构建

```bash
make subgraph
```

选取策略:
1. Top 1000 by `keystone_score_v14`
2. Top 500 fresh (2024+ 年)
3. 以上 1500 节点的 1 度邻居 (~1500)

预期输出: **~3000 节点, ~30000-80000 边**

---

### Step 5a: SciBERT 引用功能分类

```bash
make scibert
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~4h (CPU 推理) |
| 模型 | facebook/bart-large-mnli (zero-shot) 或 LLM 降级 |
| 分类标签 | extension / motivation / usage / similarity / background / future_work |
| 降级模式 | SciBERT 不可用时自动用 LLM (加 --use-llm 强制) |

强制 LLM 模式:
```bash
python -m echelon.v14b.step5a_scibert --use-llm
```

---

### Step 5b: VGAE 训练

```bash
make vgae
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~4h (MPS GPU / CPU) |
| 架构 | 2 层 GCN (797→256→128) + dot product decoder |
| 节点特征 | abstract_emb(768) + year + cite_log + keystone + field_onehot(26) |
| 目标 | val AUC > 0.85, 输出 top 200 预测边 |

调整超参(在 `echelon/v14b/config.py`):
```python
VGAE_EPOCHS = 200        # 减小: 50-100 可快速调试
VGAE_EARLY_STOP_PATIENCE = 20
VGAE_PREDICT_THRESHOLD = 0.7
```

---

### Step 5s: Section Atom Evidence Substrate

```bash
make section-atoms
make section-atom-embeddings
make section-atom-chains
```

| 项目 | 说明 |
|---|---|
| 输入 | paper_sections, local raw PDF provenance when available |
| 输出表 | section_atoms, section_atoms_fts, section_atom_embeddings, section_atom_chains |
| 精准搜索 | ID/section/title/FTS/BM25/phrase hit,用于证据链硬证据入口 |
| 模糊搜索 | deterministic atom embedding recall,只能作为 candidate recall |
| 晋升约束 | fuzzy hit 必须保持 retrieval_context_only,不能直接成为 Step13 结论 |
| 图算法边界 | GNN/VGAE 只能做候选扩展/排序/邻域发现,不能生成 atom |

### Step 5c: Limitation Tracking

```bash
make limitation
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~4h |
| LLM 成本 | ~$40 (Anthropic) / ~$35 (OpenAI) / $0 (Ollama) |
| 4 阶段 | 抽取 → 原子化 → Resolution → 排序 |
| 输出表 | limitation_atoms, limitation_resolutions |
| 中断恢复 | 每个 atom 完成后立即 commit,断点续跑安全 |

---

### Step 6: 三路融合

```bash
make fusion
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~1h |
| 输出 | future_directions 表 (top 20 方向) |
| 验收 | 交集方向数 ≥ 10 |

---

### Step 7: 三色突变标记

```bash
make mutation
```

| 颜色 | 条件 | 预期数量 |
|---|---|---|
| 🔴 红 | mature + CD-index > 0.3 | 50-100 个 |
| 🟠 橙 | 跨 Field 桥接 > p90 | 100-200 个 |
| 🟣 紫 | 18 月内 burstiness > p95 | 30-80 个 |

---

### Step 8: UMAP-3D 布局

```bash
make layout
```

| 项目 | 说明 |
|---|---|
| 预计耗时 | ~2h (含 UMAP 拟合) |
| X/Y 轴 | UMAP cosine similarity 降维 |
| Z 轴 | (year - 1991) / (2026 - 1991) |
| 输出 | subgraph_nodes.umap_x/y/z_year/node_size/color_hex |

---

### Step 9: 报告生成

```bash
make report
```

生成 2 份报告:
- `reports/v14b_pilot/V14B_Pilot_算法验证报告.md` — 13 章节
- `reports/v14b_pilot/未来方向预测_交集报告.md` — top 20 方向

---

## 7. Checkpoint 恢复

每个 step 完成后写 `reports/v14b_pilot/checkpoints/stepN.done.json`。

中断后重跑 `make pilot` 或单个 step,会自动跳过已完成的 step。

强制重跑某个 step:
```bash
# 方法 1: 删除 checkpoint
rm reports/v14b_pilot/checkpoints/step3_keystone_v14.done.json
make keystone

# 方法 2: --no-resume 参数
python -m echelon.v14b.step3_keystone_v14 --no-resume
```

查看所有 checkpoint 状态:
```bash
ls -la reports/v14b_pilot/checkpoints/
```

---

## 8. 常见错误诊断

### 8.1 OpenAlex 429 Rate Limit

```
WARNING: OpenAlex 429 rate limit, waiting Xs
```

**解决**:
```bash
# 降低并发数
V14B_CONCURRENCY=3 make enrich
# 或在 .env 中设置:
V14B_CONCURRENCY=3
```

### 8.2 VGAE OOM (内存不足)

```
RuntimeError: MPS backend out of memory
```

**解决**:
```bash
# 方法 1: 缩小子图大小
V14B_SUBGRAPH_SIZE=2000 make vgae

# 方法 2: 修改 config.py
# VGAE_HIDDEN_DIM = 128  (从 256 减小)
# VGAE_LATENT_DIM = 64   (从 128 减小)
```

### 8.3 SciBERT 模型下载慢

**解决**:
```bash
# 方法 1: 设置 HuggingFace 镜像
export HF_ENDPOINT=https://hf-mirror.com

# 方法 2: 跳过 SciBERT,直接用 LLM
make scibert  # 内部会自动降级到 LLM
# 或强制:
python -m echelon.v14b.step5a_scibert --use-llm
```

### 8.4 LLM Rate Limit

```
ERROR: RateLimitError: API rate limit exceeded
```

**解决**:
```bash
# 降低并发 (Step 5c)
# 在 config.py 中:
# LIMITATION_MAX_RESOLVERS = 20  (从 50 减小)
```

### 8.5 NetworkX SPC 超时或含环

```
# 图中含环或逐环 remove_edge 卡住
```

**解决**:
```bash
# 使用 Step2 的 SCC condensation DAG 实现,不要恢复逐环删边。
python3 -m pytest tests/v14b/test_spc_mainpath.py -q
make mainpath
```

### 8.6 ImportError: No module named 'torch_geometric'

```bash
# 重新安装 PyG
pip install torch-geometric
pip install pyg_lib torch_scatter torch_sparse -f https://data.pyg.org/whl/torch-2.2.0+cpu.html
```

### 8.7 DB 锁定错误

```
sqlite3.OperationalError: database is locked
```

**解决**:
```bash
# 确保没有其他进程在访问 DB
lsof db/echelon_library.sqlite3
# 杀掉相关进程后重试
```

---

## 9. 调优手册

所有关键超参在 `echelon/v14b/config.py` 中集中配置:

### VGAE 调优

| 超参 | 默认值 | 调优建议 |
|---|---|---|
| `VGAE_EPOCHS` | 200 | AUC 不收敛: 增到 300 |
| `VGAE_LR` | 1e-3 | 不稳定: 降到 5e-4 |
| `VGAE_BETA` | 0.5 | KL 太强: 降到 0.1 |
| `VGAE_HIDDEN_DIM` | 256 | OOM: 降到 128 |
| `VGAE_PREDICT_THRESHOLD` | 0.7 | 预测数太少: 降到 0.6 |

### 子图调优

| 超参 | 默认值 | 调优建议 |
|---|---|---|
| `SUBGRAPH_TOP_KEYSTONE` | 1000 | 减到 500 可加速 |
| `SUBGRAPH_MAX_SIZE` | 5000 | OOM 时: 减到 2000 |

### Limitation 调优

| 超参 | 默认值 | 调优建议 |
|---|---|---|
| `LIMITATION_TOP_N` | 1000 | 减到 200 可节省 LLM 费用 |
| `LIMITATION_MAX_RESOLVERS` | 50 | 减到 20 可加速 |

### 突变标记调优

```python
MUTATION_RED_CD_THRESHOLD = 0.3       # 红色 CD-index 阈值
MUTATION_ORANGE_BRIDGE_PERCENTILE = 0.90  # 橙色分位数
MUTATION_PURPLE_BURST_PERCENTILE = 0.95   # 紫色分位数
```

若标记数量不足: 降低阈值 / 降低分位数。  
若标记数量过多: 升高阈值 / 升高分位数。

---

## 10. 报告解读

### 算法验证报告 (V14B_Pilot_算法验证报告.md)

| 章节 | 关注指标 |
|---|---|
| 1. 执行摘要 | enrich 成功率 > 95%, 报告整体质量 |
| 2. Enrich 质量 | 引用关系总数 (期望 > 300k) |
| 3. Main Path | 主干道边数 100-200,从 1991 到 2026 连续 |
| 4. V14 vs V13 | top100 差异 case study,V14 更强调颠覆性 |
| 5. 子图 | 节点数 2800-3300,边数 30k-80k |
| 6. SciBERT | extension+motivation+usage 总占比 > 40% |
| 7. VGAE | val AUC > 0.85,cross-field 占比 > 30% |
| 8. Limitation | top 50 未解决 limitation 质量 |
| 9. 融合 | 三路交集方向数 ≥ 10 |
| 10. 突变 | 标记节点 100-300 个 (子图 3-10%) |
| 11. 布局 | 同 Field 聚类清晰,Z 轴连续性 |
| 12. 对比 | V14-B vs V12.5 的信息增量 |
| 13. 建议 | GO / NO-GO / REVISE 决策 |

### 未来方向报告 (未来方向预测_交集报告.md)

重点关注:
- **置信度 ≥ 0.7** 的方向
- **三路证据齐全** 的方向
- **跨 Field** 方向 (占比应 > 60%)
- **预期时间 2026-2028** 的方向 (较近期,可验证)

---

## 11. 预估成本

### LLM 成本 (全量 13606 篇)

| Provider | 模型 | 预估成本 | 速度 |
|---|---|---|---|
| **Anthropic** | claude-sonnet-4-6 | **~$45** | 快 |
| **OpenAI** | gpt-4o | **~$40** | 快 |
| **OpenAI** | o3-mini | **~$15** | 较快 |
| **Ollama** | qwen2.5:14b | **$0** | 慢 (本地) |

### 时间预估 (Mac M2, 16GB RAM)

| Step | 耗时 |
|---|---|
| Step 1 Enrich | ~1.5h |
| Step 2 Main Path | ~2h |
| Step 3 Keystone | ~1h |
| Step 4 Subgraph | ~0.5h |
| Step 5a SciBERT | ~4h (CPU) / ~1h (MPS) |
| Step 5b VGAE | ~4h (MPS) |
| Step 5c Limitation | ~4h |
| Step 6 Fusion | ~1h |
| Step 7 Mutation | ~0.5h |
| Step 8 Layout | ~2h |
| Step 9 Report | ~0.1h |
| **合计** | **~21.6h** |

---

## 12. 多 Corpus 与季度更新

### 12.1 按 corpus 跑全链路

所有主要 step 均支持 `--corpus-id`。推荐通过 Make 环境变量统一传递:

```bash
V14B_CORPUS_ID=optics make product-chain
V14B_CORPUS_ID=cs make product-chain
V14B_CORPUS_ID=materials make product-chain
```

### 12.2 季度增量更新

新增季度编排入口:

```bash
V14B_CORPUS_ID=optics \
V14B_CORPUS_SET_SPEC=physics:physics:optics \
make quarterly-run
```

`make quarterly-run` 现在会按 `corpus_id` 自动回填默认 `set-spec`:

- `optics -> physics:physics:optics`
- `cs -> cs:cs`
- `materials -> cond-mat:cond-mat.mtrl-sci`

并默认带资源参数:

- `V14B_Q_THREADS=4` (映射到 `OMP/VECLIB/MKL/NUMEXPR`)
- `V14B_Q_EMBED_BATCH=16` (映射到 `V14B_EMBEDDING_BATCH_SIZE`)

### 12.3 季度模板命令（optics/cs/materials）

直接使用以下模板:

```bash
# optics
make quarterly-run-optics

# cs
make quarterly-run-cs

# materials
make quarterly-run-materials
```

覆盖资源参数示例:

```bash
V14B_Q_THREADS=6 V14B_Q_EMBED_BATCH=12 make quarterly-run-cs
V14B_Q_THREADS=4 V14B_Q_EMBED_BATCH=16 make quarterly-run-materials
```

覆盖季度窗口示例:

```bash
V14B_QUARTER_ID=2026Q3 \
V14B_FROM_DATE=2026-07-01 \
V14B_TO_DATE=2026-09-30 \
make quarterly-run-cs
```

该入口会执行:

1. 季度增量 crawl (默认按上次 snapshot 时间继续)
2. `id-repair -> graph-features -> embeddings -> quality-audit`
3. `reset-pilot -> Step2..Step6 -> Step13(Claim Card + Lineage) -> Step7..Step10 -> Step12`
4. 写入 `corpus_runs / corpus_snapshots` 并生成季度 delta 报告

核心表:

- `corpus_registry`
- `paper_corpora`
- `corpus_runs`
- `corpus_snapshots`

---

## 13. Topic Lens 查询接口

新增 Sci-Bot 风格 Topic Lens:

```http
GET /graph/visual/topic-lens?topic=laser+optics&top_k=50&corpus_id=optics
```

返回内容包括:

- 相关论文列表
- cluster / branch 分布
- topic 历史主路径与关键转折论文
- unresolved limitations
- future growth 边与 future directions
- 第一性原理五问报告 (结构化)

---

## 12. V14B 产品链路执行策略

当前 optics 全量库约 55k papers。OpenAlex Field/Topic backfill 是质量增强项,不是主链路阻塞项:

- 若 OpenAlex 连续 429 或 `ok=0`,停止等待,不要让它卡住交付。
- 主链路入口使用 `make product-chain`,该入口不会触发 OpenAlex backfill。
- `product-chain` 顺序:
  `id-repair -> graph-features -> embeddings -> quality-audit -> reset-pilot -> Step2-Step9 -> visual-graph`

```bash
screen -dmS echelon-v14b-product-chain zsh -lc '
cd "/Users/r/Documents/New project/echelon/echelon-v14b"
export OMP_NUM_THREADS=4
export VECLIB_MAXIMUM_THREADS=4
export MKL_NUM_THREADS=4
export V14B_EMBEDDING_BATCH_SIZE=16
export V14B_AUDIT_FAIL_ON=none
make product-chain >> logs/v14b/product_chain.log 2>&1
'
```

监控:

```bash
screen -ls
tail -f logs/v14b/product_chain.log
sqlite3 db/echelon_library.sqlite3 "SELECT COUNT(*) FROM paper_embeddings;"
```

### Visual Graph API

启动 API:

```bash
uvicorn echelon.api.main:app --host 127.0.0.1 --port 8000
```

已实现的 visual graph endpoints:

- `GET /graph/visual/status`
- `GET /graph/visual/clusters`
- `GET /graph/visual/nodes`
- `GET /graph/visual/edges`
- `GET /graph/visual/tiles`
- `GET /graph/visual/story`
- `GET /graph/visual/papers/{paper_id}`
- `POST /graph/visual/search`
- `POST /graph/visual/edit`

本地 WebGL 查看器:

```text
web/visual-graph/index.html
```

该查看器默认连接 `http://127.0.0.1:8000`,支持 2.5D 点云、LOD 边、搜索、论文详情、cluster lens 和 story mode。

---

## 附录: 文件结构

```
echelon-v14b/
├── db/
│   ├── echelon_library.sqlite3    # V14-A 原始数据 (13606 篇)
│   └── v14_pilot.sqlite3          # V14-B 分析结果 (自动生成)
├── echelon/
│   └── v14b/                      # V14-B 新增代码
│       ├── __init__.py
│       ├── config.py              # 集中配置
│       ├── llm_client.py          # LLM 多 Provider 抽象
│       ├── db_schema.py           # DB Schema + Pydantic 模型
│       ├── utils.py               # 公共工具
│       ├── step1_enrich.py
│       ├── step2_mainpath.py
│       ├── step3_keystone_v14.py
│       ├── step4_subgraph.py
│       ├── step5a_scibert.py
│       ├── step5b_vgae.py
│       ├── step5c_limitation.py
│       ├── step6_fusion.py
│       ├── step7_mutation.py
│       ├── step8_layout.py
│       ├── step9_report.py
│       └── step10_visual_graph_builder.py
├── web/visual-graph/              # 2.5D WebGL 查看器
├── logs/v14b/                     # 运行日志
├── reports/v14b_pilot/
│   ├── checkpoints/               # Step 完成标记
│   ├── V14B_Pilot_算法验证报告.md
│   └── 未来方向预测_交集报告.md
├── tests/v14b/                    # 单元测试 (60+)
├── Makefile                       # 一键命令
├── requirements-v14b.txt          # 依赖
├── .env.example                   # 环境变量示例
└── RUNBOOK_V14B.md                # 本手册
```

---

## Raw PDF 外接盘下载

全量论文 PDF 不进入 git，也不直接写主库 `pdfs` 表。下载器把文件和 manifest 都放在外接盘，避免与在线 section ingest 抢 SQLite 写锁：

```bash
mkdir -p /Volumes/LaCie/Echelon_Paper_Raw_Data/{pdfs,metadata,sections,manifests,logs,tmp}
python3 scripts/download_raw_papers.py \
  --store-root /Volumes/LaCie/Echelon_Paper_Raw_Data \
  --concurrency 2 \
  --request-delay 0.75
```

后台运行建议使用 `screen`，日志写入外接盘：

```bash
screen -dmS v14b_raw_pdf_full zsh -lc 'cd /Users/r/Documents/New\ project/echelon/echelon-v14b && export PYTHONPATH=. COPYFILE_DISABLE=1 && python3 scripts/download_raw_papers.py --store-root /Volumes/LaCie/Echelon_Paper_Raw_Data --concurrency 2 --request-delay 0.75 --progress-every 100 >> /Volumes/LaCie/Echelon_Paper_Raw_Data/logs/raw_pdf_full.log 2>&1'
```

进度检查：

```bash
sqlite3 /Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3 \
  "SELECT status, COUNT(*), ROUND(SUM(COALESCE(size_bytes,0))/1024.0/1024.0/1024.0,2) AS gb FROM raw_pdf_downloads GROUP BY status;"
tail -f /Volumes/LaCie/Echelon_Paper_Raw_Data/logs/raw_pdf_full.log
```

当前策略：raw PDF 全量低速常驻下载；section 抽取仍按高价值队列优先推进。新启动的 section ingest 应优先读本地 PDF cache；正在运行的旧 ingest 不强行中断，等安全断点或下一轮队列再切换。

要让 Step5s 优先复用外接盘 PDF cache，设置：

```bash
export V14B_RAW_PDF_STORE_ROOT=/Volumes/LaCie/Echelon_Paper_Raw_Data
export V14B_RAW_PDF_MANIFEST=/Volumes/LaCie/Echelon_Paper_Raw_Data/manifests/raw_pdf_downloads.sqlite3
export V14B_SECTION_INGEST_PREFER_LOCAL_RAW_PDF=true
```

复用状态只读审计：

```bash
make raw-pdf-store-audit
make topic-gap-raw-pdf-inspect
```

`raw-pdf-store-audit` 会同时报告 manifest 下载进度、multi-topic gap 队列中可直接复用本地 PDF 的比例，以及 `paper_sections` 中已经由 `local_raw_pdf_cache` 产生的证据行数。`topic-gap-raw-pdf-inspect` 不写主库，只解析外接盘里已经命中的 topic-gap PDF，判断当前 parser 是否能抽出 primary sections；若 manifest 已有成功下载但 section ingest 复用数仍为 0，说明下一轮 ingest 需要带上上述环境变量或更新本地 `.env`。

---

*Echelon V14-B | 演化树 Pilot 运行手册 v1.0*
