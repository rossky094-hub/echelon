# V14-B Evidence Decision 算法验证报告

**生成时间**: 2026-05-31 02:04
**数据规模**: 55,391 篇论文 (corpus=all)

---

## 1. 执行摘要

| 指标 | 数值 |
|---|---|
| 总论文数 | **55,391** |
| OpenAlex W 覆盖率 | **64.4%** (35,663/55,391) |
| Field/Topic 覆盖率 | **99.9%** (55,359/55,391) |
| 引用关系总数 | **3,215,130** |
| 主干道边数 (top 1%) | **2,775** / 277,526 |
| 子图节点数 | **5,000** |
| 子图边数 | **38,538** |
| 子图结论范围 | **pilot_evidence_subgraph** |
| Citation-function evidence 覆盖率 | **100.0%** |
| Future candidate generator 候选边数 | **1,000** |
| Limitation atoms 总数 | **730** |
| 三路融合方向数 | **5** |

---

## 2. OpenAlex / Field 覆盖质量

- **OpenAlex W 覆盖率**: 64.4% (35,663/55,391)
- **Field/Topic 覆盖率**: 99.9% (55,359/55,391)
- **openalex_enriched 标记覆盖**: 99.2%；这是历史元数据标记，不等同于 OpenAlex W 或 field/topic 决策覆盖。
- **结论边界**: OpenAlex/field coverage is not a success claim; cross-field, bridge, and topic-color conclusions must carry uncertainty until coverage gates pass.
- **引用关系总数**: 3,215,130 条
- **平均每篇引用数**: 58.0

---

## 3. 全网 Main Path

- **SPC 主干道边数**: 2,775 (top 1%)
- **总边数**: 277,526

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
| 子图边数 | **38,538** |

**结论边界**: Step4 是 `pilot_evidence_subgraph`；任何只来自该子图的结论必须标为 pilot/evidence，完整 all 图谱以 Step10 visual graph 为准。

- 节点覆盖率: 9.0%
- 边覆盖率: 9.3%
- 适配性: `pilot_adequate_for_algorithmic_evidence`
- 推荐子图上限: 5,000

---

## 6. Citation Function Evidence

| 引用功能 | 边数 | 占比 |
|---|---|---|
| usage | 19,737 | 51.2% |
| background | 9,936 | 25.8% |
| similarity | 4,786 | 12.4% |
| extension | 3,240 | 8.4% |
| motivation | 839 | 2.2% |

**高权重 (extension+motivation+usage) 总占比**: 61.8%

**证据解释**: citation function 在没有全文 citation context 时是弱证据层，只应用作 fusion / visual evidence 的权重修正，不能当作真实引用意图的 ground truth。

| 证据等级 | 边数 | 平均权重 |
|---|---:|---:|
| weak_paper_metadata | 38,538 | 0.222 |

---

## 7. Future Candidate Generator

- **候选边总数**: 1,000
- **跨 Field 候选边占比**: **6.0%** (60/1,000)

**证据边界**: GNN/VGAE 只生成 future candidate edges；`predicted_prob`/`calibrated_prob` 是候选排序信号，不是方向结论。进入 Radar/Topic Dossier 需要 Step6 fusion + Step13 complete Claim Card + calibration audit。

### Top 5 候选边 (case study)

| 源论文 | 目标论文 | 候选概率 | 源年 | 目标年 |
|---|---|---|---|---|

---

## 8. Limitation Tracking

- **Limitation atoms 总数**: 730
- **高严重性 atoms**: 83
- **Resolution 记录数**: 1,001

### Top 10 未解决 Limitations

| atom_id | paper_id | 论文 | 局限描述 | 严重性 |
|---|---|---|---|---|

---

## 9. 三路融合交集

- **融合方向数**: **5**

### Top 5 未来候选证据合同预览

| 候选方向 | 排序分数 | claim_scope | evidence_grade | Radar 状态 | uncertainty_reasons |
|---|---:|---|---|---|---:|
| Broadband electro-optic frequency comb generation in an integrated mic | 0.81 | exploratory_with_claim_card | exploratory | exploratory_claim_card | 4 |
| High-yield wafer-scale fabrication of ultralow-loss, dispersion-engine | 0.81 | exploratory_incomplete_card | exploratory | candidate_pool_only | 8 |
| Coherent Raman spectro-imaging with laser frequency combs | 0.81 | exploratory_incomplete_card | exploratory | candidate_pool_only | 9 |
| Photo-induced cascaded harmonic and comb generation in silicon nitride | 0.81 | exploratory_incomplete_card | exploratory | candidate_pool_only | 9 |
| 11 TeraFLOPs per second photonic convolutional accelerator for deep le | 0.81 | exploratory_incomplete_card | exploratory | candidate_pool_only | 9 |

> 详细见: 未来候选方向_证据合同报告.md

---

## 10. 三色突变标记

| 类型 | 数量 | 含义 |
|---|---|---|
| 🔴 红色 (CD-index 突变) | **2,031** | mature 论文 CD-index > 0.3 |
| 🟠 橙色 (跨 Field 桥接) | **1,058** | 跨领域桥接分数 > p90 |
| 🟣 紫色 (Burstiness) | **1,790** | 18 月内被引突增 > p95 |
| **合计** | **4,879** | 子图 5,000 节点中的 97.6% |

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
| 引用图 | 仅 arXiv 内部 | **DOI/arXiv/OpenAlex/S2 exact relinking；linked-ref 低覆盖时仍需 uncertainty** |
| 评分算法 | V13 均等权重 | **V14 生命周期自适应** |
| 未来方向 | 无 | **5 个三路融合方向** |

---

## 13. 下一步建议

### 决策状态: **EVIDENCE_GATED** — 候选方向可用于补证据,但 Topic Dossier / Claim Card / Radar 不得高置信放行

**证据决策放行条件**:
- [ ] Topic Dossier multi-topic regression 通过四个基准 topic,不是只让 Metalens 好看
- [ ] linked refs >= 30%；低于门槛时 Main/Cite 演化只能标为 uncertainty
- [ ] section evidence 覆盖 main/future/branch/keystone 关键论文和 topic-gap 队列
- [ ] future candidates 有 rolling held-out-year calibration audit；否则只能进 candidate_pool
- [ ] Radar 主视图只允许完整 Step13 Claim Card,裸 GNN/VGAE 边只能作为证据补齐目标

**下一步证据工作**:
1. Citation function: 如 extension+motivation+usage 占比 < 40%,先补 citation context 或运行 capped LLM edge audit 抽检；LLM 结果只能作为弱标签,不能直接升级结论
2. VGAE / future candidates: 若 calibration audit 未通过,保持 candidate_pool_only；优先补 rolling held-out-year 校准和反例分析,不是追求裸边数量
3. Limitation/resolution: 如 high-confidence resolution < 30%,保持 exploratory / candidate_pool, 优先补 limitation/discussion/resolution section evidence 与 linked resolution evidence；阈值不得下调来晋升高置信

---

*报告由 V14-B step9_report.py 自动生成 | 2026-05-31 02:04*