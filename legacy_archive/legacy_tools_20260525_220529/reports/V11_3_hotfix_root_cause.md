# Pilot 1k 真实根因分析 — 8 项 V11.3 hotfix 候选

**生成时间**:2026-05-10
**数据源**:`/home/user/workspace/echelon_mvp0a/reports/*.json`
**1000 篇真实 OpenAlex 论文,4 topic 跨 3 field**

---

## 摘要

原报告"5 大洞察",经过深度数据分析,实际暴露 **8 个真实根因问题**,其中:
- 🔴 **3 个 V11.2 漏修问题**(R1/R2/R3,本次 Pilot 才暴露)
- 🟠 **5 个 V11.2 已知盲点**(原洞察 1-5,需算法层调整)

**8 个问题中,2 个属于工程铁律级别(R1 评分坍缩、R2 evidence 空壳),不解决无法 P1 启动**。

---

## 🔴 R1 — KeystoneScore 评分坍缩(V11.2 漏修)

### 现象
- Top 10 seeds 的 score 全在 [0.655, 0.683],差异 < 0.03
- z_score 几乎都 < 1.5,看不出谁是真"金种子"
- 说明几何平均+clip 把所有 c_* 拉到接近 0.001,几何平均后差异坍缩

### 根因
AUDIT-068 修复:`safe_clip(c, 0.001, 1.0)` 强制下限 0.001 防复数。
**副作用**:任何低分 c_* 都变 0.001,而几何平均 `(0.001 × 0.5 × 0.5 × 0.5 × 0.5)^(1/5) ≈ 0.219`,
导致大量论文聚集在 [0.2, 0.7] 中段,score 几乎不变。

### 量化
- 1000 篇 KeystoneScore 标准差 σ < 0.05(健康应 ≥ 0.15)
- Top 10 与 Bottom 50 的 score 差 < 0.5(健康应 ≥ 1.5)

### 候选方案
| 方案 | 改法 | 工作量 | 利 | 弊 |
|---|---|---|---|---|
| **A:幂平均替代几何平均** | `(Σ c^p / n)^(1/p)`,p=2 时为均方根 | 2h | 保留区分度 + 不出复数 | 失去"任一为 0 则归零"语义 |
| **B:对数空间求和 + 加性平滑** | `score = Σ log(c + 0.05) / n`(等价加 0.05 平滑的几何平均) | 1h | 保留几何平均语义 + 区分度 | 公式略繁琐 |
| **C:加权几何平均 + clip 提到 0.05** | `safe_clip(c, 0.05, 1.0)` 替代 0.001 | 30min | 最简单 | 仍有坍缩(只是减轻) |

**推荐 B**:对数空间几何平均 + 0.05 平滑,既符合 AUDIT-005(几何平均一票归零的物理意义)又解决坍缩。

### 触发文档修订
- V11.2 第 7 章 §7.2.4(KeystoneScore 公式)
- V11.2 第 4 章 §4.2.3(评分体系)

---

## 🔴 R2 — Evidence 空壳:卡点 evidence_count = 0(V11.2 漏修)

### 现象
- 10 个卡点全部 evidence_count = 0
- AUDIT-015 (page_no valid) 和 AUDIT-017 (no praise) 都报 True,但是空集合上的真也是真(空真)
- 实际上 BottleneckClaim 没绑到任何 evidence_atom

### 根因
Pilot 简化:abstract 当 evidence 文本,但 abstract 平均 200 词,无法切出真正的 evidence span(claim ± 上下 1 句)。
代码层 `extract_evidence_from_abstract()` 返回空列表,但 BottleneckClaim 的 `evidence_id` 字段(AUDIT-047)是必填,Pilot 用 mock UUID 占位,**测试通过但语义空**。

### 候选方案
| 方案 | 改法 | 工作量 | 利 | 弊 |
|---|---|---|---|---|
| **A:abstract 当单 evidence** | abstract 整段作为 1 条 evidence(page_no=0,is_abstract_evidence=True) | 1h | 简单兼容 abstract-only | 物理深度无法验证(abstract 一般不含数值) |
| **B:Pilot 切换真 PDF 解析** | 下载 1000 篇 OA PDF,真跑 pdfplumber + extract_evidence | 12-15h | 数据真实 | 网络/存储/CPU 都翻倍,失败论文 ~15-30% |
| **C:abstract 分句 + 每句一 evidence_atom** | spaCy 分句,每句作为独立 evidence_atom | 3h | 切实可用,evidence 数量提升 | 仍受 abstract 信息密度限制 |

**推荐 C**:abstract 分句方案。Pilot 阶段 abstract 平均 7-12 句,卡点能绑 5-15 evidence。
真 PDF 留到 V12 MVP0b。

### 触发文档修订
- V11.2 第 5 章 §5.4(证据原子定义)
- V11.2 第 8 章 §8.3.2(BottleneckClaim 绑定 evidence)
- 第 14 章 MVP 路线图(MVP0a/0b/1 的数据源升级路径)

---

## 🔴 R3 — Cluster Label 跨 topic 错位(V11.2 漏修)

### 现象
- `[4] 在 multimodal ML 中,元表面的宽带设计瓶颈`(主体错位:metasurface 跟 multimodal 没关系)
- `[5] 在 RL-based world model 中,视觉语言模型的幻觉问题瓶颈`(同样错位)
- 占 10 个 cluster 的 20%,即 1/5 的卡点标签在跨界时混淆

### 根因
KMeans 把不同 topic 的论文聚到一起(因为 cosine 相近),
但 label 模板 `"在 {topic_name} 中, {bottleneck_short_description}"` 用的是 cluster 内**第一篇**或**多数派**论文的 topic。
当 cluster 跨 topic(本来这是好事!揭示跨界桥),label 系统强行硬绑一个 topic,造成错位。

这恰恰是 AUDIT-017 修复的边界案例 — 不是"表扬信",但是"领域错位"。

### 候选方案
| 方案 | 改法 | 工作量 | 利 | 弊 |
|---|---|---|---|---|
| **A:跨 topic cluster 用 "/"** | `[在 metasurface design / multimodal ML 跨界中]` | 1h | 保留双 topic 信息 | 标签长 |
| **B:跨界 cluster 用通用前缀** | `[跨领域: 深度学习+物理建模]` | 2h | 简洁 | 失去具体 topic 信息 |
| **C:label 完全去 topic** | `[逆向设计的物理可解释性瓶颈]`,去掉"在 X 中" | 30min | 简洁 + 无错位 | 失去定位锚点 |

**推荐 A**:跨 topic 用 `/` 连接。当 cluster 主导 topic 占比 < 60% 时触发。

### 触发文档修订
- V11.2 第 7 章 §7.4(Cluster Label 生成)
- 增加边界判定:`is_cross_topic_cluster = top_topic_ratio < 0.6`

---

## 🟠 R4(原洞察 1)— 跨 topic 桥稀少(7 条),光学跨界几乎没有

### 量化
- 总 semantic_bridge 7 条,其中 Optics ↔ ML 仅 1 条
- 桥集中在 Robotics ↔ VLM(2 条)、Robotics ↔ World Models(3 条)
- 注意:Pilot 用 TF-IDF+SVD 256D,信息容量远不如 SPECTER2 768D

### 根因
1. 文本空间差异大:metasurface 论文术语集(plasmonic, antenna, mode)与 ML 论文术语集(transformer, embedding, loss)几乎不重叠,TF-IDF cosine 难达 0.85
2. cosine 阈值 0.85 在 TF-IDF 空间偏严
3. 没有物理-AI 桥关键词权重(diffractive, optical neural network, computational imaging 等本应高权)

### 候选方案
| 方案 | 改法 | 工作量 |
|---|---|---|
| **A:TF-IDF 阈值降到 0.65** | 简单粗暴 | 30min |
| **B:加跨界关键词桥列表** | 38 条 Optics ↔ AI 桥词,匹配则强制建桥 | 4h |
| **C:换 sentence-transformers 模型** | 用 all-MiniLM-L6-v2 (本地 90MB) 代替 TF-IDF+SVD | 2h |

**推荐 B+C 组合**:换 sentence-transformers 后阈值降到 0.7;加 38 条桥词作为兜底。

### 触发文档修订
- V11.2 第 6 章 §6.4.1(semantic_bridge)
- 附录 A:新增物理-AI 桥词表

---

## 🟠 R5(原洞察 2)— 物理深度门误伤纯 CS 论文

### 量化
- 物理深度门通过 268/1000 = 26.8%,主要是 Optics(>80%)
- T11714 (VLM) 通过率 < 10%,T10462 (World Models) < 15%
- VLM 双门通过仅 12 篇(原应 ~50)

### 根因
物理深度规则:abstract 含数值+单位 ≥ 3 个。
VLM/RL 论文确实少有"波长 1550nm,精度 ±0.5dB"这种描述,但有 "achieves 87.3% accuracy on COCO" 等 CS 特定指标。
门判定单一化。

### 候选方案
| 方案 | 改法 | 工作量 |
|---|---|---|
| **A:topic 自适应深度规则** | Optics 用波长/折射率/损耗;CS 用 SOTA% / dataset size / ablation | 6h |
| **B:深度规则 OR 化** | (物理常量数 ≥ 3) OR (CS 量化指标 ≥ 3) OR (实验对比表 ≥ 1) | 4h |
| **C:门通过率 floor** | 每 topic 至少通过 30%(强行抽样) | 1h |

**推荐 B**:OR 化最稳健且符合 AUDIT-065 原意(不歧视 AI 黑盒)。

### 触发文档修订
- V11.2 第 5 章 §5.3(物理深度判定)
- V11.2 第 7 章 §7.3(双硬门)

---

## 🟠 R6(原洞察 3)— MMR λ=0.7 多样性显著有效(无需调整)

### 量化
- 最大惩罚项 0.4545 << 1.0
- 50 篇 4 topic 分布(13/15/12/10),近似均衡
- 无任何单 topic 垄断

### 结论
**不需要调整,MMR 工作良好**,作为基线保持。

### V11.3 文档变更
仅在 V11.3 hotfix 文档中**确认 MMR λ=0.7 通过 1k 实测**。

---

## 🟠 R7(原洞察 4)— co_citation 边主导 56,308 边

### 量化
- co_citation: 56,308 边
- bib_couple: 26,764 边
- cite_direct: 510 边(只占 0.9%)
- semantic_bridge: 7 边

### 根因
1000 篇语料**内部**互引少(都是发表后 12-18 个月新论文,引用关系尚未形成)。
co_citation 是"两篇被同一外部论文引用",所以非常多。
这是数据特性,不是 bug。

### 候选方案
| 方案 | 改法 | 工作量 |
|---|---|---|
| **A:co_citation 加最小阈值** | 共被引次数 ≥ 2 才建边(去噪) | 1h |
| **B:边权重正则化** | 不限边数,但 PageRank 时按边类型加权 | 2h |
| **C:cite_direct 同步拉取** | 在 ingestion 时多拉外部引用源,补全 cite_direct | 8h |

**推荐 A**:简单去噪,不影响算法语义。

### 触发文档修订
- V11.2 第 6 章 §6.3.2(co_citation 计算)

---

## 🟠 R8(原洞察 5)— AUDIT-051 HWM 黑洞

### 状态
Pilot 不可验证(需要真实 cron 失败模拟)

### 候选方案
- A:GitHub Actions CI 容器化模拟(8h)
- B:延后到 V12 MVP0b 验证(0h)

**推荐 B**:Pilot 阶段不阻塞,代码已就位。

---

## 推荐 hotfix 范围(8 项中的 6 项)

| 优先级 | 问题 | 推荐方案 | 工作量 | 阻塞 P1? |
|---|---|---|---|---|
| 🔴 P0-fix | R1 KeystoneScore 坍缩 | B 对数空间 + 0.05 平滑 | 1h | 是 |
| 🔴 P0-fix | R2 Evidence 空壳 | C abstract 分句 | 3h | 是 |
| 🔴 P0-fix | R3 Cluster Label 跨 topic 错位 | A 用 / 连接 | 1h | 是 |
| 🟠 P1-fix | R4 Optics 跨界桥稀少 | B+C 桥词 + sentence-transformers | 6h | 否 |
| 🟠 P1-fix | R5 物理深度误伤 CS | B OR 化 | 4h | 否 |
| 🟢 优化 | R7 co_citation 主导 | A 阈值 ≥ 2 | 1h | 否 |
| ⚪ 跳过 | R6 MMR(已 ok) | 文档确认 | 0h | 否 |
| ⚪ 跳过 | R8 HWM | 延后 V12 | 0h | 否 |

**总工作量:16 小时**

---

## 重跑 Pilot 计划

新语料策略:**时间窗 + 部分 topic 替换**(避免完全过拟合原 1000 篇)
- T10245 Metasurfaces 保留(光学旗舰,需保持基线)
- T10653 Robot Manipulation 替换为 T10208 (Soft Robotics) 或保留
- T11714 Multimodal ML 保留
- T10462 RL Robotics 替换为 T11038 (Computational Imaging) ← 关键!这个 topic 是 Optics ↔ ML 真桥

时间窗:**2022-01-01 ~ 2023-12-31**(完全错开原语料 2024-2026,验证泛化)

新 1000 篇 → 重跑全流程 → 对比 hotfix 前后 8 项指标。
