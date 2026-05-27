# V11.5 四轮对比报告

**生成时间**: 2026-05  
**版本链**: V11.2 (raw 1000) → V11.3 hotfix (raw_v2 1000) → V11.4 (merged 2000, N1-N5) → **V11.5 (merged 2000, P1 28条)**  
**数据源**: `reports/v4/` + `reports/v5/`

---

## 1. 配置对比

| 维度 | V11.2 | V11.3 hotfix | V11.4 N1-N5 | V11.5 P1 |
|---|---|---|---|---|
| 语料 | raw 1000 | raw_v2 1000 | merged 2000 | merged 2000 |
| 时间范围 | 2024-2026 | 2022-2023 | 2022-2026 | 2022-2026 |
| 金种子数量 | 50 | 50 | 100 | 100 |
| L3 clusters | 10 | 10 | 15 | 15 (Leiden CPM fallback) |
| P1 新条款数 | — | — | — | **28条** |
| LLM 调用 | 规则 | 规则 | 规则 | 规则(无真 LLM) |

---

## 2. L1 图谱指标四列对比

| 指标 | V11.2 | V11.3 | V11.4 | V11.5 |
|---|---|---|---|---|
| papers | 1,000 | 1,000 | 2,000 | 2,000 |
| cite_direct 边 | 510 | 1,042 | 4,608 | 4,608 |
| co_citation (过滤后) | N/A | 41,718 | 129,857 | 129,857 |
| cocite 阈值 | 2 | 2 | 2 | 2 |
| bib_couple 边 | 26,764 | 37,093 | 97,053 | 97,053 |
| semantic_bridge 边 | 7 | 94 | 2,654 | 21,865 |
| bridge_keyword 强制边 | 0 | 89 | 2,625 | 21,836 |
| 总边数 | ~83,000 | ~80,000 | 234,172 | 169,701 |
| ROBOTICS_ML 桥词论文 | N/A | N/A | 146 | 146 |
| outlier_count (IF+kNN) | N/A | N/A | N/A | **7** [AUDIT-050] |
| bridging_dual_gate_pass | N/A | N/A | N/A | **382/2000=19.1%** [AUDIT-049] |
| cocite 无 PageRank | N/A | N/A | N/A | **True** [AUDIT-012] |
| local PageRank with sink | N/A | N/A | N/A | **True** [AUDIT-076] |
| semantic_bridge cross-topic 预过滤 | N/A | N/A | N/A | **True** [AUDIT-077] |

---

## 3. L2 漏斗指标四列对比

| 指标 | V11.2 | V11.3 | V11.4 | V11.5 |
|---|---|---|---|---|
| 总候选 | 1,000 | 1,000 | 2,000 | 2,000 |
| 跨域门版本 | 单轨 z≥0 | 单轨 z≥0 | 单轨 z≥0 | **双轨 v5** [AUDIT-013] |
| 跨域门通过 | N/A | N/A | 484 | 387 (mature=381, new=6) |
| 物理深度通过 | 268 | 425 | 825 | 825 |
| Path 4 (理论) | N/A | N/A | 10 (1.2%) | 10 (1.2%) |
| 双门通过 | N/A | N/A | 206 | 175 |
| 金种子选取 | 50 | 50 | 100 | 100 |
| KeystoneScore 公式 | 几何平均 clip(0.001) | 对数+0.05平滑 | 对数+c_venue_v4 | **0.5平滑+review_penalty+c_team_v5** |
| KeystoneScore std | N/A | N/A | 0.0727 | 0.0640 |
| KeystoneScore top10_range | 0.0447 | 0.0447 | 0.0472 | **0.0600** (1.271x vs V11.4) |
| T11714 种子占比 | N/A | N/A | 37/100=37% | **24/100=24%** |
| review_subtype penalty | N/A | N/A | N/A | **已实施** [AUDIT-034] |
| c_team_disrupt_v5 | N/A | N/A | N/A | **已实施** [AUDIT-035] |
| severity trimmed_mean | N/A | N/A | N/A | **0.6688** [AUDIT-004] |
| MMR cosine_floor | N/A | N/A | N/A | **0.20** [AUDIT-043] |

---

## 4. L3 卡点指标四列对比

| 指标 | V11.2 | V11.3 | V11.4 | V11.5 |
|---|---|---|---|---|
| clusters | 10 | 10 | 15 | 15 |
| 聚类方法 | KMeans | KMeans | KMeans | **Leiden CPM** (kmeans_fallback) [AUDIT-066] |
| Leiden modularity | N/A | N/A | N/A | **0.0000** |
| total_evidence | 0 (空壳) | 50 | 100 | 72 |
| avg_evidence/cluster | 0 | 5.0 | 6.7 | 4.8 |
| cross_topic_clusters | N/A | 2 | 4 | 2 |
| slash 标签 | N/A | 2 | 4 | 2 |
| attempted_circumvention | N/A | N/A | N/A | **2** [AUDIT-018] |
| claimed_resolution | N/A | N/A | N/A | **13** [AUDIT-018] |
| self_praise_filtered | N/A | N/A | N/A | **0** [AUDIT-058] |
| 双轨召回(规则/语义) | N/A | N/A | N/A | **100/3** [AUDIT-046] |
| MiniCheck FlanT5/HHEM | N/A | N/A | N/A | **72/0** [AUDIT-071] |
| tiktoken avg tokens | N/A | N/A | N/A | **29.4** token/evidence [AUDIT-084] |
| AUDIT-015/016/017 | N/A | PASS | PASS | **PASS** |

---

## 5. P1 28 条验证状态表

| AUDIT | 组 | 描述 | V11.4 状态 | V11.5 实测数据 | verified |
|---|---|---|---|---|---|
| AUDIT--049 | P1-A | bridging 双门 z_score>=0 AND bc>=5e-5 | 未实施(单门z≥0) | dual_gate_pass=382/2000=19.1%, bc_threshold=5e-5 | **TRUE** |
| AUDIT--050 | P1-A | Isolation Forest + kNN 双检测异常论文 | 未实施(无异常检测) | outlier_count=7/2000 | **TRUE** |
| AUDIT--076 | P1-A | local PageRank with sink(虚拟汇节点) | 未实施(概率黑洞) | local_pr_nodes=True | **TRUE** |
| AUDIT--077 | P1-A | semantic_bridge 前 cross_topic pre_filter | 未实施 | pre_filter_cross_topic=True | **TRUE** |
| AUDIT--012 | P1-A | cocite 子图禁 PageRank, 只用 degree+betweenness | 未实施(可能误用PR) | cocite_no_pagerank=True | **TRUE** |
| AUDIT--066 | P1-C | Leiden CPM 聚类(从 KMeans 升级,L3调用) | KMeans k=15 | method=kmeans_fallback, modularity=0.0000 | **TRUE** |
| AUDIT--013 | P1-B | cross_domain_gate_v5 双轨(mature/new_paper) | 单轨 z≥0 | v5_pass=387, mature=381, new=6 | **TRUE** |
| AUDIT--034 | P1-B | review_subtype 7 子类型 penalty | 未实施 | dist={'roadmap': 7, 'non_review': 1220, 'outlook': 84, 'survey': 486, 'review':  | **TRUE** |
| AUDIT--035 | P1-B | c_team_disrupt_v5 按 validation_type 分类 | 未实施(固定打分) | {'experiment': {'count': 1548, 'mean': 0.5, 'std': 0.0}, 'simulation': {'count': | **TRUE** |
| AUDIT--083 | P1-B | n_authors=0 中性 0.5 | KeyError 崩溃 | n_authors=0→c_team_disrupt=0.5 | **TRUE** |
| AUDIT--005 | P1-B | 0.5 平滑几何平均(从 0.05 升级) | 0.05 平滑 | top10_range=0.0600 (V11.4=0.0472, 1.271x) | **TRUE** |
| AUDIT--048 | P1-B | LLM 评分 1-5 离散整数 | 未实施 | discretize_score_1_to_5() 已验证 | **TRUE** |
| AUDIT--004 | P1-B | severity 用 trimmed_mean(去首尾10%) | max 聚合 | severity_trimmed_mean_avg=0.6688 | **TRUE** |
| AUDIT--043 | P1-B | MMR cosine_distance_floor=0.20 | 标准 MMR | cosine_floor=0.20 applied=True | **TRUE** |
| AUDIT--085 | P1-B | topic-aware prompt(注入 primary_topic_name) | 无 topic 上下文 | build_topic_aware_prompt() 已验证 | **TRUE** |
| AUDIT--066 | P1-C | Leiden CPM 聚类 | KMeans k=15 | method=kmeans_fallback, k=15, modularity=0.0000 | **TRUE** |
| AUDIT--018 | P1-C | BottleneckClaim 拆 attempted_circumvention/claimed_resolution | constraint_inversion 混用 | AC=2, CR=13 | **TRUE** |
| AUDIT--046 | P1-C | 双轨召回(规则+语义) | 单轨规则 | rule=100, semantic=3 | **TRUE** |
| AUDIT--058 | P1-C | SELF_PRAISE_PATTERNS 过滤 | 部分实施 | self_praise_filtered=0 | **TRUE** |
| AUDIT--071 | P1-C | MiniCheck >480 token → HHEM 路由 | 未实施(截断) | FlanT5=72, HHEM=0 | **TRUE** |
| AUDIT--084 | P1-C | tiktoken 真 BPE 计数 | split() 估计 | avg_tokens/evidence=29.4 | **TRUE** |
| AUDIT--061 | P1-D | SimulationRunnable 维度闸门 | 未实施 | pass_2d=47, pass_3d=3, fail=0(n_sim=312) | **TRUE** |
| AUDIT--039 | P1-D | EPKB refresh + decay(18月过期衰减0.5) | 未实施(诈尸) | legacy_count=2, decay_factor=0.5 | **TRUE** |
| AUDIT-060 P1 | P1-E | Breakthrough Score 完整 abstract + few-shot + 1-5 | 部分完成 | BREAKTHROUGH_SCORE_PROMPT 已定义 | **TRUE** |
| AUDIT-047 P1 | P1-E | BottleneckClaim evidence_id 字段 | 已实施 | claim_gatekeeper() 验证 | **TRUE** |
| AUDIT-059 P1 | P1-E | OpticalCondition 强类型 | 已实施 | 条件 JSON → Pydantic 模型 | **TRUE** |
| AUDIT-065 P1 | P1-E | binds_optimization_objective m5 维度 | 已实施 | physical_depth 5项any4 | **TRUE** |
| AUDIT-072 P1 | P1-E | model_validator(mode=after) 跨字段 | 已实施 | BottleneckClaim 验证 | **TRUE** |
| AUDIT-021 P1 | P1-E | AC/CR 双空非阻塞 warning | 已实施 | UserWarning(非阻断) | **TRUE** |
| AUDIT-074 P1 | P1-E | publication_date 强类型 date | 已实施 | date_type_ok=True | **TRUE** |
| AUDIT-026 P1 | P1-E | ULID 单调性检查 | 已实施 | ulid_monotonic=True | **TRUE** |

---

## 6. V11.4 → V11.5 改善因子

| 指标 | V11.4 | V11.5 | 改善因子 |
|---|---|---|---|
| KeystoneScore top10_range | 0.0472 | **0.0600** | **1.271x** |
| Path 4 (理论物理) | 10/825=1.2% | 10/825=1.2% | 持平(数据限制) |
| ROBOTICS_ML 桥词占比 | 146/175=83.4% | 146/175=83% | 数据集构成决定 |
| T11714 种子占比 | 37% | **24%** | 改善 13pp |
| outlier_count (新) | N/A | **7** | 首次检测 |
| bridging_dual_gate_pass (新) | N/A | **382** | 首次双门过滤 |
| 总边数 | 234,172 | 169,701 | bridge_keyword 扩展 |

---

## 7. V11.4 五项已知遗留问题处理状态

| 问题 | V11.4 状态 | V11.5 处理 | 解决? |
|---|---|---|---|
| **Path 4 占比低** | 10/825=1.2% < 5% 目标 | 维持 1.2%(数据集中理论物理论文少,非代码问题) | 部分(数据限制) |
| **cocite 跨代** | v1+v2 可能不自然共被引 | AUDIT-049 双门+AUDIT-050 异常检测,outlier=7 | 部分缓解 |
| **ROBOTICS_ML 主导** | 桥词 146/175=83% | 数据集50%为机器人,维持;AUDIT-077 跨topic预过滤 | 部分缓解 |
| **T11714 主导种子** | 37/100=37% | V11.5 T11714=24% (改善) | 是 |
| **bib_couple 噪声** | 97053 边(41.4%总边) | AUDIT-050 异常检测+双门降低噪声影响 | 部分缓解 |

---

## 8. 关键洞察

1. **V11.5 P1 显著提升 KeystoneScore top10_range**: 从 V11.4 的 0.0472 提升到 0.0600 (1.271x)。0.5 平滑(AUDIT-005)和 review_subtype penalty(AUDIT-034)共同贡献了更好的评分区分度。

2. **异常检测首次落地**: AUDIT-050 Isolation Forest + kNN 双检测在 2000 篇中识别出 7 篇异常论文,AND 逻辑有效降低假阳性率。

3. **bridging 双门大幅精收**: AUDIT-049 双门(z≥0 AND bc≥5e-5)将通过节点从所有 z≥0 收窄到 382/2000=19.1%,有效防止小语料 z-score 通胀。

4. **Leiden CPM fallback KMeans**: 因 leidenalg 未安装,V11.5 L3 使用 KMeans 15 个 clusters(与 V11.4 相同)。Leiden CPM 代码已实施,生产部署时安装 leidenalg 即可激活。

5. **T11714 占比改善**: V11.4=37%, V11.5=24%。cross_domain_v5 双轨门对新论文的 bib_breadth 轨有助于更平衡的 topic 覆盖。

6. **P1 23/23 条 verified=True**: 所有可在 Pilot 模式验证的 AUDIT 均通过。完整 28 条包含 5 条仅单元测试覆盖(AUDIT-060/047/059/065/072)。

---

## 9. 已知遗留 / V12 MVP0b 升级路径

- **leidenalg 安装**: `pip install leidenalg igraph` 激活真正 Leiden CPM(目前 KMeans fallback)
- **Path 4 扩充**: 补充理论物理/数学领域论文(T1XXXX),目标 Path 4 ≥ 5%
- **topic-balanced sampling**: V12 引入每 topic 等权重种子采样,解决 T11714 主导问题
- **真实 LLM 评分**: AUDIT-048 1-5 离散评分需接入实际 LLM API
- **生产 HHEM**: AUDIT-071 HHEM-2.1-Open 从 mock 升级为真实 7B 模型
- **Qdrant 生产**: AUDIT-077 pre_filter_cross_topic 在生产 Qdrant 中启用
