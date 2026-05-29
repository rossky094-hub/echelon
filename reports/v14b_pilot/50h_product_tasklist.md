# V14B 50-Hour Product-Value Task List

This checklist is the execution queue while section/OpenAlex frontfill runs.  Each item has an explicit output and gate so work is measured by product value, not by whether a graph can merely render.

| ID | Window | Task | Output | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| P0-01 | 0-3h | 固定当前指标快照 | product_baseline_snapshot.{json,md} | papers/OpenAlex/section/linked refs/Claim Cards/visual graph counts are recorded | in_progress |
| P0-02 | 0-3h | 建立 Metalens 验收基准 | metalens expected branches and quality gaps in baseline snapshot | Metalens branches, bottlenecks, turning-paper evidence, future evidence are scored | in_progress |
| P0-03 | 0-3h | 写 Topic Dossier 质量 rubric | Topic Dossier rubric in baseline snapshot | generic statements are demoted unless backed by clickable evidence | in_progress |
| P1-04 | 3-8h | 做 Metalens gold topic fixture | tests/v14b Metalens regression fixture | fixture includes imaging, achromatic, high-NA, tunable, manufacturing, computational compensation | todo |
| P1-05 | 3-8h | Metalens 分支识别自动测试 | automated topic-lens regression | each expected branch returns driver papers, bottleneck, enabler, evidence gap | todo |
| P1-06 | 3-8h | Metalens 审计报告 | reports/v14b_pilot/metalens_topic_regression.md | report shows what improved, what is still generic, and which evidence is missing | todo |
| P2-07 | 8-14h | Topic Lens 结论 evidence_objects 化 | API returns evidence_objects for every branch/bottleneck/turning/future statement | evidence types include paper, section, limitation_atom, main_path_edge, branch_lineage, future_candidate | todo |
| P2-08 | 8-14h | 无证据结论降级 | insufficient_evidence blocks in Topic Dossier | no evidence-backed UI card is rendered from naked prose | todo |
| P2-09 | 8-14h | 前端可点击证据闭环 | branch/bottleneck/turning/future cards open paper/section/evidence detail | each visible conclusion has an inspectable evidence drawer | todo |
| P3-10 | 14-19h | Step13 五问 Claim Card 硬约束 | Claim Card quality gate | missing root/history/enabler/bottleneck/experiment prevents Radar promotion | todo |
| P3-11 | 14-19h | Radar 主视图只展示完整卡 | candidate pool separated from R&D Radar | GNN-only edges are never shown as investable directions | todo |
| P3-12 | 14-19h | Claim Card 缺口提示 | missing_gates, claim_scope, evidence_strength in API/UI | user can see exactly why a candidate is not actionable | todo |
| P4-13 | 19-24h | Access Link 完整性审计 | access gap table/report | key turning papers, branch drivers, future endpoints are audited | todo |
| P4-14 | 19-24h | 自动合成外部访问链接 | arXiv/DOI/S2/OpenAlex links in paper detail | known IDs produce clickable links; missing IDs become explicit access gaps | todo |
| P4-15 | 19-24h | 前端显示 local evidence / external access / access gap | paper detail access panel | researchers know whether they can inspect local evidence or must open an external source | todo |
| P5-16 | 24-30h | Delta section 自动接力 | top12000 completion handoff to section-evidence-delta | if primary sections are below target, delta queue starts once and only once | todo |
| P5-17 | 24-30h | Delta queue 优先级审查 | main/future/branch/keystone/Metalens coverage report | next crawl is evidence-budgeted, not blind sweeping | todo |
| P5-18 | 24-30h | 资源保护 | single-process guard, disk floor, temp PDF cleanup | no duplicate crawler and no persistent full-PDF cache | todo |
| P6-19 | 30-35h | 后段链路 smoke test | Step5c -> Step6 -> Step13 -> Step10 partial run log | schema, empty-table, quality-gate, frontend breaking issues are found before final run | todo |
| P6-20 | 30-35h | 修复 smoke test 阻断点 | reviewable fixes with tests | fixes preserve algorithmic semantics and serve project goals | todo |
| P7-21 | 35-40h | Branch Lineage 解释增强 | parent, split reason, driver papers, constraint shift in branch cards | layout-only clusters are labeled layout_cluster_only, not true branches | todo |
| P7-22 | 35-40h | Topic Dossier 分支可信度门 | evidence-backed branch vs weak cluster distinction | only evidence-backed branches are narrated as real branch evolution | todo |
| P8-23 | 40-44h | Future Growth 可解释化 | GNN/VGAE candidate generator explanation | each future candidate shows model probability, calibration, bottleneck, Step6/13 status | todo |
| P8-24 | 40-44h | Future candidate 到 Claim Card 的转化路径 | candidate pool lifecycle state | no Claim Card means no Radar promotion | todo |
| P9-25 | 44-47h | Topic Lens 第一屏改为 Dossier | topic-first workstation UI | search result answers branch/bottleneck/turning/future before showing raw paper list | todo |
| P9-26 | 44-47h | 图层组合解释 | Main/Co-cite/Cite/Semantic/Future/Bottleneck/Uncertainty/Fusion value explanations | selected layer combinations explain what the user is seeing and why it matters | todo |
| P9-27 | 44-47h | 交互打磨 | clickable branch, bottleneck, key paper, claim card | no important card is a dead end | todo |
| P10-28 | 47-50h | 整理审计报告 | completed items, remaining risk, next required frontfill | remaining risk is explicit and tied to product-goal impact | todo |
| P10-29 | 47-50h | 准备爬虫完成后的自动运行顺序 | post-frontfill-chain ready/restartable | section/OpenAlex threshold triggers downstream chain from a safe breakpoint | todo |
| P10-30 | 47-50h | GitHub 同步与最终状态确认 | pushed branch, passing tests, live monitors | repo is reproducible while crawlers continue | todo |

## Execution Rule

- Do not pause crawler/frontfill work for these tasks unless a hard failure is detected.
- Do not promote GNN-only future edges into Radar; they remain candidate-pool evidence until Step13 cards are complete.
- Every visible branch, bottleneck, turning paper, and claim must either link to evidence or be labeled insufficient evidence.
- Generated local queues such as `data/v14b/section_delta_queue.csv` are operational state and are not committed by default.
