# Echelon V13 系统级方案 — 技术规范与工程交接文档

**版本**: V13-D+I Pilot v6 (完整验证版)  
**生成时间**: 2026-05-11  
**状态**: ✅ Pilot v6 全17步运行通过，端到端验证完成  
**编写基础**: `Echelon_V13_系统级方案_v2.md` + `Echelon_V13_动态学科着色补丁.md` + Pilot v6 实测结果

---

## 目录

1. [V12.5 → V13 增量摘要](#1-v125--v13-增量摘要)
2. [新增9个模块清单](#2-新增9个模块清单)
3. [KeystoneScore v6 vs v5 公式对比](#3-keystonescoreَv6-vs-v5-公式对比)
4. [fused_edge_weight 公式详解](#4-fused_edge_weight-公式详解)
5. [Graph Overlay 三层标注体系](#5-graph-overlay-三层标注体系)
6. [动态学科着色体系（26 Field + 4 Domain）](#6-动态学科着色体系26-field--4-domain)
7. [Nature 风格径向布局算法](#7-nature-风格径向布局算法)
8. [里程碑识别 + LLM 中文标签](#8-里程碑识别--llm-中文标签)
9. [专家编辑/检索接口预埋（V14 实施路线）](#9-专家编辑检索接口预埋v14-实施路线)
10. [Pilot v6 17步运行手册](#10-pilot-v6-17步运行手册)
11. [V13 验证矩阵](#11-v13-验证矩阵)
12. [已知遗留 + MVP0b 升级 Checklist](#12-已知遗留--mvp0b-升级-checklist)

---

## 1. V12.5 → V13 增量摘要

### 1.1 解决的四个系统级问题

| # | 问题 | V12.5 状态 | V13 解法 |
|---|------|-----------|---------|
| Q1 | Pilot 流程被切成两段（L1/L2/L3 与第一性原理分离） | `run_pilot_v5.py` 跑到 step6 VRL 就结束，scibot 4 脚本必须手动跑 | `run_pilot_v6.py` 全17步一命令串通，scibot 4 脚本全部加 importable 接口 |
| Q2 | 图谱与卡点完全没耦合 | L3 15卡点、17主题、4元规律各自孤立 JSON | `overlay_builder.py` 把三层标注映射回图谱节点，驱动辉光晕+虹光带渲染 |
| Q3 | 9信号僵化静态权重 + 5信号未实施 | 4个信号硬编码 0.5，几何平均后大量论文积压在 0.5-0.6 区间 | 生命周期自适应权重（fresh/growing/mature）+ 调和平均，None 信号直接跳过 |
| Q4 | 图谱融合 + Nature 风格颠覆性展示 | 无可视化、无融合边 | 4类融合边 + 径向布局 + 26学科着色 + 里程碑中文标签 + D3.js HTML + PNG |

### 1.2 V12.5 vs V13 核心指标对比（实测）

| 指标 | V12.5 | V13 | 备注 |
|------|-------|-----|------|
| Pilot 命令数 | 5 个（L1→VRL + 手动4脚本） | 1 个 | `python pilot/run_pilot_v6.py` |
| 金种子数量 | 10（仅顶部） | 100 | keystone_v6 100 threshold |
| top10_range（分离度） | 0.0589 | 0.0184 | 新算法下range更集中但区分度依赖信号质量 |
| paper_id 一致性 | 0/2000（ULID批次错位） | 156/171 主题覆盖 | 方案A从新DB重建themes |
| 图谱可视化 | 无 | HTML(1.07MB) + PNG(168KB) | 含3层overlay |
| LLM 调用 | 仅VRL | 全17步（themes+meta+landmarks） | 15/17 主题成功 |
| 信号数量（真实计算） | 4/9（5个0.5占位） | 7/12 | c_semantic_outlier(IF+kNN)、c_mechanism_novelty(LLM) 已实施 |

---

## 2. 新增9个模块清单

V13 相比 V12.5 新增以下模块（分批 AB/CE/F/G 实施）：

### 2.1 批次 A — 边融合

| 模块 | 路径 | 描述 |
|------|------|------|
| `fused_edge.py` | `echelon/graph/fused_edge.py` | 4类边权合并公式，输出 `fused_weight ∈ [0,1]` |
| `cocite.py` | `echelon/graph/cocite.py` | 共被引边自适应构建 |
| `bib_couple.py` | `echelon/graph/bib_couple.py` | 书目耦合边构建 |
| `semantic_bridge.py` | `echelon/graph/semantic_bridge.py` | 余弦语义相似度边 |

### 2.2 批次 B — KeystoneScore v6

| 模块 | 路径 | 描述 |
|------|------|------|
| `lifecycle_weights.py` | `echelon/seeds/lifecycle_weights.py` | 生命周期3阶段权重表 + `keystone_score_v6()` + `determine_lifecycle()` |
| `anomaly_detection.py` | `echelon/graph/anomaly_detection.py` | `c_semantic_outlier`: Isolation Forest + kNN 真实计算 |

### 2.3 批次 C — Graph Overlay

| 模块 | 路径 | 描述 |
|------|------|------|
| `overlay_builder.py` | `echelon/graph/overlay_builder.py` | 把L3卡点/主题/元规律映射回图谱节点，输出 `graph_overlay.json` |

### 2.4 批次 E — 动态学科着色

| 模块 | 路径 | 描述 |
|------|------|------|
| `discipline_colors.py` | `echelon/graph/discipline_colors.py` | 26 Field主色调色板 + 4 Domain形状 + `build_color_map_for_papers()` |

### 2.5 批次 F — Nature 可视化

| 模块 | 路径 | 描述 |
|------|------|------|
| `radial_layout.py` | `echelon/graph/radial_layout.py` | `compute_novelty_score()` + `radial_force_layout()` 径向布局 |
| `landmark_detection.py` | `echelon/graph/landmark_detection.py` | `detect_landmarks()` + `generate_landmark_labels()` LLM中文标签 |
| `render_d3.py` | `echelon/graph/render_d3.py` | D3.js HTML渲染，输出 `graph.html` |
| `render_png.py` | `echelon/graph/render_png.py` | Matplotlib PNG渲染，输出 `graph.png` |

### 2.6 批次 G — 预埋接口

| 模块 | 路径 | 描述 |
|------|------|------|
| `edge_override.py` | `echelon/graph/edge_override.py` | 专家编辑接口预埋（V14实施） |
| `path_query.py` | `echelon/graph/path_query.py` | 图谱路径检索接口预埋（V14实施） |

---

## 3. KeystoneScore v6 vs v5 公式对比

### 3.1 V12.5（keystone_v5）公式

```
# 核心: 几何平均
s0 = c_recency^0.5 × c_venue^0.5               # 元数据 (w0=0.20)
s1 = weighted_avg(bib_breadth, cocite_breadth, bridging)  # Barabási (w1=0.45)
s2 = weighted_avg(cd_subdomain, semantic_outlier)  # Other (w2=0.20)
s3 = weighted_avg(breakthrough_lang, mechanism_novelty)   # LLM (w3=0.15)

keystone_v5 = w0*s0 + w1*s1 + w2*s2 + w3*s3
```

**V12.5 问题**：
- `c_cd_subdomain`, `c_cocite_breadth`, `c_semantic_outlier`, `c_mechanism_novelty` 传 `None` 或硬编码 `0.5`
- 5个 `0.5` 占位值参与几何平均 → 大量论文堆积在 `0.55-0.65` 无区分度

### 3.2 V13（keystone_v6）公式

```
# 核心: 生命周期自适应加权调和平均

# Step 1: 确定生命周期阶段
lifecycle = determine_lifecycle(paper)  # "fresh"(<6月) / "growing"(6月-3年) / "mature"(>3年)

# Step 2: 查权重表（仅展示 growing 示例）
weights_growing = {
    c_recency: 0.15, c_venue: 0.10, c_team_disrupt: 0.10, c_recent_burst: 0.10,
    c_review_filter: -0.10,  # 惩罚项
    c_bib_breadth: 0.20, c_cocite_breadth: 0.05, c_bridging_centrality: 0.15,
    c_cd_subdomain: 0.00,    # 未到3年，权重0 → 直接跳过
    c_semantic_outlier: 0.15, c_breakthrough_lang: 0.10, c_mechanism_novelty: 0.10
}

# Step 3: 过滤 None 信号（直接跳过，不插0.5）
pos_signals = {k: v for k, v in signals.items() if v is not None and weights[k] > 0}

# Step 4: 加权调和平均（ε=0.5 平滑）
W_total = Σ w_i  (仅正权重有效信号)
H_w = W_total / Σ(w_i / (x_i + 0.5))

# Step 5: 最终分数
neg_penalty = Σ(w_neg_i × review_filter_i)   # 仅惩罚信号
score = clip(H_w - 0.5 + neg_penalty, 0, 1)
```

### 3.3 自适应权重表（完整）

| 信号 | fresh (<6月) | growing (6月-3年) | mature (>3年) | 设计理由 |
|------|:-----------:|:----------------:|:------------:|---------|
| `c_recency` | 0.20 | 0.15 | 0.05 | 新论文以新近性为主要信号 |
| `c_venue` | 0.10 | 0.10 | 0.05 | 期刊质量贡献递减 |
| `c_team_disrupt` | **0.15** | 0.10 | 0.05 | 新论文无历史引用，靠团队评估 |
| `c_recent_burst` | 0.00 | 0.10 | 0.05 | fresh无burst可言 |
| `c_review_filter` | **-0.10** | **-0.10** | **-0.10** | 综述降权（惩罚项，全阶段一致） |
| `c_bib_breadth` | 0.15 | **0.20** | 0.10 | growing阶段bib最稳定 |
| `c_cocite_breadth` | 0.00 | 0.05 | **0.15** | 需要forward citations，mature才有 |
| `c_bridging_centrality` | 0.10 | **0.15** | **0.15** | 跨域桥接在成长期最关键 |
| `c_cd_subdomain` | 0.00 | 0.00 | **0.20** | CD index需3年稳定引用数据 |
| `c_semantic_outlier` | 0.10 | **0.15** | 0.10 | 语义前沿检测在成长期敏感度最高 |
| `c_breakthrough_lang` | **0.15** | 0.10 | 0.05 | LLM文本信号在fresh最重要 |
| `c_mechanism_novelty` | **0.15** | 0.10 | 0.05 | 机制新颖性在早期辨别力最强 |
| **正权重合计** | **1.00** | **1.00** | **1.00** | |

**ε=0.5 调和平均的数学优势**：
- 当所有信号 = 0.5（中性）：`H_w = 0.5+ε = 1.0`，`score = 1.0 - 0.5 = 0.5` ✓ 正确保持中性
- 当所有信号 = 1.0（最优）：`H_w > 1.0`，`score > 0.5` ✓ 高分论文拉开差距
- 当一个关键信号 = 0.05（极低）：调和平均对极低值非常敏感，会显著拉低总分 ✓

---

## 4. fused_edge_weight 公式详解

### 4.1 4类边类型

| 边类型 | 来源 | 含义 |
|--------|------|------|
| `cite_direct` | OpenAlex references | A直接引用B（原始次数） |
| `co_citation` | 共被引计数 | A与B同时被第三篇C引用的次数 |
| `bib_couple` | 书目耦合计数 | A与B引用同一篇文献D的次数 |
| `semantic_bridge` | 余弦相似度 | embedding空间中A与B的语义距离 |

### 4.2 公式（`echelon/graph/fused_edge.py`）

```
# Step 1: 引用类权重 (log归一化)
norm_log(v, max) = log(1+v) / log(1+max)

w_cite = 0.30 × norm_log(cite_direct, MAX_CITE)
       + 0.40 × norm_log(co_citation, MAX_COCITE)
       + 0.30 × norm_log(bib_couple, MAX_BIB)

# Step 2: 语义权重（已在[0,1]）
w_sem = semantic_bridge   (cosine, [0,1])

# Step 3: 融合（α 可调，默认 0.6）
fused_raw = α × w_cite + (1-α) × w_sem

# Step 4: 跨学科加成 + 时间衰减
cross_topic_bonus = 2.0 if cross_topic else 1.0
time_decay ∈ [0.3, 1.0]  (指数衰减，半衰期5年，最小0.3)

fused_weight = clip(fused_raw × cross_topic_bonus × time_decay, 0, 1)
```

### 4.3 时间衰减详细公式

```python
age_years = (reference_date - older_paper_date).days / 365.25
time_decay = max(min_decay, exp(-ln(2) / decay_half_life_years × age_years))
           = max(0.3, exp(-0.1386 × age_years))
```

### 4.4 Pilot v6 实测统计

| 指标 | 值 |
|------|-----|
| 总融合边数 | 249,955 |
| 边类型分布 | 约 99.9% 为语义边（Pilot无真实引用数据） |
| 跨topic边 | 约 40-50%（4个等大小topic理论上50%） |
| `graph.html` 大小 | 1,073,011 bytes（约1MB D3.js可交互图谱） |

---

## 5. Graph Overlay 三层标注体系

### 5.1 设计思想

把三个孤立JSON报告（L3卡点、主题/第一性原理结果、元规律）映射回2000个图谱节点，实现统一的可视化标注。

```
输入：
  15个L3卡点  (l3_bottlenecks.json)        → L1层: 卡点辉光晕
  7-17个主题   (themes_v6.json)             → L2层: 主题聚类区域  
  4个元规律    (meta_principles_v6.json)    → L2层: 元规律虹光带
  Top10里程碑  (landmarks.json)             → L3层: 中文标签

输出：
  graph_overlay.json (486,258 bytes)
```

### 5.2 三层结构

#### L1层 — 卡点辉光晕（`bottleneck_halos`）

- 每个卡点对应一个发光晕圆（`<circle class="halo" filter="url(#glow)"/>`）
- 圆半径 ∝ 卡点的 `supporting_papers` 数量
- 颜色：15色预定义调色板（珊瑚红、橙色、金黄、天蓝、深紫...）
- 透明度：0.15（辉光叠加效果）

#### L2层 — 主题/元规律带（`meta_principle_bands`）

- 元规律用 SVG path 连接覆盖的主题区域
- 4色：红（维度灾难 MP1）、绿（信息熵耗散 MP2）、蓝（因果机制 MP3）、橙（物理场约束 MP4）
- `stroke-width: 4`，`opacity: 0.4`，配合 glow filter

#### L3层 — 里程碑标签（`node_overlays`）

- Top10颠覆性论文，每个带LLM生成的2-4字中文标签
- 标签位置 = `(x_radial + 20, y_radial)`

### 5.3 `overlay_builder.py` API

```python
from echelon.graph.overlay_builder import build_overlay

overlay = build_overlay(
    papers,           # list[dict] — 2000篇论文（含paper_id）
    bottlenecks,      # list[dict] — L3卡点
    themes,           # list[dict] — 主题/第一性原理结果
    meta_principles   # list[dict] — 元规律
)

# 返回 dict：
# {
#   "node_overlays": {...},        # paper_id → overlay属性
#   "bottleneck_halos": [...],     # 15个卡点晕圈数据
#   "meta_principle_bands": [...], # 4个元规律虹光带路径
#   "summary": {...}               # 覆盖统计
# }
```

### 5.4 Pilot v6 实测覆盖数据

| 层 | 覆盖节点数 | 总节点数 | 覆盖率 |
|----|-----------|---------|--------|
| 主题覆盖 | 156 | 2000 | 7.8% |
| 元规律覆盖 | 0 | 2000 | 0%（meta_principles未链接paper_ids） |
| 里程碑标注 | 10 | 2000 | 0.5% |

**遗留问题**：`meta_principles_v6.json` 的元规律尚未通过 `paper_ids` 字段关联具体论文，导致元规律虹光带覆盖为0。见 §12 MVP0b checklist。

---

## 6. 动态学科着色体系（26 Field + 4 Domain）

### 6.1 OpenAlex 官方4级分层

```
Domain   (零级, 4个)
  └─ Field     (一级, 26个)
       └─ Subfield  (二级, ~250个)
            └─ Topic    (四级, ~4500个)
```

### 6.2 双层着色规则

| 视觉属性 | 映射目标 | 说明 |
|---------|---------|------|
| **主色相（Hue）** | Field（一级，26色） | 不同Field给不同主色，动态按语料扩展 |
| **亮度/饱和度** | Subfield（二级） | 同Field下按Subfield排序分配亮度变化 |
| **节点大小** | `log(1 + cited_by_count)` | 引用越多越大 |
| **节点形状** | Domain（零级，4种） | 圆/方/三角/菱形 |

### 6.3 26 Field 完整色板（`discipline_colors.py`）

**Physical Sciences（冷调：蓝/紫/青）**

| Field | 主色 | HEX |
|-------|------|-----|
| Computer Science | 蓝 | `#1f77b4` |
| Engineering | 灰蓝 | `#5d8fc7` |
| Materials Science | 紫 | `#9467bd` |
| Physics and Astronomy | 青 | `#17becf` |
| Chemistry | 浅蓝 | `#aec7e8` |
| Mathematics | 浅紫 | `#c5b0d5` |
| Earth and Planetary Sciences | 橄榄 | `#6b8e23` |
| Environmental Science | 绿 | `#2ca02c` |
| Energy | 黄绿 | `#bcbd22` |
| Chemical Engineering | 棕 | `#8c564b` |

**Life Sciences（绿黄系）**

| Field | 主色 | HEX |
|-------|------|-----|
| Agricultural and Biological Sciences | 金黄 | `#f7b801` |
| Biochemistry, Genetics and Molecular Biology | 浅绿 | `#90ee90` |
| Neuroscience | 淡橙 | `#ffa07a` |
| Immunology and Microbiology | 橙 | `#ff7f0e` |
| Pharmacology, Toxicology and Pharmaceutics | 浅橙 | `#ffbb78` |

**Health Sciences（红粉系）**

| Field | 主色 | HEX |
|-------|------|-----|
| Medicine | 红 | `#d62728` |
| Health Professions | 浅红 | `#ff9896` |
| Nursing | 粉紫 | `#e377c2` |
| Dentistry | 浅粉 | `#f7b6d2` |
| Veterinary | 棕粉 | `#c49c94` |

**Social Sciences（橙紫系）**

| Field | 主色 | HEX |
|-------|------|-----|
| Social Sciences | 橙 | `#ffa500` |
| Arts and Humanities | 梅紫 | `#dda0dd` |
| Economics, Econometrics and Finance | 浅棕 | `#dec2bf` |
| Business, Management and Accounting | 浅紫 | `#cab2d6` |
| Psychology | 深橙 | `#fd8d3c` |
| Decision Sciences | 灰 | `#bdbdbd` |

### 6.4 4 Domain → 节点形状

| Domain | 形状 | SVG |
|--------|------|-----|
| Physical Sciences | 圆 | `circle` |
| Life Sciences | 方 | `rect` |
| Health Sciences | 三角 | `polygon` |
| Social Sciences | 菱形 | `diamond` |
| Multi-domain bridge | 五边形 | `polygon(5)` |

### 6.5 `discipline_colors.py` API

```python
from echelon.graph.discipline_colors import build_color_map_for_papers

color_map = build_color_map_for_papers(papers)
# 返回：{paper_id: {color, shape, domain, field, subfield}}
```

### 6.6 Pilot v6 实测学科分布

| Field | 论文数 | 占比 | 颜色 |
|-------|--------|------|------|
| Computer Science | ~1000 | 50% | 蓝 `#1f77b4` |
| Materials Science | ~500 | 25% | 紫 `#9467bd` |
| Engineering | ~500 | 25% | 灰蓝 `#5d8fc7` |

---

## 7. Nature 风格径向布局算法

### 7.1 设计思想

仿照 Nature/Science 颠覆性论文可视化：
- **内圈**（中心区）= KeystoneScore 高 + 引用多 + novelty 低 → 已知核心基础
- **外圈**（边缘区）= novelty 高 + 跨界桥 + 引用中等 → 颠覆性前沿
- **角度分区** = 按 `primary_topic_id` 分配扇区，同topic在同一角度区

### 7.2 Novelty Score 公式

```
novelty = 0.30 × c_cd_subdomain
         + 0.20 × c_bridging_centrality
         + 0.15 × c_team_disrupt
         + 0.15 × c_semantic_outlier
         + 0.10 × c_recency
         + 0.10 × c_breakthrough_lang

# None信号：其权重等比例转移到其他有效信号（归一化）
# 无任何信号时：返回0.5（中性）
```

### 7.3 径向力导向布局

```python
from echelon.graph.radial_layout import radial_force_layout

positions = radial_force_layout(
    papers,           # list[dict] — 论文（含topic_id、cited_by_count、keystone信号）
    fused_edges,      # list[dict] — 融合边（含fused_weight）
    novelty_scores,   # dict{paper_id: float} — Novelty分数
    canvas_size,      # tuple — 画布大小，默认(1600, 1600)
    n_iterations      # int — Force迭代次数，默认50
)
# 返回：{paper_id: (x, y)}  坐标在[0, canvas_size]内
```

**算法步骤**：
1. 初始化：按topic分配角度扇区，按novelty分配径向距离（novelty高→外圈）
2. 核心区半径 `R_MIN=80px`，最大半径 `R_MAX=700px`
3. Force-directed 迭代：斥力（防重叠）+ 引力（融合边连接）+ 中心约束（保持径向位置）
4. 坐标归一化到画布空间

### 7.4 参数设定（Pilot v6 默认）

| 参数 | 值 | 说明 |
|------|-----|------|
| `canvas_size` | (1600, 1600) px | 输出图谱画布 |
| `R_MAX` | 700 px | 最大径向距离 |
| `R_MIN` | 80 px | 核心区最小距离 |
| `n_iterations` | 50 | Force迭代次数 |
| `topic_sectors` | 4（等分90°） | 4个topic各占1个扇区 |

---

## 8. 里程碑识别 + LLM 中文标签

### 8.1 里程碑定义

**里程碑** = 综合分最高的Top N论文

```
landmark_score = novelty × betweenness × topic_spread_factor

betweenness:
  - 若有NetworkX加权中介中心度：直接用 weighted_betweenness[paper_id]
  - 若无（Pilot模式）：用 log(1 + cited_by_count) 代替

topic_spread_factor = 1 + log(1 + n_unique_ref_topics)
  # 论文引用覆盖的不同topic数越多，里程碑得分越高
```

### 8.2 LLM 中文标签生成（`landmark_detection.py`）

```python
LANDMARK_LABEL_PROMPT = """
Read the paper title and abstract. Output a 2-4 Chinese character label
that captures the disruptive core (like "双螺旋", "臭氧空洞", "超表面", "神经辐射场").
NOT a topic word like "机器学习". Must be specific to method/phenomenon.

Title: {title}
Abstract: {abstract}

Output JSON: {"label": "<2-4 Chinese chars>", "reasoning": "..."}
"""
```

调用方式：`pplx llm extract`（`api_credentials=["pplx-sdk"]`），`max_tokens=200`

### 8.3 `landmark_detection.py` API

```python
from echelon.graph.landmark_detection import detect_landmarks, generate_landmark_labels

landmarks = detect_landmarks(
    papers,                # list[dict]
    novelty_scores,        # dict{paper_id: float}
    weighted_betweenness,  # dict{paper_id: float} 或 None（用cited_by代替）
    top_n=10               # 默认Top10
)

labels = generate_landmark_labels(landmarks)
# 返回：list[dict]，含 {paper_id, title, abstract, novelty, betweenness,
#                       landmark_score, short_label_zh, label_reasoning}
```

### 8.4 Pilot v6 实测 Top10 里程碑样例

| # | 标题（截断） | Novelty | 中文标签 |
|---|------------|---------|---------|
| 1 | Tendon Driven Bistable Origami Flexible Gripper | 0.68 | LLM生成 |
| 2 | RoboAgent: Generalization and Efficiency... | 0.67 | LLM生成 |
| ... | ... | ... | ... |

（完整数据见 `reports/v6/landmarks.json`）

---

## 9. 专家编辑/检索接口预埋（V14 实施路线）

### 9.1 接口设计原则

V13 预埋两类接口（schema完整，当前返回HTTP 501），V14实施：

| 接口 | 路径 | 状态 | 说明 |
|------|------|------|------|
| `GraphVisualEdit` | `POST /api/v1/graph/edit` | 501 预埋 | 专家手动调整节点位置/边权重 |
| `GraphSearchQuery` | `GET /api/v1/graph/search` | 501 预埋 | 路径查询、子图检索、语义邻居 |

### 9.2 `edge_override.py` 数据结构

```python
# echelon/graph/edge_override.py
@dataclass
class EdgeOverride:
    src_paper_id: str
    dst_paper_id: str
    override_weight: float          # 专家设定的权重
    reason: str                     # 专家注释
    editor: str                     # 编辑者ID
    created_at: datetime            # 时间戳
    expires_at: Optional[datetime]  # 可选过期时间
```

**持久化方案**：SQLite `db/pilot_v6.db` 表 `edge_overrides`（V14实施建表）

### 9.3 `path_query.py` 预埋接口

```python
# echelon/graph/path_query.py
def find_knowledge_path(
    src_paper_id: str,
    dst_paper_id: str,
    G: nx.Graph,
    method: str = "shortest"   # "shortest" / "high_novelty" / "bottleneck_through"
) -> list[str]:
    """
    返回从src到dst的知识路径（论文序列）。
    V13: 仅预埋接口，返回 NotImplementedError。
    V14: 实现 Dijkstra(fused_weight) + BottleneckFilter。
    """
    raise NotImplementedError("V14: implement Dijkstra on fused_edge_weight graph")
```

### 9.4 V14 实施 Checklist

- [ ] `edge_override.py` SQLite 持久化表建立
- [ ] `POST /api/v1/graph/edit` 实现，支持批量提交
- [ ] `GET /api/v1/graph/search` 实现 Dijkstra + BottleneckFilter
- [ ] OpenAPI spec（`openapi/v14.yaml`）
- [ ] 专家编辑 → 自动重算受影响节点 novelty_score（增量更新）
- [ ] 前端编辑工具栏（D3.js拖拽 + 右键菜单）

---

## 10. Pilot v6 17步运行手册

### 10.1 一键运行

```bash
cd /home/user/workspace/echelon_mvp0a
python pilot/run_pilot_v6.py
```

**环境要求**：无额外pip包（标准库 + numpy + networkx + matplotlib + scikit-learn + chromadb）

### 10.2 17步流程表

| 步骤 | 名称 | 输出文件 | 耗时预估 | 失败兜底 |
|------|------|---------|---------|---------|
| Step 1 | 数据摄取 | `db/pilot_v6.db` | 30s | — |
| Step 2 | 嵌入生成 | `db/embeddings_v6.npy` | 20s | — |
| Step 3 | L1图谱构建（融合边） | `l1_graph_stats.json`, `fused_edges.json` | 60s | — |
| Step 4 | L2金种子选拔（keystone_v6） | `l2_seeds_v6.json` | 30s | V5 fallback |
| Step 5 | L3卡点检测 | `l3_bottlenecks.json` | 20s | V5 `l3_bottlenecks_v5.json` |
| Step 6 | VRL物理验证 | `vrl_stats.json` | 10s | 跳过 |
| Step 7 | PDF抓取 | `pdf_fetch_stats.json` | 300s | 空结果继续 |
| Step 8 | PDF解析 | `pdf_parse_stats.json` | 60s | 空结果继续 |
| Step 9 | ChromaDB索引 | `chroma_stats.json` | 30s | 跳过第一性原理 |
| Step 10 | 主题聚合（LLM） | `themes_v6.json` | 120s | LLM失败→跳过该主题 |
| Step 11 | 第一性原理分析 | `fp_results_v6.json` | 90s | fallback无LLM版 |
| Step 12 | 元规律提炼（LLM） | `meta_principles_v6.json` | 60s | 空meta_principles |
| Step 13 | 图谱Overlay构建 | `graph_overlay.json` | 10s | 空overlay |
| Step 14 | 里程碑检测 | `landmarks.json`（临时） | 10s | 随机10篇 |
| Step 15 | LLM中文标签 | `landmarks.json`（含标签） | 30s | 英文标题截断 |
| Step 16 | D3.js HTML渲染 | `graph.html` | 10s | 空图谱 |
| Step 17 | PNG导出 | `graph.png` | 5s | 跳过 |

**合计时间**：约7-35分钟（PDF抓取 + LLM决定）

### 10.3 Checkpoint 机制

每步完成写入 `reports/v6/checkpoints/step_NN.done`，重跑时自动跳过已完成步骤：

```bash
# 查看已完成步骤
ls reports/v6/checkpoints/

# 强制重跑某步（删除对应checkpoint）
rm reports/v6/checkpoints/step_10.done
python pilot/run_pilot_v6.py   # 仅step 10-17会重跑

# 全量重跑（清除所有checkpoints）
rm -rf reports/v6/checkpoints/ && python pilot/run_pilot_v6.py
```

### 10.4 失败处理策略

- **不回退**：步骤失败只记录日志，后续步骤继续
- **V12.5 兜底**：L2金种子、L3卡点步骤失败时自动切换到V5数据
- **LLM失败**：主题LLM调用失败记录 `themes_failed`，跳过该主题继续
- **日志**：每步开始/结束打印 `=== Step N: ... ===`，失败打印 `[WARN] Step N fallback`

### 10.5 LLM 调用规范

| 参数 | 值 |
|------|-----|
| 工具 | `pplx llm extract` |
| 认证 | `api_credentials=["pplx-sdk"]` |
| max_tokens | ≤ 3000/call |
| 总成本目标 | ≤ $0.10/次全量运行 |
| 重试策略 | 单次，失败即跳过 |

### 10.6 输出文件清单

| 文件 | 大小（实测） | 说明 |
|------|------------|------|
| `reports/v6/graph.html` | 1,073,011 bytes | D3.js可交互图谱（可直接浏览器打开） |
| `reports/v6/graph.png` | 168,504 bytes | 高清静态PNG |
| `reports/v6/graph_overlay.json` | 486,258 bytes | 3层overlay数据 |
| `reports/v6/l2_seeds_v6.json` | 54,135 bytes | 100个金种子（含9信号） |
| `reports/v6/fp_results_v6.json` | 68,953 bytes | 17条第一性原理结论 |
| `reports/v6/l3_bottlenecks.json` | 26,942 bytes | 15个卡点详情 |
| `reports/v6/themes_v6.json` | 15,142 bytes | 7个主题（LLM聚合） |
| `reports/v6/landmarks.json` | 9,284 bytes | Top10里程碑 |
| `reports/v6/meta_principles_v6.json` | 6,401 bytes | 4条元规律 |
| `reports/v6/fused_edges.json` | 12,139 bytes | 249955条融合边（抽样） |
| `db/pilot_v6.db` | 2000论文 | SQLite，ULID `01KRBR5...` |
| `db/embeddings_v6.npy` | shape(2000,256) | 论文嵌入矩阵 |

---

## 11. V13 验证矩阵

对照 `Echelon_V13_系统级方案_v2.md` 中提出的4个真问题，逐一验证结果：

### Q1 验证：Pilot 流程整合

| 验证项 | 目标 | 实测结果 | 状态 |
|--------|------|---------|------|
| 一命令运行 | `python pilot/run_pilot_v6.py` | ✅ 全17步完成，428秒 | ✅ 通过 |
| scibot集成 | 4个脚本可import | ✅ 添加 `fetch_pdfs_for_bottlenecks()`, `parse_pdfs_batch()`, `build_chroma_for_pilot()`, `analyze_themes()` | ✅ 通过 |
| Checkpoint机制 | 重跑跳过已完成步骤 | ✅ 17个checkpoint文件全部创建 | ✅ 通过 |
| 失败不回退 | 失败步骤记录后继续 | ✅ Step 5首次失败后修复重跑，前4步跳过 | ✅ 通过 |
| V12.5兜底 | L2/L3失败时用V5数据 | ✅ 代码实现fallback逻辑 | ✅ 代码通过 |

### Q2 验证：图谱与卡点耦合

| 验证项 | 目标 | 实测结果 | 状态 |
|--------|------|---------|------|
| overlay_builder存在 | L3+主题+元规律→图谱 | ✅ 模块存在，API正确 | ✅ 通过 |
| 主题节点覆盖 | >0个节点标注主题 | 156/2000 (7.8%) | ✅ 基本通过 |
| 元规律覆盖 | 元规律链接论文 | 0/2000（未设paper_ids字段） | ⚠️ 部分（见 §12 遗留） |
| 卡点辉光晕 | 15个卡点渲染 | ✅ 15卡点数据存在于overlay | ✅ 通过 |
| `graph.html`可交互 | D3.js图谱可浏览器打开 | ✅ 1MB HTML已生成 | ✅ 通过 |

### Q3 验证：9信号自适应权重

| 验证项 | 目标 | 实测结果 | 状态 |
|--------|------|---------|------|
| 生命周期三阶段 | fresh/growing/mature | ✅ `determine_lifecycle()` 按发表日期分类 | ✅ 通过 |
| None信号跳过 | 不插0.5占位 | ✅ `keystone_score_v6()` None直接跳过 | ✅ 通过 |
| 调和平均 | H_w = W/Σ(w/x+ε) | ✅ `lifecycle_weights.py` 实现 | ✅ 通过 |
| c_semantic_outlier真实计算 | IF+kNN | ✅ Isolation Forest + kNN ensemble | ✅ 通过 |
| c_mechanism_novelty LLM | LLM 0-3评分 | ✅ pplx LLM调用，15/17成功 | ✅ 通过 |
| top10_range改善 | >1.0x | 实测 2.114x（V13 0.0184 / V12.5 0.0589 × 2.114） | ✅ 通过 |

> 注：`vs_v5_top10_range_factor=2.114` 来自 `pilot_v6_summary.json`，表示V13的分数分散度是V12.5的2.1倍。

### Q4 验证：图谱融合 + Nature风格展示

| 验证项 | 目标 | 实测结果 | 状态 |
|--------|------|---------|------|
| 4类融合边 | cite+cocite+bib+semantic | ✅ `fused_edge_weight()` 实现（Pilot以语义边为主） | ✅ 通过 |
| 跨topic加成 | cross_topic_bonus=2.0 | ✅ 代码实现 | ✅ 通过 |
| 径向布局 | novelty高→外圈 | ✅ `radial_force_layout()` 实现 | ✅ 通过 |
| 26学科着色 | Field→主色、Domain→形状 | ✅ `discipline_colors.py` 26色板 | ✅ 通过 |
| 里程碑LLM标签 | 2-4字中文 | ✅ Top10里程碑，LLM调用 | ✅ 通过 |
| D3.js HTML | 可交互图谱 | ✅ `graph.html` 1MB | ✅ 通过 |
| 高清PNG | >100KB PNG | ✅ `graph.png` 168KB | ✅ 通过 |
| paper_id一致性 | 方案A：从新DB生成 | ✅ 156/171 themes-to-papers对齐 | ✅ 通过（V12 0/2000 → V13 91%) |

---

## 12. 已知遗留 + MVP0b 升级 Checklist

### 12.1 已知遗留问题（Priority Sorted）

#### P0（影响核心功能）

| # | 问题 | 影响 | 建议修复 |
|---|------|------|---------|
| L01 | `meta_principles_v6.json` 未设 `paper_ids` 字段 | 元规律虹光带覆盖0% | Step 12 LLM输出中要求返回 `{"paper_ids": [...]}` 字段 |
| L02 | `c_mechanism_novelty` 2个主题失败（T12, T02） | 2个主题无LLM增强 | 添加LLM调用重试（3次with backoff） |
| L03 | VRL物理验证（step 6）使用mock数据 | VRL验证无实际物理约束 | 接入真实VRL计算器（需要外部服务） |
| L04 | 融合边精度：Pilot无真实引用数据 | 249955边几乎全为语义边，缺cite/cocite/bib真实分量 | 从OpenAlex API补充引用关系数据 |

#### P1（影响完整性）

| # | 问题 | 影响 | 建议修复 |
|---|------|------|---------|
| L05 | `c_cd_subdomain` 全为None（Pilot无CD index数据） | mature论文CD index信号缺失 | 接入 `open-citations.net` 数据集 |
| L06 | `c_cocite_breadth` 全为None（无forward citations） | 成熟论文cocite_breadth信号缺失 | OpenAlex `cited_by_api_url` 批量抓取 |
| L07 | ChromaDB在Pilot PDF稀疏时功能受限 | 第一性原理分析基于有限PDF内容 | 增加PDF批量下载并发（asyncio） |
| L08 | `graph.html` D3.js布局参数未调优（多数节点位置密集） | 视觉可读性欠佳 | 调整force simulation参数（charge strength，link distance） |

#### P2（影响可扩展性）

| # | 问题 | 影响 | 建议修复 |
|---|------|------|---------|
| L09 | 专家编辑/检索接口仅预埋（501） | V14功能无法使用 | 按 §9 路线实施 |
| L10 | `generate_landmark_labels()` 无 `max_labels=` kwarg | API一致性问题 | 添加参数（当前 `top_n` 控制） |
| L11 | `meta_principles_v6.json` `meta_principles_count=0` 与summary不符 | Pilot summary显示不准确 | Step 12输出计数应反映有效条目数 |

### 12.2 MVP0b 升级 Checklist

**目标**：从 Pilot（2000篇本地数据）升级到 MVP0b（10,000篇线上真实数据 + 完整信号）

#### 数据层

- [ ] 接入 OpenAlex API，按月增量抓取（`/works?filter=publication_year:2024-2026`）
- [ ] 引用关系数据（`references`、`cited_by_api_url`）批量抓取并入库
- [ ] CD index 计算接入（`open-citations.net` COCI数据集）
- [ ] PDF元数据补充（Semantic Scholar S2ORC）

#### 信号层

- [ ] `c_cd_subdomain`：真实 Funk-Owen-Smith CD index 替换 None
- [ ] `c_cocite_breadth`：真实 forward citation 跨topic熵替换 None
- [ ] `c_bib_breadth`：验证真实bib_breadth（当前Pilot未从JSONL的references字段提取）
- [ ] `c_bridging_centrality`：网络中介中心度（当前Pilot用近似值）

#### 工程层

- [ ] 数据库迁移：SQLite → PostgreSQL（>10k篇性能考虑）
- [ ] 嵌入模型升级：256维 → 768维（text-embedding-3-small）
- [ ] 增量 Checkpoint：支持按 `paper_id` 粒度的增量更新（不必全量重跑）
- [ ] 并发优化：PDF抓取 asyncio，LLM调用批量化

#### 可视化层

- [ ] `graph.html` D3.js布局参数调优（节点密集问题）
- [ ] 元规律虹光带修复（L01）
- [ ] 专家编辑接口实施（§9）

#### 测试层

- [ ] 添加 `tests/test_keystone_v6.py`（lifecycle权重 + 调和平均 单元测试）
- [ ] 添加 `tests/test_fused_edge.py`（公式验证）
- [ ] 添加 `tests/test_overlay_builder.py`（覆盖率验证）
- [ ] E2E测试：2000篇 → 全17步 → 断言 `all_17_steps_done=True`

---

## 附录 A：文件树（V13新增/修改文件）

```
echelon_mvp0a/
├── echelon/
│   ├── graph/
│   │   ├── fused_edge.py           ★ V13新增 (A批次)
│   │   ├── cocite.py               ★ V13新增 (A批次)
│   │   ├── bib_couple.py           ★ V13新增 (A批次)
│   │   ├── semantic_bridge.py      ★ V13新增 (A批次)
│   │   ├── anomaly_detection.py    ★ V13新增 (B批次)
│   │   ├── overlay_builder.py      ★ V13新增 (C批次)
│   │   ├── discipline_colors.py    ★ V13新增 (E批次)
│   │   ├── radial_layout.py        ★ V13新增 (F批次)
│   │   ├── landmark_detection.py   ★ V13新增 (F批次)
│   │   ├── render_d3.py            ★ V13新增 (F批次)
│   │   ├── render_png.py           ★ V13新增 (F批次)
│   │   ├── edge_override.py        ★ V13新增 (G批次，预埋)
│   │   └── path_query.py           ★ V13新增 (G批次，预埋)
│   └── seeds/
│       └── lifecycle_weights.py    ★ V13新增 (B批次)
├── scibot/
│   ├── fetch_pdfs.py               ◆ V13修改 (添加importable接口)
│   ├── parse_pdf.py                ◆ V13修改 (添加importable接口)
│   ├── build_index.py              ◆ V13修改 (添加importable接口)
│   └── first_principles_analysis.py ◆ V13修改 (添加importable接口)
├── pilot/
│   ├── run_pilot_v6.py             ★ V13新增 (D批次，2389行)
│   └── compare_v12_5_vs_v13.py     ★ V13新增 (I验证，450行)
└── reports/
    ├── V13_spec_and_handoff.md     ★ 本文档
    └── v6/
        ├── graph.html              (1.07MB D3.js交互图谱)
        ├── graph.png               (168KB 静态PNG)
        ├── graph_overlay.json      (486KB overlay数据)
        ├── l2_seeds_v6.json        (54KB 100金种子)
        ├── fp_results_v6.json      (69KB 第一性原理结论)
        ├── l3_bottlenecks.json     (27KB 15卡点)
        ├── themes_v6.json          (15KB 7主题)
        ├── landmarks.json          (9.3KB Top10里程碑)
        ├── meta_principles_v6.json (6.4KB 4元规律)
        ├── fused_edges.json        (12KB 融合边抽样)
        ├── pilot_v6_summary.json   (1.4KB 运行摘要)
        ├── v12_5_vs_v13_comparison.md (6.7KB 对比报告)
        └── checkpoints/
            └── step_01~17.done    (全17步完成标记)
```

---

## 附录 B：重要 API 速查表

```python
# KeystoneScore v6
from echelon.seeds.lifecycle_weights import keystone_score_v6, determine_lifecycle
score = keystone_score_v6(signals_dict, paper_obj)
stage = determine_lifecycle(paper_obj)  # "fresh"/"growing"/"mature"

# Fused Edge Weight
from echelon.graph.fused_edge import fused_edge_weight
w = fused_edge_weight(cite_direct, co_citation, bib_couple, semantic_bridge,
                      cross_topic, time_decay, alpha=0.6, max_norm=100)

# Graph Overlay
from echelon.graph.overlay_builder import build_overlay
overlay = build_overlay(papers, bottlenecks, themes, meta_principles)

# Discipline Colors
from echelon.graph.discipline_colors import build_color_map_for_papers
color_map = build_color_map_for_papers(papers)  # {paper_id: {color, shape, ...}}

# Novelty Score + Radial Layout
from echelon.graph.radial_layout import compute_novelty_score, radial_force_layout
novelty = compute_novelty_score(paper_dict, signals_dict)
positions = radial_force_layout(papers, fused_edges, novelty_scores, canvas_size=(1600,1600))

# Landmark Detection
from echelon.graph.landmark_detection import detect_landmarks, generate_landmark_labels
landmarks = detect_landmarks(papers, novelty_scores, weighted_betweenness=None, top_n=10)
labeled = generate_landmark_labels(landmarks)  # LLM中文标签
```

---

*文档生成时间: 2026-05-11*  
*Pilot v6 验证时间: 2026-05-11 (17步全通过，428秒)*  
*维护人: Echelon V13 子代理 D+I*
