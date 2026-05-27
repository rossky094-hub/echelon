# V11.4 实施计划:5 条洞察修改 + 2000 篇 P0

**生成时间**:2026-05-10
**前置版本**:V11.3 hotfix(6/7 PASS,1/7 PARTIAL)
**关键约束**:严格串行(洞察修完→2000 篇 P0)、Markdown 交付、不再 DOCX

---

## 5 条洞察的根因 + 修改方案

### N1 — 时间窗影响 cite_direct 密度

**现象**:
- 2024-2026 数据 cite_direct = 510(语料新,引用关系未形成)
- 2022-2023 数据 cite_direct = 1042(2 倍)

**根因**:
新论文发表后 12-18 个月内,被同期论文引用极少。
1k 抽样级别下,cite_direct 在新语料里**不是有效信号**。

**修改方案 N1-A:数据分层 + 自适应权重**
- 新代码:`echelon/ingest/sampling_strategy.py`
- 实现 `select_pilot_sampling_window(target_size, age_priority)`:
  - `age_priority = "fresh"` → 6-18 个月窗口(适合发现 emerging 但 cite_direct 弱)
  - `age_priority = "established"` → 12-36 个月(默认,cite_direct 信号充足)
  - `age_priority = "mature"` → 36-60 个月(cite_direct 强但已知度高)
- L1 边权重根据语料平均 age 自适应:
  - `cite_direct_weight = clip(avg_age_months / 18, 0.3, 1.0)`
  - 新语料 cite_direct 权重低,co_citation 权重高
- 文档增量:第 14 章 MVP 路线图加"Pilot 语料采样指南"

**验收**:
- 跑 1k 新 + 1k 老,cite_direct 权重自动 0.5/1.0
- bridging_centrality top10 无新论文歧视

---

### N2 — R5 OR 化 Path 2 占主导,需细化 CS 子规则

**现象**:
- T11714 通过 153 篇,Path 2 (CS 量化)贡献 60 篇 (39%)
- Path 2 关键词太宽:仅 SOTA% / dataset / ablation

**根因**:
V11.3 R5 hotfix 用最简关键词集,造成两个新问题:
1. **假阳性**:任何论文有 "achieves 87%" 都过,可能是描述别人工作
2. **假阴性**:理论 ML 论文(无 SOTA% 但有数学证明)被误伤
3. CS 论文的真实物理深度信号还包括:复杂度证明、收敛保证、消融完整度、数据集多样性

**修改方案 N2-A:Path 2 细化 + Path 4 新增**
- 修改 `echelon/seeds/physical_depth.py`
- Path 2 重构(CS 量化指标 ≥3 的细化):
  - **2a 性能数字**:SOTA%/F1/AUC/BLEU/ROUGE 配数据集名(必须配对,防假阳性)
  - **2b 消融**:`ablat\w*` + count word ≥ 3
  - **2c 复杂度**:`O(n)` / `time complexity` / `polynomial` / `convergence rate`
  - **2d 数据集规模**:M+/B+ samples / parameters / FLOPs
- 新增 **Path 4 理论深度**:数学证明语义指标
  - `theorem` / `proof` / `lemma` / `we prove` / `bound is tight` 出现 ≥2 次
- 修改:`v11_3 path_count = 3` 调到 **`v11_4 path_count = 4`**
- 任一路径 ≥ 阈值(2 或 3)即通过

**验收**:
- 1k 新+老,T11714 Path 2 占比从 39% 降到 25-30%(不再主导)
- Path 4 理论深度贡献 ≥ 5%
- 总 T11714 通过率仍 > 100 篇(不应大幅下降)

---

### N3 — 老语料 co_citation 噪声更重

**现象**:
- 新语料(2024-2026):cocite 边 56,308,过滤后未变(因为没启用过滤当时)
- 老语料(2022-2023):cocite 原 72,945,过滤(weight ≥2)后 41,718,**去噪 42.8%**
- 固定阈值 ≥2 在不同语料效果差异大

**根因**:
- 老论文积累了更多被引,共被引偶发概率高,大量 weight=1 的"巧合共被引"
- 新论文共被引矩阵稀疏,weight=1 反而是真信号
- 固定阈值过于粗糙

**修改方案 N3-A:自适应分位数阈值**
- 修改 `echelon/graph/cocite.py`
- 实现 `compute_cocite_threshold(weight_distribution)`:
  - 计算所有共被引对的 weight 分布
  - 阈值 = max(2, P50)(中位数,但下限 2)
  - 老语料分布偏厚尾 → P50 = 2-3
  - 新语料分布稀疏 → P50 = 1,被 max 拉到 2
- 添加 `cocite_threshold` 字段到 L1 stats(可观测)

**验收**:
- 新语料(2024-2026)阈值 = 2
- 老语料(2022-2023)阈值 = 2 或 3(自动)
- 合并 2000 篇阈值在 2-3 之间

---

### N4 — R1 KeystoneScore 语料效应未消除

**现象**:
- V11.3 R1 改对数空间几何平均后 top10_range 从 0.028 → 0.0447(1.6×,未达 2× 目标)
- 老语料 cited_by_count 累积均质化了 c_venue 分量

**根因**:
- `c_venue` 用 `cited_by_count / max(corpus_cited)` 归一,老论文都 ≥100,
  归一后都接近 0.7-0.9,失去区分度
- 新论文 cited_by_count 0-50,归一后都接近 0-0.5
- 跨语料无可比性

**修改方案 N4-A:c_venue 改用 percentile-by-age**
- 修改 `echelon/seeds/score_keystone.py` 中 c_venue 计算
- 新公式:
  ```python
  def c_venue_v4(paper, corpus):
      age_months = max(1, (today - paper.publication_date).days / 30)
      # 归一化引用率(年化)
      cite_per_year = paper.cited_by_count / (age_months / 12)
      # 在同年龄段(±6 月)论文中算 percentile
      peer_papers = [p for p in corpus if abs(p.age_months - age_months) <= 6]
      peer_cites_per_year = [p.cited_by_count / (p.age_months/12) for p in peer_papers]
      percentile = sum(1 for c in peer_cites_per_year if c <= cite_per_year) / len(peer_papers)
      return percentile  # 0-1,无 cited_by_count 累积均质化
  ```
- 文档更新:第 4 章 §4.2.3 c_venue 公式重写

**验收**:
- 1k 老语料:c_venue 标准差 ≥ 0.20(V11.3 < 0.10)
- 1k 新语料:c_venue 标准差 ≥ 0.20
- 合并 2k 数据上,KeystoneScore top10_range ≥ 2×(R1 完全 PASS)

---

### N5 — 桥词列表精准命中 95%,需扩 Robotics↔ML / VLM↔World

**现象**:
- V11.3 38 条 Optics↔AI 桥词 → 89 条强制建边,占跨 topic 桥 95%
- 但 V11.3 桥词只覆盖 Optics↔AI,没有 Robotics↔ML、VLM↔World 等
- 实际 Pilot V2 数据中,Robotics↔ML 跨界 5 条、VLM↔World 4 条,均无桥词支持

**根因**:
桥词库覆盖单一,只针对你 V10/V11 项目本身关注的"光学+AI",没扩展到 4 topic 全交叉。

**修改方案 N5-A:桥词库分类扩充**
- 修改 `echelon/graph/bridge_keywords.py`
- 桥词库分组(从 38 条 → 约 100 条):
  - **OPTICS_AI**(38 条,V11.3 已有,保留)
  - **ROBOTICS_ML**(20 条新增):imitation learning / reinforcement learning robotics / 
    sim-to-real / domain randomization / behavior cloning / DAgger / 
    diffusion policy / VLA / vision-language-action / RT-2 / RT-X / Open X-Embodiment / 
    deep reinforcement learning manipulation / inverse RL / GAIL / curriculum learning robotics / 
    learning from demonstration / motor skill learning / 
    physics-informed reinforcement learning / soft actor critic robotic
  - **VLM_WORLD_MODEL**(15 条新增):dreamerv3 / world model / latent dynamics / 
    model-based RL / planning with foundation models / video prediction / 
    causal world model / object-centric world model / latent action model / 
    JEPA / I-JEPA / V-JEPA / structured world model / hierarchical world model / 
    embodied world model
  - **GENERIC_AI4SCIENCE**(10 条新增):physics-informed neural network / PINN / 
    AI for science / scientific machine learning / SciML / 
    differentiable simulation / neural ODE / Hamiltonian neural network / 
    Lagrangian neural network / equivariant neural network
- `contains_bridge_keyword(text)` 返回 `(bool, category)`,L1 stats 记录每类桥的数量

**验收**:
- 2000 篇语料,4 类桥都各自至少 5 条以上
- Optics↔ML 仍是最多(因为这是你项目核心),其他类作为补充
- semantic_bridge 总数从 V11.3 的 94 → V11.4 ≥ 200

---

## 实施分组(并行)

### 分组 A:算法层(N2 + N4 + N5)— 12-16h
- N2 物理深度 Path 2 细化 + Path 4 新增
- N4 c_venue percentile-by-age
- N5 桥词库扩充到 100+ 条

### 分组 B:基础设施层(N1 + N3)— 5-8h
- N1 采样策略 + 自适应权重
- N3 cocite 自适应分位数阈值

并行执行 → 等都完成 → 合并测试

---

## 2000 篇 P0 计划

合并:`raw/papers_*.jsonl`(1000)+ `raw_v2/papers_*_v2.jsonl`(1000)
- 4 topic × (250 新 + 250 老)= 4 × 500 = 2000 篇
- 时间窗:2022-01-01 ~ 2026-05-09(完全覆盖)
- 完美的双语料压力测试

跑一遍完整 L1→L2→L3:
- L2 金种子:50 → **100 篇**(语料翻倍,种子也翻倍)
- L3 卡点:10 → **15-20 个**(更多 cluster 容量)
- 三轮对比:V11.2(原 1k)/ V11.3(新 1k)/ V11.4(2k)
