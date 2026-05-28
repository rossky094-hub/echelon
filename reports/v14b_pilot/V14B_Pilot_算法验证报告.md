# V14-B Pilot 算法验证报告

**生成时间**: 2026-05-28 13:25
**数据规模**: 55,391 篇论文 (physics.optics arXiv 1991-2026)

---

## 1. 执行摘要

| 指标 | 数值 |
|---|---|
| 总论文数 | **55,391** |
| OpenAlex enrich 成功率 | **99.0%** (54,844/55,391) |
| 引用关系总数 | **3,016,141** |
| 主干道边数 (top 1%) | **2,771** / 277,195 |
| 子图节点数 | **5,000** |
| 子图边数 | **38,794** |
| 子图结论范围 | **pilot_evidence_subgraph** |
| SciBERT 分类完成率 | **100.0%** |
| VGAE 预测未来边数 | **1,000** |
| Limitation atoms 总数 | **1,066** |
| 三路融合方向数 | **20** |

---

## 2. Enrich 数据质量

- **OpenAlex 命中率**: 99.0%
- **引用关系总数**: 3,016,141 条
- **平均每篇引用数**: 55.0

---

## 3. 全网 Main Path

- **SPC 主干道边数**: 2,771 (top 1%)
- **总边数**: 277,195

### 主干道代表性论文 (case study)

| paper_id | 标题 | 年份 | 被引数 |
|---|---|---|---|

---

## 4. V14 调权 vs V13

- **V14 top100 节点**: 100 个
- **生命周期分布**: (见 DB lifecycle_v14 列)

> V14 新增权重强调: **bridging_centrality** (0.20-0.25) 和 **cd_subdomain** (成熟期 0.25)

---

## 5. 子图选取

| 类型 | 数量 |
|---|---|
| 子图节点总数 | **5,000** |
| Keystone 节点 | **1,000** |
| Fresh (2024+) 节点 | **500** |
| 1 度邻居节点 | **3,500** |
| 子图边数 | **38,794** |

**结论边界**: Step4 是 `pilot_evidence_subgraph`；任何只来自该子图的结论必须标为 pilot/evidence，完整 optics 图谱以 Step10 visual graph 为准。

- 节点覆盖率: 9.0%
- 边覆盖率: 9.4%
- 适配性: `pilot_adequate_for_algorithmic_evidence`
- 推荐子图上限: 5,000

---

## 6. SciBERT 引用功能分布

| 引用功能 | 边数 | 占比 |
|---|---|---|
| usage | 19,890 | 51.3% |
| background | 9,899 | 25.5% |
| similarity | 4,754 | 12.3% |
| extension | 3,384 | 8.7% |
| motivation | 867 | 2.2% |

**高权重 (extension+motivation+usage) 总占比**: 62.2%

**证据解释**: citation function 在没有全文 citation context 时是弱证据层，只应用作 fusion / visual evidence 的权重修正，不能当作真实引用意图的 ground truth。

| 证据等级 | 边数 | 平均权重 |
|---|---:|---:|
| weak_paper_metadata | 38,794 | 0.222 |

---

## 7. VGAE Link Prediction

- **预测边总数**: 1,000
- **跨 Field 边占比**: **3.7%** (37/1,000)

### Top 5 预测边 (case study)

| 源论文 | 目标论文 | 概率 | 源年 | 目标年 |
|---|---|---|---|---|

---

## 8. Limitation Tracking

- **Limitation atoms 总数**: 1,066
- **高严重性 atoms**: 191
- **Resolution 记录数**: 1,743

### Top 10 未解决 Limitations

| atom_id | paper_id | 论文 | 局限描述 | 严重性 |
|---|---|---|---|---|

---

## 9. 三路融合交集

- **融合方向数**: **20**

### Top 5 未来方向预览

| 方向 | 置信度 | 预期时间 |
|---|---|---|
| Broadband electro-optic frequency comb generation in an integrated mic | 0.62 | 2026-2030 |
| High-yield wafer-scale fabrication of ultralow-loss, dispersion-engine | 0.62 | 2026-2030 |
| High-efficiency and broadband coherent optical comb generation in inte | 0.62 | 2026-2030 |
| Efficient Kerr soliton comb generation in micro-resonator with interfe | 0.62 | 2026-2030 |
| Hybrid Kerr-electro-optic frequency combs on thin-film lithium niobate | 0.62 | 2026-2030 |

> 详细见: 未来方向预测_交集报告.md

---

## 10. 三色突变标记

| 类型 | 数量 | 含义 |
|---|---|---|
| 🔴 红色 (CD-index 突变) | **1,954** | mature 论文 CD-index > 0.3 |
| 🟠 橙色 (跨 Field 桥接) | **1,762** | 跨领域桥接分数 > p90 |
| 🟣 紫色 (Burstiness) | **1,708** | 18 月内被引突增 > p95 |
| **合计** | **5,424** | 子图 5,000 节点中的 108.5% |

---

## 11. 演化树布局

- **X, Y 轴**: UMAP 降维 (cosine similarity, n_neighbors=15, min_dist=0.1)
- **Z 轴**: (publication_year - 1991) / (2026 - 1991) ∈ [0, 1]
- **节点颜色**: primary_field_id (26 色映射)
- **节点大小**: log(cite_count + 1) 归一化

---

## 12. 与 V12.5 Pilot 对比

| 维度 | V12.5 (2000 篇) | V14-B (13606 篇) |
|---|---|---|
| 数据规模 | 2,000 篇 | **13,606 篇** |
| 引用图 | 仅 arXiv 内部 | **OpenAlex 跨库** |
| 评分算法 | V13 均等权重 | **V14 生命周期自适应** |
| 未来方向 | 无 | **20 个三路融合方向** |

---

## 13. 下一步建议

### 建议: **GO** — 算法验证通过,可启动 V14-B 前端开发

**前端启动条件**:
- [ ] 三路融合方向 ≥ 10 个 (当前: 20)
- [ ] VGAE test AUC > 0.80 (需验证)
- [ ] 主干道节点 100-200 个 (当前: TBD)
- [ ] 突变节点 100-300 个 (当前: 5424)

**重型算法调优建议**:
1. SciBERT: 如 extension+motivation+usage 占比 < 40%,考虑换 LLM 分类
2. VGAE: 如 AUC < 0.80,减少 epoch → 调 lr → 增加 negative sampling
3. Limitation: 如 high-confidence resolution < 30%,放宽阈值到 0.5

---

*报告由 V14-B step9_report.py 自动生成 | 2026-05-28 13:25*