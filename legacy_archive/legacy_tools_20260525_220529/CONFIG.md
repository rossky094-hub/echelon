# Echelon MVP0a Pilot 配置

## 4 个 OpenAlex Topic(确认)

| Slot | Topic ID | 名称 | Field | Subfield | 总论文数 | Pilot 抽取 |
|---|---|---|---|---|---|---|
| Optics | **T10245** | Metamaterials and Metasurfaces Applications | Materials Science | Electronic, Optical and Magnetic Materials | 70,789 | 250 |
| Robotics | **T10653** | Robot Manipulation and Learning | Engineering | Control and Systems Engineering | 60,252 | 250 |
| VLM | **T11714** | Multimodal Machine Learning Applications | Computer Science | Computer Vision and Pattern Recognition | 62,293 | 250 |
| World Models | **T10462** | Reinforcement Learning in Robotics | Computer Science | Artificial Intelligence | 56,914 | 250 |

**Pilot 总规模**: 1000 篇

**跨度评估**:
- 4 个 topic 横跨 **3 个 Field**(Materials Science / Engineering / Computer Science)
- 4 个 topic 横跨 **4 个 Subfield**
- 这是真正的"AI4Science 跨界压力测试" — semantic_bridge / bridging_centrality 必须能拓出 Optics ↔ VLM / Robotics ↔ Optics 的桥

## Pilot 抽取规则

- 时间范围:2024-01-01 ~ 2026-05-09(近 17 个月)
- 来源:OpenAlex 最新 + arXiv preprint(优先)
- 排除:retracted=true、is_paratext=true、authorships 为空
- 必须有:abstract、引用列表、language=en
- API 调用:`pyalex.Works().filter(primary_topic={"id": "<TOPIC>"}, ...).paginate(per_page=200, cursor="*")`
  - **AUDIT-067 必修**:必须用 cursor,不用 page

## 目录结构

```
/home/user/workspace/echelon_mvp0a/
├── CONFIG.md                     # 本文件
├── echelon/                      # 核心代码
│   ├── __init__.py
│   ├── core/                     # P0 基础设施
│   │   ├── ulid_utils.py         # ULID 主键 (AUDIT-026)
│   │   ├── openalex_client.py    # cursor 分页 (AUDIT-067)
│   │   ├── topic_mapper.py       # topic_id 映射 (AUDIT-024)
│   │   ├── outbox.py             # 双写 outbox (AUDIT-025)
│   │   ├── unit_normalizer.py    # Pint 单位归一 (AUDIT-064)
│   │   └── async_task.py         # 异步任务模式 (AUDIT-070)
│   ├── schema/                   # Pydantic v2 schema
│   │   ├── paper.py
│   │   ├── evidence.py
│   │   ├── bottleneck_claim.py   # 含 evidence_id (AUDIT-047) + condition: OpticalCondition (AUDIT-059)
│   │   ├── graph_edit.py         # @model_validator (AUDIT-072)
│   │   └── falsifiability.py     # 分支 schema (AUDIT-036)
│   ├── ingest/                   # 节点 -3
│   │   ├── arxiv_fetcher.py
│   │   ├── openalex_fetcher.py
│   │   └── retraction_check.py
│   ├── pdf/                      # 节点 -2 + -1 (AUDIT-014/015)
│   │   ├── parser.py             # 保留 page 元数据
│   │   └── extract_evidence.py
│   ├── graph/                    # 节点 5 L1 (AUDIT-008/009/010/011/012/049/050/052/063/066/067/074/075/076)
│   │   ├── build_l1.py
│   │   ├── cocite.py
│   │   ├── bib_couple.py
│   │   ├── semantic_bridge.py
│   │   ├── shared_dataset.py
│   │   └── centrality.py
│   ├── seeds/                    # 节点 6 L2 (AUDIT-001/002/003/005/068/069)
│   │   ├── score_calibre.py
│   │   ├── score_keystone.py     # 几何平均 + clip
│   │   ├── mmr.py                # 替代 DPP (AUDIT-002 + AUDIT-069)
│   │   └── cross_domain_gate.py
│   ├── bottleneck/               # 节点 7 L3 (AUDIT-015/016/017/018/057/058)
│   │   ├── cluster.py            # CPM + γ 调优 (AUDIT-066)
│   │   ├── extract_claim.py      # Prompt v2 + Schema 校验
│   │   ├── debate_critic.py      # prior_art_pool 注入
│   │   ├── label_generator.py    # 先收敛后生 label (AUDIT-017)
│   │   └── minicheck_scorer.py   # AUDIT-023/057/071
│   ├── physics/                  # AUDIT-033/036
│   │   ├── n_eff_table.py
│   │   └── falsifiability.py
│   └── vrl/                      # AUDIT-062
│       └── assess_readiness.py
├── data/                         # Pilot 数据
│   ├── raw/                      # 原始 arXiv/OpenAlex JSON
│   ├── pdfs/                     # 下载的 PDF
│   └── parsed/                   # 解析后的证据原子
├── db/                           # SQLite/PG schema 与 dump
│   ├── ddl.sql                   # 含 ULID/version/HWM
│   └── pilot.db
├── reports/                      # 验证报告
│   ├── l1_graph_stats.json
│   ├── l2_seeds.json
│   ├── l3_bottlenecks.json
│   ├── p0_validation.json        # 31 条 P0 是否真修复
│   └── pilot_report.md
├── tests/                        # 单元测试 + 反幻觉测试
│   ├── test_p0_audits.py         # 每条 P0 一个 unit test
│   └── test_pydantic_validators.py
└── run_pilot.py                  # 主流程脚本
```

## Pilot 验证 P0 修复的硬指标

| AUDIT | 验证方法 |
|---|---|
| AUDIT-068 几何平均复数 | 1000 篇 KeystoneScore 计算后断言无 NaN/复数 |
| AUDIT-069 DPP ValueError | MMR 选 50 篇,无 ValueError |
| AUDIT-067 cursor 分页 | 实际能拉到 1000 篇(若仍用 page,理论 10000 才阻断,但要看代码是否走 cursor) |
| AUDIT-074 datetime - str | 所有 publication_date 操作不抛 TypeError |
| AUDIT-072 Pydantic v2 validator | merge/split 编辑能成功通过 |
| AUDIT-024 topic_id | DDL 中 primary_topic_id 字段就位,SQL 查询正确 |
| AUDIT-051 HWM 黑洞 | 模拟 cron 失败 3 天 → 重启后所有数据补齐 |
| AUDIT-052 3 跳爆炸 | Cypher 限 1-2 跳,5s 超时 |
| AUDIT-026 ULID | 100 个连续插入,主键 monotonically increasing |
| AUDIT-047 evidence_id 字段 | 守门代码不抛 AttributeError |
| AUDIT-002 MMR | 多样性精排 50 篇,惩罚项 ∈ [0,1] |
| AUDIT-001 consistency 公式 | 跨论文 consistency 计算无负数 |
| AUDIT-003 共线性 | KeystoneScore 三大子分相关性 < 0.7 |
| AUDIT-008 bridging_centrality | 月度全量 + 增量 sb_count proxy 都跑通 |
| AUDIT-009/010 entity_overlap | 1000 篇全组合不 OOM,Jaccard 对称 |
| AUDIT-011 NetworkX | 下推 Neo4j GDS,5w 边查询 < 30s |
| AUDIT-014 abstract 截断 | 读完整 abstract,平均 ≥ 200 词 |
| AUDIT-015 evidence_page 编造 | LLM 输出的 page_no 在解析的 evidence_pool 内 |
| AUDIT-016 Critic UUID | Critic 的 UUID 引用必在 prior_art_pool 内 |
| AUDIT-017 Cluster 标签表扬信 | 50 个 cluster 标签人工抽审,无表扬信 |
| AUDIT-025 双写脑裂 | Outbox 表存在,Debezium CDC 无双写 |
| AUDIT-028 Cypher 注入 | 字符串拼接被禁,纯参数化绑定 |
| AUDIT-033 真空光速 | n_eff_table 调用,silicon 1550nm 算出 ~1290nm 等效波长 |
| AUDIT-036 alpha/power FDTD | 仿真论文走 convergence_criteria,实验论文才用 alpha/power |
| AUDIT-037 BT 870 次预算 | Swiss-system 配对实际只跑 ~129 次 |
| AUDIT-042 Prior-Art 双桶 | RRF 融合,不分双桶 |
| AUDIT-056 RBAC | 应用层 user_role 校验 |
| AUDIT-062 VRL 无人区 | has_counterevidence=False + 跨 ≥2 子领域 → VRL2+ |
| AUDIT-070 异步 API | 增量 API 返回 task_id 202,不超时 |
| AUDIT-073 Cross-Encoder 字符串化 | 文本/向量分离,无 stringify |
