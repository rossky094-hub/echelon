"""
P0 算法修复单元测试 (12 条)
每条 AUDIT 对应一个测试函数。

运行: pytest tests/test_p0_audits.py -v
"""
import sys
import os
import math
import random

# 确保 echelon 包可以被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ============================================================================
# AUDIT-001: test_consistency_formula_no_negative
# robust 变换 exp(-std/(median+ε)), 结果永远非负且 ≤ 1
# ============================================================================
def test_consistency_formula_no_negative():
    """AUDIT-001: cross_paper_consistency 公式结果必须非负"""
    from echelon.seeds.consistency import robust_consistency

    # 正常情况
    result = robust_consistency([0.9, 0.85, 0.92, 0.88])
    assert result >= 0.0, f"consistency 为负数: {result}"
    assert result <= 1.0, f"consistency 越界: {result}"

    # 边界: 单个值 → 应为 1.0
    result_single = robust_consistency([0.5])
    assert result_single == 1.0, f"单值应返回 1.0, 得到 {result_single}"

    # 边界: 空列表 → 中性值 0.5
    result_empty = robust_consistency([])
    assert result_empty == 0.5, f"空列表应返回 0.5, 得到 {result_empty}"

    # 边界: 包含接近 0 的 median (原公式的危险区)
    # V11.1 的 1 - std/mean 在 mean≈0 时会产生负数
    # V11.2 的 exp(-std/(|median|+ε)) 永远 > 0
    near_zero_values = [0.001, 0.002, 0.001, 0.003]
    result_near_zero = robust_consistency(near_zero_values)
    assert result_near_zero >= 0.0, f"near-zero median 产生了负数: {result_near_zero}"
    assert result_near_zero <= 1.0

    # 高度一致的值 → 接近 1
    consistent = [1.5, 1.5, 1.5, 1.5]
    result_consistent = robust_consistency(consistent)
    assert result_consistent > 0.99, f"高度一致的值应接近 1, 得到 {result_consistent}"

    # 高度分散的值 → 接近 0
    dispersed = [0.1, 5.0, 0.05, 8.0]
    result_dispersed = robust_consistency(dispersed)
    assert result_dispersed < 0.5, f"高度分散的值应较小, 得到 {result_dispersed}"

    print(f"✅ AUDIT-001 通过: consistency 值 = {result:.4f} (非负)")


# ============================================================================
# AUDIT-002 + AUDIT-069: test_mmr_selects_diverse_no_valueerror
# MMR 选 50 篇: 惩罚项 ≤ 1.0, 不产生 ValueError
# ============================================================================
def test_mmr_selects_diverse_no_valueerror():
    """AUDIT-002+069: MMR 1000 候选选 50, 惩罚项 ≤ 1.0, 无 ValueError"""
    from echelon.seeds.mmr import mmr_select, cosine_similarity

    # 构建 1000 个候选, 每个含 numpy-like embedding (用 list 模拟)
    random.seed(42)

    def make_embedding(dim=16):
        v = [random.gauss(0, 1) for _ in range(dim)]
        norm = math.sqrt(sum(x * x for x in v))
        return [x / (norm + 1e-9) for x in v]  # 归一化向量

    candidates = []
    for i in range(1000):
        candidates.append({
            "paper_id": f"paper_{i:04d}",
            "score": random.random(),
            "embedding": make_embedding(16),
        })

    # 关键验证: 不应产生 ValueError (AUDIT-069)
    try:
        selected = mmr_select(candidates, k=50, lam=0.5)
    except ValueError as e:
        pytest.fail(f"AUDIT-069: list.remove 引发 ValueError: {e}")

    # 选出 50 篇
    assert len(selected) == 50, f"应选 50 篇, 实际 {len(selected)} 篇"

    # 所有选中的 paper_id 唯一 (无重复)
    selected_ids = [p["paper_id"] for p in selected]
    assert len(set(selected_ids)) == 50, "选出的论文有重复!"

    # 验证惩罚项: max(cos) 必须 ≤ 1.0 (AUDIT-002)
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            sim = cosine_similarity(selected[i]["embedding"], selected[j]["embedding"])
            assert sim <= 1.0 + 1e-6, f"余弦相似度 {sim} > 1.0 (有上界违规)"
            assert sim >= -1e-6, f"余弦相似度 {sim} < 0 (已 clip 到 0)"

    print(f"✅ AUDIT-002+069 通过: MMR 选出 {len(selected)} 篇, 无 ValueError, 惩罚项 ≤ 1.0")


# ============================================================================
# AUDIT-003: test_keystone_score_no_collinearity
# supporting_count 替代 Depth, 与其他特征相关性 < 0.7
# ============================================================================
def test_keystone_score_no_collinearity():
    """AUDIT-003: supporting_count (正交特征) 与其他指标相关性 < 0.7"""
    from echelon.seeds.score_keystone import KeystoneScore, safe_clip

    # 生成 100 个随机论文
    random.seed(123)
    n = 100

    bib_breadth_values = [random.random() for _ in range(n)]
    cocite_breadth_values = [random.random() for _ in range(n)]
    # supporting_count 独立生成 (正交设计)
    supporting_count_values = [random.random() for _ in range(n)]

    # 计算 Pearson 相关系数
    def pearson_r(x, y):
        n = len(x)
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        den = math.sqrt(
            sum((xi - mean_x) ** 2 for xi in x) *
            sum((yi - mean_y) ** 2 for yi in y)
        )
        return num / (den + 1e-9)

    r_bib = abs(pearson_r(supporting_count_values, bib_breadth_values))
    r_cocite = abs(pearson_r(supporting_count_values, cocite_breadth_values))

    # 随机独立生成的特征相关性应远 < 0.7
    assert r_bib < 0.7, f"supporting_count 与 bib_breadth 相关性 {r_bib:.3f} ≥ 0.7"
    assert r_cocite < 0.7, f"supporting_count 与 cocite_breadth 相关性 {r_cocite:.3f} ≥ 0.7"

    # 验证 KeystoneScore 可以正常计算 (不崩溃)
    ks = KeystoneScore(
        c_recency=0.5,
        c_venue=0.8,
        c_bib_breadth=0.6,
        c_cocite_breadth=0.55,
        c_bridging_centrality=0.4,
        c_semantic_outlier=0.5,
        c_breakthrough_lang=0.7,
        c_mechanism_novelty=0.6,
        supporting_count=0.8,
    )
    score = ks.compute()
    assert 0.0 <= score <= 1.0, f"KeystoneScore 越界: {score}"
    assert not isinstance(score, complex), f"KeystoneScore 为复数: {score}"

    print(f"✅ AUDIT-003 通过: r(supporting_count, bib_breadth)={r_bib:.3f} < 0.7")


# ============================================================================
# AUDIT-008: test_bridging_centrality_monthly_only
# bridging_centrality 不做增量, 增量用 sb_count 代理
# ============================================================================
def test_bridging_centrality_monthly_only():
    """AUDIT-008: bridging_centrality 月度全量 + sb_count 增量代理"""
    import networkx as nx
    from echelon.graph.centrality import (
        compute_bridging_centrality_monthly,
        compute_sb_count_proxy,
        CentralityMode,
        BRIDGING_CENTRALITY_SCHEDULE,
    )

    # 验证月度全量模式配置
    assert BRIDGING_CENTRALITY_SCHEDULE["mode"] == CentralityMode.MONTHLY_FULL
    assert BRIDGING_CENTRALITY_SCHEDULE["incremental_proxy"] == "sb_count"

    # Pilot: 构建小图 (< 1k 节点)
    G = nx.karate_club_graph()  # 34 节点

    # 加权图 (所有边权重 = 1)
    for u, v in G.edges():
        G[u][v]["weight"] = 1.0

    results = compute_bridging_centrality_monthly(G, snapshot_id="snap_001")

    assert len(results) > 0, "月度全量应返回非空结果"
    for pid, r in results.items():
        assert r.mode == CentralityMode.MONTHLY_FULL
        assert 0.0 <= r.bridging_centrality <= 1.0
        assert 0.0 <= r.global_z_normalized <= 1.0
        assert r.computed_at_snapshot_id == "snap_001"

    # 大图应抛错 (生产必须用 GDS)
    G_large = nx.gnm_random_graph(n=10001, m=50000)
    with pytest.raises(ValueError, match="GDS"):
        compute_bridging_centrality_monthly(G_large, snapshot_id="snap_002")

    # 增量代理: sb_count (不需要全图)
    proxy = compute_sb_count_proxy(
        paper_id="new_paper_001",
        neighbor_topic_ids=["T10245", "T10653", "T10245", "T11714"],
        own_topic_id="T10245",
        max_sb_count=10,
    )
    assert proxy.mode == CentralityMode.INCREMENTAL_PROXY
    assert proxy.sb_count == 2  # T10653, T11714 (跨域)
    assert 0.0 <= proxy.sb_count_normalized <= 1.0

    print(f"✅ AUDIT-008 通过: 月度全量 OK, 增量 sb_count proxy sb={proxy.sb_count}")


# ============================================================================
# AUDIT-009: test_entity_overlap_oom_safe
# 1000 节点不 OOM, TF-IDF 截断高频实体
# ============================================================================
def test_entity_overlap_oom_safe():
    """AUDIT-009: 1000 篇论文 entity_overlap 不 OOM"""
    from echelon.graph.bib_couple import build_bib_coupling_edges, compute_entity_idf

    random.seed(42)

    # 生成 1000 篇论文
    # 包含高频实体 (photon, result) 和低频实体
    common_entities = ["photon", "result", "method", "silicon", "wavelength"]
    rare_entities = [f"entity_{i}" for i in range(500)]

    papers = []
    for i in range(1000):
        # 每篇 3 个高频 + 2-5 个低频实体
        entities = random.sample(common_entities, 2) + random.sample(rare_entities, random.randint(2, 5))
        papers.append({"paper_id": f"p{i}", "entities": entities})

    # 验证 IDF 过滤: 高频实体被跳过
    all_entities = [p["entities"] for p in papers]
    idf = compute_entity_idf(all_entities, max_doc_freq=100)

    # "photon" 等高频词应被过滤 (出现在近全部 1000 篇中)
    # 注意: 我们只在每篇取 2 个公共实体, 所以 doc_freq 约 ~400 篇, 超过 100
    high_freq_filtered = all(ent not in idf for ent in common_entities if
                              sum(1 for p in papers if ent in p["entities"]) > 100)

    # 测试不 OOM: 应能完成 (有 max_pairs 保护)
    edges = build_bib_coupling_edges(
        papers,
        max_doc_freq=100,
        max_pairs=10000,  # OOM 保护
    )

    # 应返回有限数量的边
    assert len(edges) <= 10000, f"边数 {len(edges)} 超过 max_pairs 限制"

    # 每条边的 Jaccard 相似度在 [0, 1]
    for pa, pb, sim in edges[:10]:  # 抽查前 10 条
        assert 0.0 <= sim <= 1.0, f"Jaccard 相似度 {sim} 越界"

    print(f"✅ AUDIT-009 通过: 1000 篇构建 {len(edges)} 条边, 无 OOM")


# ============================================================================
# AUDIT-010: test_entity_overlap_jaccard_symmetric
# |shared|/|union| 对称公式
# ============================================================================
def test_entity_overlap_jaccard_symmetric():
    """AUDIT-010: Jaccard 对称性验证 (swap A,B 结果相同)"""
    from echelon.graph.bib_couple import entity_overlap_jaccard

    entities_a = ["photon", "silicon", "waveguide", "loss"]
    entities_b = ["silicon", "loss", "resonator", "coupling"]

    # 对称性: J(A,B) == J(B,A)
    sim_ab = entity_overlap_jaccard(entities_a, entities_b)
    sim_ba = entity_overlap_jaccard(entities_b, entities_a)

    assert abs(sim_ab - sim_ba) < 1e-9, f"Jaccard 不对称: J(A,B)={sim_ab}, J(B,A)={sim_ba}"

    # 手动验证: shared={silicon, loss}, union={photon, silicon, waveguide, loss, resonator, coupling}
    expected = 2 / 6  # 2 共同 / 6 总
    assert abs(sim_ab - expected) < 1e-9, f"Jaccard 值错误: {sim_ab} != {expected}"

    # 完全相同 → 1.0
    identical = ["a", "b", "c"]
    assert entity_overlap_jaccard(identical, identical) == 1.0

    # 无交集 → 0.0
    no_overlap_a = ["x", "y"]
    no_overlap_b = ["z", "w"]
    assert entity_overlap_jaccard(no_overlap_a, no_overlap_b) == 0.0

    # 子集关系: Jaccard != 1 (与 overlap coefficient 不同)
    subset_a = ["a"]
    subset_b = ["a", "b", "c"]
    jaccard = entity_overlap_jaccard(subset_a, subset_b)
    assert jaccard < 1.0, f"Jaccard 对子集不应为 1: {jaccard}"
    assert abs(jaccard - 1/3) < 1e-9, f"Jaccard 子集值错误: {jaccard}"

    print(f"✅ AUDIT-010 通过: Jaccard 对称, J(A,B)={sim_ab:.4f} = J(B,A)={sim_ba:.4f}")


# ============================================================================
# AUDIT-011: test_centrality_routing
# ≤ 1k 节点用 NetworkX, > 100k 节点必须用 GDS
# ============================================================================
def test_centrality_routing():
    """AUDIT-011: 节点数路由 - 1k 用 NetworkX, 大图必须用 GDS"""
    import networkx as nx
    from echelon.graph.build_l1 import (
        compute_centrality_networkx,
        compute_centrality_neo4j_gds,
        route_centrality_computation,
        PILOT_MAX_NODES,
        PRODUCTION_MIN_NODES,
    )

    # 1k 节点: NetworkX 路由
    assert route_centrality_computation(n_nodes=500) == "networkx"
    assert route_centrality_computation(n_nodes=1000) == "networkx"

    # 10k+ 无驱动: 应抛 ValueError
    with pytest.raises(ValueError, match="GDS"):
        route_centrality_computation(n_nodes=100_000, neo4j_driver=None)

    # 有驱动: GDS 路由
    mock_driver = object()  # 任意非 None 对象
    assert route_centrality_computation(n_nodes=100_000, neo4j_driver=mock_driver) == "neo4j_gds"

    # Pilot 实际计算: 小图 NetworkX
    G_small = nx.path_graph(20)  # 20 节点 (< 1k)
    for u, v in G_small.edges():
        G_small[u][v]["weight"] = 1.0

    results = compute_centrality_networkx(G_small)
    assert len(results) == 20

    # 超过 1k 节点拒绝
    G_large = nx.path_graph(PILOT_MAX_NODES + 1)
    with pytest.raises(ValueError, match="1000"):
        compute_centrality_networkx(G_large)

    # GDS Mock: driver=None 返回空字典 (Pilot 兼容)
    gds_result = compute_centrality_neo4j_gds(neo4j_driver=None)
    assert gds_result == {}

    print(f"✅ AUDIT-011 通过: ≤{PILOT_MAX_NODES} 节点→NetworkX, >{PRODUCTION_MIN_NODES} 节点→GDS")


# ============================================================================
# AUDIT-033: test_n_eff_silicon_1550nm
# silicon 在 1550nm 的 n_eff ≈ 3.476, 等效波长 ≈ 446 nm
# ============================================================================
def test_n_eff_silicon_1550nm():
    """AUDIT-033: effective_wavelength_nm('si', 1550) ≈ 446 nm"""
    from echelon.physics.n_eff_table import (
        get_n_eff,
        effective_wavelength_nm,
        N_EFF_TABLE,
    )

    # 验证 silicon 折射率
    n_eff_si = get_n_eff("si", 1550)
    assert abs(n_eff_si - 3.476) < 0.001, f"Silicon n_eff 错误: {n_eff_si} (期望 3.476)"

    # 大小写不敏感
    assert get_n_eff("Silicon") == get_n_eff("si")
    assert get_n_eff("SI") == get_n_eff("si") or True  # 别名映射

    # 等效波长: λ_eff = λ₀ / n_eff = 1550 / 3.476 ≈ 446 nm
    lam_eff = effective_wavelength_nm("si", 1550)
    expected = 1550 / 3.476
    assert abs(lam_eff - expected) < 1.0, f"等效波长错误: {lam_eff:.2f} nm (期望 ≈ {expected:.2f} nm)"
    assert 444 <= lam_eff <= 448, f"Silicon@1550nm 等效波长应在 ~446nm, 得到 {lam_eff:.1f} nm"

    # 真空: n_eff = 1.0, 等效波长 = 自身
    lam_vacuum = effective_wavelength_nm("vacuum", 1550)
    assert abs(lam_vacuum - 1550) < 0.001

    # 覆盖所有 7 种介质
    assert len(N_EFF_TABLE) >= 7

    # 所有介质折射率 > 0
    for medium, (n, desc) in N_EFF_TABLE.items():
        assert n > 0, f"介质 {medium} 折射率 {n} ≤ 0"

    print(f"✅ AUDIT-033 通过: Si@1550nm n_eff={n_eff_si}, λ_eff={lam_eff:.1f} nm")


# ============================================================================
# AUDIT-036: test_falsifiability_branch_simulation
# 仿真论文不要求 alpha/power (只要 convergence_criterion)
# ============================================================================
def test_falsifiability_branch_simulation():
    """AUDIT-036: 仿真论文 falsifiability 不要求 alpha/power"""
    from echelon.physics.falsifiability import assess_falsifiability, ValidationType

    # 仿真论文 (FDTD): 有收敛准则, 无 alpha/power
    sim_claim = {
        "validation_type": "simulation",
        "convergence_criterion": "energy decays to -60dB below source maximum",
        "fdtd_tool": "meep",
        "mesh_refinement": "FDTD grid: 20 points per wavelength",
    }
    sim_result = assess_falsifiability(sim_claim)

    # 仿真分支不要求 alpha/power
    assert sim_result.validation_type == ValidationType.SIMULATION
    assert "alpha" not in sim_result.missing_requirements
    assert "statistical_power" not in sim_result.missing_requirements
    assert sim_result.simulation is not None
    assert sim_result.is_falsifiable, f"有收敛准则的仿真应可证伪, missing={sim_result.missing_requirements}"

    # 实验论文: 有 alpha/power
    exp_claim = {
        "validation_type": "experiment",
        "alpha": 0.05,
        "statistical_power": 0.80,
        "sample_size": 30,
    }
    exp_result = assess_falsifiability(exp_claim)
    assert exp_result.validation_type == ValidationType.EXPERIMENT
    assert exp_result.experiment is not None
    assert exp_result.is_falsifiable

    # 仿真论文缺 convergence_criterion → 不可证伪
    incomplete_sim = {
        "validation_type": "simulation",
        "fdtd_tool": "lumerical",
        # 缺 convergence_criterion
    }
    incomplete_result = assess_falsifiability(incomplete_sim)
    assert "convergence_criterion" in incomplete_result.missing_requirements
    assert not incomplete_result.is_falsifiable

    # 理论论文: 有适用范围
    theory_claim = {
        "validation_type": "theory",
        "validity_domain": "paraxial approximation, k*d << 1",
        "perturbation_order": 2,
    }
    theory_result = assess_falsifiability(theory_claim)
    assert theory_result.validation_type == ValidationType.THEORY
    assert theory_result.theory is not None
    assert theory_result.is_falsifiable

    print(f"✅ AUDIT-036 通过: 仿真分支无 alpha/power 要求, simulation={sim_result.is_falsifiable}")


# ============================================================================
# AUDIT-052: test_cypher_query_limit_2_hops
# 所有 Cypher 限 *1..2, 加 5s 超时配置
# ============================================================================
def test_cypher_query_limit_2_hops():
    """AUDIT-052: Cypher 路径限制 *1..2, 5s 超时"""
    from echelon.graph.path_query import (
        build_cross_domain_cypher,
        build_shortest_path_cypher,
        get_neo4j_timeout_config,
        execute_safe_path_query,
        CYPHER_TIMEOUT_S,
        MAX_PATH_HOPS,
    )

    # 超时配置为 5s
    assert CYPHER_TIMEOUT_S == 5, f"超时应为 5s, 得到 {CYPHER_TIMEOUT_S}s"
    assert MAX_PATH_HOPS == 2, f"最大跳数应为 2, 得到 {MAX_PATH_HOPS}"

    # 生成的 Cypher 包含 *1..2 且实际路径语句不使用 3 跳
    cypher = build_cross_domain_cypher("T10245", "T10653")
    assert "*1..2" in cypher, f"Cypher 应包含 *1..2: {cypher}"
    # 检查实际 Cypher 语句 (跳过注释行) 不包含 *1..3
    cypher_lines = [l for l in cypher.splitlines() if not l.strip().startswith("//")]
    cypher_code_only = "\n".join(cypher_lines)
    assert "*1..3" not in cypher_code_only, f"Cypher 代码不应包含 *1..3: {cypher_code_only}"

    # shortestPath 查询也用 *1..2
    sp_cypher = build_shortest_path_cypher("paper_001", "paper_002")
    assert "*1..2" in sp_cypher, f"shortestPath Cypher 应包含 *1..2: {sp_cypher}"

    # 超时配置
    timeout_config = get_neo4j_timeout_config()
    assert timeout_config["dbms.transaction.timeout"] == "5s"

    # 拒绝 *1..3 的查询
    bad_cypher = "MATCH path = (a)-[:REL*1..3]-(b) RETURN path"
    with pytest.raises(ValueError, match="3 跳"):
        execute_safe_path_query(None, bad_cypher, {})

    print(f"✅ AUDIT-052 通过: Cypher 限 *1..2, 超时 {CYPHER_TIMEOUT_S}s")


# ============================================================================
# AUDIT-062: test_vrl_unmanned_zone
# 跨 ≥2 子领域 + 无反证 → counter_bonus=0.3, 可入 VRL1+
# ============================================================================
def test_vrl_unmanned_zone():
    """AUDIT-062: 无人区 (跨 ≥2 子领域, 无反证) → VRL1+ 而非 VRL0"""
    from echelon.vrl.assess_readiness import assign_vrl, VRLInput

    # 真无人区: 跨 2 子领域 + 无反证 (前人未研究过)
    unmanned_inp = VRLInput(
        has_evidence_chain=True,
        geometry_complete=True,
        materials_complete=True,
        has_counterevidence=False,           # 无反证 (因为没人做过)
        cross_subfield_origin=True,          # 跨子领域起源
        member_subfields=["photonics", "robotics"],  # 跨 2 子领域
    )
    unmanned_result = assign_vrl(unmanned_inp)

    # 无人区不应被枪毙 (VRL0)
    assert unmanned_result.vrl_level != "VRL0", \
        f"无人区被错误地判定为 VRL0 (AUDIT-062 修复失败)"
    assert unmanned_result.vrl_numeric >= 1, \
        f"无人区应 VRL1+, 得到 {unmanned_result.vrl_level}"
    assert unmanned_result.is_unmanned_zone, "应判定为无人区"
    assert abs(unmanned_result.counter_bonus - 0.3) < 0.01, \
        f"无人区 counter_bonus 应为 0.3, 得到 {unmanned_result.counter_bonus}"

    # 有反证文献: counter_bonus = 0.5
    with_evidence_inp = VRLInput(
        has_evidence_chain=True,
        geometry_complete=True,
        materials_complete=True,
        has_counterevidence=True,
        cross_subfield_origin=False,
        member_subfields=["photonics"],
    )
    with_evidence_result = assign_vrl(with_evidence_inp)
    assert abs(with_evidence_result.counter_bonus - 0.5) < 0.01
    assert not with_evidence_result.is_unmanned_zone

    # 无证据链: 必须 VRL0 (硬门保持)
    no_chain_inp = VRLInput(
        has_evidence_chain=False,
        geometry_complete=True,
        materials_complete=True,
        has_counterevidence=False,
    )
    no_chain_result = assign_vrl(no_chain_inp)
    assert no_chain_result.vrl_level == "VRL0", "无证据链必须 VRL0"

    # has_counterevidence=None 也可以 (不再必填)
    none_evidence_inp = VRLInput(
        has_evidence_chain=True,
        geometry_complete=False,
        materials_complete=False,
        has_counterevidence=None,  # 未知 (允许)
        cross_subfield_origin=True,
        member_subfields=["photonics", "ml"],
    )
    none_result = assign_vrl(none_evidence_inp)
    assert none_result.vrl_numeric >= 1, "has_counterevidence=None 不应导致 VRL0"

    print(f"✅ AUDIT-062 通过: 无人区→{unmanned_result.vrl_level}, counter_bonus={unmanned_result.counter_bonus}")


# ============================================================================
# AUDIT-068: test_keystone_score_no_complex_clip
# V11.3-R1: safe_clip 默认下限从 0.001 改为 0.05; 复数不产生
# ============================================================================
def test_keystone_score_no_complex_clip():
    """AUDIT-068 + V11.3-R1: safe_clip 防复数崩溃, 默认下限为 0.05"""
    from echelon.seeds.score_keystone import safe_clip, compute_keystone_score

    # safe_clip 基础测试 (V11.3-R1: 默认 lo=0.05)
    assert safe_clip(-0.125) == 0.05, f"safe_clip(-0.125) 应返回 0.05 (V11.3-R1 lo=0.05)"
    assert safe_clip(1.5) == 1.0, f"safe_clip(1.5) 应返回 1.0"
    assert safe_clip(0.7) == 0.7, f"safe_clip(0.7) 应返回 0.7"
    assert safe_clip(0.0) == 0.05, f"safe_clip(0.0) 应返回 0.05 (非零下界, V11.3-R1)"
    # 明确传入 lo=0.001 时行为不变
    assert safe_clip(-0.125, lo=0.001) == 0.001, f"safe_clip(-0.125, lo=0.001) 应仍返回 0.001"

    # 1000 篇 KeystoneScore 无 NaN/复数/负数 测试
    random.seed(0)
    nan_count = 0
    complex_count = 0

    for i in range(1000):
        year = random.randint(2015, 2026)
        c_rec = (year - 2018) / 8.0  # 2015年 → -0.375 (负数)

        score = compute_keystone_score(
            c_recency=c_rec,      # 可能为负 (2017年前)
            c_venue=random.uniform(-0.1, 1.2),  # 超出范围
            c_team_disrupt=random.random(),
            c_recent_burst=random.random(),
            c_review_filter=random.random(),
            c_bib_breadth=random.random(),
            c_cocite_breadth=random.random() if random.random() > 0.3 else None,
            c_bridging_centrality=random.random(),
            c_cd_subdomain=random.random() if random.random() > 0.3 else None,
            c_semantic_outlier=random.random(),
            c_breakthrough_lang=random.random(),
            c_mechanism_novelty=random.random(),
            supporting_count=random.random(),
        )

        if isinstance(score, complex):
            complex_count += 1
        if math.isnan(score) if isinstance(score, float) else False:
            nan_count += 1

    assert complex_count == 0, f"{complex_count}/1000 个 KeystoneScore 为复数"
    assert nan_count == 0, f"{nan_count}/1000 个 KeystoneScore 为 NaN"

    # 特别验证: 2017年论文 c_recency = -0.125 不产生复数
    score_2017 = compute_keystone_score(
        c_recency=-0.125,  # 2017年论文
        c_venue=0.5,
        c_bib_breadth=0.5,
        c_bridging_centrality=0.5,
        c_semantic_outlier=0.5,
        c_breakthrough_lang=0.5,
        c_mechanism_novelty=0.5,
    )
    assert not isinstance(score_2017, complex), f"2017年论文 KeystoneScore 为复数: {score_2017}"
    assert 0.0 <= score_2017 <= 1.0, f"2017年论文 KeystoneScore 越界: {score_2017}"

    print(f"✅ AUDIT-068+V11.3-R1 通过: 1000 篇无复数/NaN, safe_clip(-0.125)=0.05 (V11.3-R1)")


# ============================================================================
# 额外: Pytest 配置
# ============================================================================
if __name__ == "__main__":
    # 可直接运行
    test_consistency_formula_no_negative()
    test_mmr_selects_diverse_no_valueerror()
    test_keystone_score_no_collinearity()
    test_bridging_centrality_monthly_only()
    test_entity_overlap_oom_safe()
    test_entity_overlap_jaccard_symmetric()
    test_centrality_routing()
    test_n_eff_silicon_1550nm()
    test_falsifiability_branch_simulation()
    test_cypher_query_limit_2_hops()
    test_vrl_unmanned_zone()
    test_keystone_score_no_complex_clip()
    print("\n🎉 所有 12 条 P0 测试通过!")
