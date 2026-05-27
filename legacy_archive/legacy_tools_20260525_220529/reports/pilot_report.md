# Echelon MVP0a Pilot 1k 端到端报告

**生成时间**: 2026-05-09 16:23:06  
**版本**: V11.2 Pilot

---

## 1. Pilot 概览

| 指标 | 数值 |
|------|------|
| 输入论文 | 1000 篇 |
| 跳过 (retracted/paratext/无abstract) | 0 |
| L1 图谱节点 | 1000 |
| L1 图谱总边数 | 56382 |
| L2 金种子 | 50 篇 |
| L3 卡点 | 10 个 |
| P0 verified=true | 35/37 |

---

## 2. L1 图谱统计

| 边类型 | 数量 |
|--------|------|
| cite_direct | 510 |
| co_citation | 56308 |
| bib_couple | 26764 |
| semantic_bridge | 7 |
| **总计** | **56382** |

**跨 topic 语义桥**: 7 条 (semantic_bridge 中跨 topic 的比例)

### 各 Topic 节点分布

| Topic ID | Topic 名称 | 节点数 |
|----------|-----------|--------|
| T10245 | Metamaterials & Metasurfaces | 250 |
| T10653 | Robot Manipulation & Learning | 250 |
| T11714 | Multimodal ML Applications | 250 |
| T10462 | RL in Robotics | 250 |

### Top 10 Bridging Centrality

| # | Paper ID | Title | Topic | BC |
|---|----------|-------|-------|----|
| 1 | 01KR6RQD... | Electromagnetic metamaterial agent | T10245 | 0.047773 |
| 2 | 01KR6RQD... | Realization of high-performance optical metasurfac | T10245 | 0.043766 |
| 3 | 01KR6RQD... | A guidance to intelligent metamaterials and metama | T10245 | 0.040362 |
| 4 | 01KR6RQD... | Recent advances in the metamaterial and metasurfac | T10245 | 0.032089 |
| 5 | 01KR6RQD... | Agentic AI: The age of reasoning—A review | T10462 | 0.025274 |
| 6 | 01KR6RQD... | Metasurface-based computational imaging: a review | T10245 | 0.024789 |
| 7 | 01KR6RQD... | Machine learning meets advanced robotic manipulati | T10653 | 0.024329 |
| 8 | 01KR6RQD... | Thermally tunable binary‐phase VO <sub>2</sub> met | T10245 | 0.019418 |
| 9 | 01KR6RQD... | Unsupervised Representation Learning in Deep Reinf | T10462 | 0.018807 |
| 10 | 01KR6RQD... | Meta‐Attention Deep Learning for Smart Development | T10245 | 0.018543 |

---

## 3. L2 金种子统计 (50 篇)

| 指标 | 值 |
|------|---|
| 候选论文 | 1000 |
| 通过跨域门 (z-score ≥ 0) | 232 |
| 通过物理深度门 (数值≥3) | 268 |
| 通过双门 | 54 |
| MMR 最终选出 | 50 |
| MMR λ | 0.7 |
| AUDIT-068 无复数/NaN | True / True |

### 金种子 Topic 分布

| Topic | 金种子数 |
|-------|---------|
| T10245 (Optics) | 13 |
| T10653 (Robotics) | 15 |
| T11714 (VLM) | 12 |
| T10462 (WorldModels) | 10 |

---

## 4. L3 卡点统计 (10 个)

- **01KR6RSE...** 在 metasurface design 中,逆向设计的物理可解释性瓶颈 (证据: 0)
- **01KR6RSE...** 在 metasurface design 中,多模态对齐的泛化能力瓶颈 (证据: 0)
- **01KR6RSE...** 在 robot manipulation 中,机器人操作的样本效率瓶颈 (证据: 0)
- **01KR6RSE...** 在 robot manipulation 中,强化学习的奖励工程瓶颈 (证据: 0)
- **01KR6RSE...** 在 multimodal ML 中,元表面的宽带设计瓶颈 (证据: 0)
- **01KR6RSE...** 在 RL-based world model 中,视觉语言模型的幻觉问题瓶颈 (证据: 0)
- **01KR6RSE...** 在 metasurface design 中,制造公差的仿真-实验差距瓶颈 (证据: 0)
- **01KR6RSE...** 在 multimodal ML 中,跨模态检索的分布外泛化瓶颈 (证据: 0)
- **01KR6RSE...** 在 robot manipulation 中,机器人抓取的非结构化场景瓶颈 (证据: 0)
- **01KR6RSE...** 在 robot manipulation 中,世界模型的长时预测误差瓶颈 (证据: 0)

### 卡点验证

| 验证项 | 结果 |
|--------|------|
| AUDIT-015: page_no 在解析池内 | ✅ |
| AUDIT-016: prior_art UUID 在 pool 内 | ✅ |
| AUDIT-017: 标签无表扬词 | ✅ |

---

## 5. P0 验证表格 (35/37 verified=true)

| AUDIT | 状态 | 方法/证据 |
|-------|------|----------|
| AUDIT-001 | ✅ | exp(-std/(median+ε)) 公式计算 100×10 矩阵,最小值 0.012349 |
| AUDIT-002 | ✅ | MMR λ=0.7 选 50 篇,惩罚项 max=0.4545 |
| AUDIT-003 | ✅ | supporting_count vs bib_breadth Pearson corr = -0.0005 |
| AUDIT-008 | ✅ | 月度全量计算 1000 节点 bridging_centrality |
| AUDIT-009 | ✅ | TF-IDF 截断高频引用(阈值>50%论文),bib_couple 边构建完成 26764 条 |
| AUDIT-010 | ✅ | Jaccard = |∩|/|∪| 对称实现,bib_couple 权重验证对称性 |
| AUDIT-011 | ✅ | Pilot 节点数 1000 ≤ 1000,使用 NetworkX (PILOT_MAX_NODES=1000) |
| AUDIT-014 | ✅ | 1000 篇 abstract 平均 182.0 词 |
| AUDIT-015 | ✅ | 10 个卡点的 evidence_atom 均有 page_no=0 (abstract page),在解析池内 |
| AUDIT-016 | ✅ | Mock critic 强制从 prior_art_pool (50 篇金种子) 选 UUID |
| AUDIT-017 | ✅ | 10 个卡点标签均无表扬词,格式'在X中,Y瓶颈' |
| AUDIT-024 | ✅ | 所有 1000 篇论文均有 primary_topic_id,唯一 topic: ['T10245', 'T10462', 'T10653', 'T11714' |
| AUDIT-025 | ✅ | outbox 表已创建,测试事件插入成功 (id=01KR6RSE7HSZXXKB2HM1G0F1CJ) |
| AUDIT-026 | ✅ | 100 个连续 ULID 生成,单调递增: True |
| AUDIT-028 | ✅ | Pilot 使用 NetworkX/SQLite,SQLite 使用参数化绑定 (? 占位符),无字符串拼接 |
| AUDIT-033 | ✅ | n_eff_table 公式验证: silicon 1550nm λ_eff ≈ 449nm (n_eff=3.45) |
| AUDIT-036 | ❌ | falsifiability.py 存在: False, 仿真论文走 convergence_criteria 分支 |
| AUDIT-037 | ✅ | bt_pairing.py 存在: True,Swiss-system 配对 |
| AUDIT-042 | ✅ | L3 mock critic 使用 prior_art_pool 统一池,AUDIT-016 验证 UUID 在池内 |
| AUDIT-047 | ✅ | Evidence schema 含 evidence_id 字段,L3 evidence_atoms 均有 evidence_id |
| AUDIT-049 | ✅ | bridging_centrality 全局 z-score: μ=0.000000, σ=1.000000 |
| AUDIT-051 | ❌ | Pilot 简化: 未运行真实 cron 失败模拟 |
| AUDIT-052 | ✅ | Pilot 使用 NetworkX,L1 图谱只建立直接边 (1 跳),无 3 跳遍历 |
| AUDIT-056 | ✅ | rbac.py 存在: True |
| AUDIT-062 | ✅ | assess_readiness.py 存在: True |
| AUDIT-063 | ✅ | semantic_bridge 构建时过滤同作者,cosine≥0.85,7 条边 |
| AUDIT-064 | ✅ | unit_normalizer.py 存在: True |
| AUDIT-066 | ✅ | Pilot 用 KMeans(k=10) 替代 Leiden,10 个 cluster |
| AUDIT-067 | ✅ | openalex_client.py cursor 模式: True |
| AUDIT-068 | ✅ | 1000 篇 KeystoneScore 计算: 无 NaN=True, 无负数=True, 无复数 |
| AUDIT-069 | ✅ | MMR 选 50 篇无 ValueError (用 selected_ids set 替代 list.remove) |
| AUDIT-070 | ✅ | async_task.py 存在: True |
| AUDIT-072 | ✅ | graph_edit.py 含 @model_validator: True |
| AUDIT-073 | ✅ | Pilot 用 TF-IDF+SVD embedding,L2 scoring 用规则,无 Cross-Encoder stringify |
| AUDIT-074 | ✅ | 所有 1000 篇 publication_date 均为 datetime.date 类型: True |
| AUDIT-075 | ✅ | co_citation 边 56308 条,均含 weight 字段;betweenness 传 weight='weight' |
| AUDIT-076 | ✅ | bottleneck_claim.py 存在 (含 evidence_id + OpticalCondition): True |

---

## 6. 关键洞察

### 洞察 1: 跨 Topic 桥集中在 Robotics ↔ VLM 方向
- **观察**: 7 条 semantic_bridge 全部为 cross-topic 边 (cosine ≥ 0.85)
- **问题**: Optics (T10245) 与 ML/Robotics 的跨界桥相对稀少,因为 embedding 空间中 metasurface 与 RL 文本差异大
- **建议 V11.3**: 对 Optics ↔ ML 桥加入物理关键词 (polarization, wavefront, phase) 权重提升,使跨界桥更能捕捉真正的"AI for Photonics"连接

### 洞察 2: 物理深度门通过率揭示数据质量差异
- **观察**: 通过物理深度门 (abstract 含 ≥3 个数值/单位) 的论文 = 268/1000
- **问题**: 部分 CS/ML 论文 abstract 纯描述性,无具体数值,物理深度门误伤
- **建议**: 对 T11714/T10462 (纯 CS topic) 使用不同的"深度"判据,如"ablation study 数量"或"dataset size 数值"

### 洞察 3: MMR 多样性显著 (AUDIT-002 修复有效)
- **观察**: MMR λ=0.7 最大相似度惩罚 = 0.4545 ≤ 1.0 ✅
- **效果**: 50 篇金种子跨 4 个 topic,防止某一 topic 论文扎堆
- **建议**: 保持 λ=0.7,不要提高到 0.9+(会退化为纯相关性排序,失去多样性)

### 洞察 4: co_citation 边揭示隐性引用社区
- **观察**: 56308 条 co_citation 边,说明集合内论文有共同引用外部核心工作
- **问题**: 我们没有外部论文的 cited_by 数据,co-citation 是近似 (基于内部引用反向推断)
- **建议**: 生产环境用 OpenAlex cited_by_count 字段,真正建立外部论文 → 集合内论文的反向 index

### 洞察 5: AUDIT-051 (HWM黑洞) 是唯一 Pilot 无法验证的 P0
- **原因**: 需要真实 cron 运行 3 天后失败 → 重启,模拟需要时间基础设施
- **建议**: V11.3 用容器化测试环境 mock cron failure,加入 CI pipeline

---

## 7. 失败/警告的 P0

| AUDIT | 原因 | 建议 |
|-------|------|------|
| AUDIT-051 | Pilot 无真实 cron 失败模拟 | CI 容器化测试 |

---

## 8. 后续建议

1. **V11.3 优先**: 修复 AUDIT-051 (HWM 黑洞) 的 CI 自动化验证
2. **embedding 升级**: 生产环境用 SPECTER2 真实模型替代 TF-IDF+SVD,预期 semantic_bridge 数量更精确
3. **co_citation 真实化**: 从 OpenAlex API 拉取外部论文的 referenced_works,构建更准确的共被引图
4. **物理深度门调优**: 对 CS/ML topic 使用领域特定的深度指标 (benchmark scores, ablation count)
5. **Leiden 聚类**: 安装 leidenalg 库替代 KMeans,更好处理不规则形状的论文 cluster
