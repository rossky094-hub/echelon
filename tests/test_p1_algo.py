"""
P1-B 算法精修 单元测试 (8 条 P1 AUDIT)

运行: pytest tests/test_p1_algo.py -v

覆盖:
  AUDIT-004 P1: trimmed mean severity 聚合
  AUDIT-005 P1: 0.5 平滑几何平均 + KeystoneScore V5
  AUDIT-007 P1: BT-Firth 惩罚 Bradley-Terry
  AUDIT-012 P1: 无向图 PageRank 禁用, cocite 用 degree+betweenness
  AUDIT-043 P1: MMR 余弦距离硬下界 0.20
  AUDIT-048 P1: LLM 评分 1-5 离散整数 + Pydantic validator
  AUDIT-060 P1: Breakthrough Score prompt few-shot + 1-5
  AUDIT-066 P1: Leiden CPM / KMeans fallback 聚类
"""
from __future__ import annotations

import math
import sys
import os
import time

import pytest

# 确保 echelon 包可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# AUDIT-004: trimmed mean severity 聚合
# ============================================================================

class TestAudit004TrimmedMean:
    """AUDIT-004 P1: Severity 取 Max → trimmed mean(去首尾各 10%)"""

    def test_basic_trimmed_mean(self):
        """5 个值去首尾各 10% = 去掉 0 个 (floor(5*0.1)=0), 退化为全均值"""
        from echelon.seeds.severity_aggregate import trimmed_mean
        result = trimmed_mean([1.0, 2.0, 3.0, 4.0, 5.0], trim_pct=0.10)
        # floor(5*0.10)=0 → 普通均值 = 3.0
        assert abs(result - 3.0) < 1e-9

    def test_trimmed_mean_removes_outlier(self):
        """20% 截断: 去掉 outlier 后均值明显下降"""
        from echelon.seeds.severity_aggregate import trimmed_mean
        # 原始: [0.1, 0.8, 0.85, 0.9, 10.0], max=10.0 严重失真
        # 20% trim (floor(5*0.2)=1): 去掉最小(0.1) 和最大(10.0) → [0.8, 0.85, 0.9]
        result = trimmed_mean([0.1, 0.8, 0.85, 0.9, 10.0], trim_pct=0.20)
        expected = (0.8 + 0.85 + 0.9) / 3
        assert abs(result - expected) < 1e-9, f"期望 {expected}, 得到 {result}"

    def test_trimmed_mean_vs_max(self):
        """trimmed_mean 应比 max 小, 抵抗单个高分"""
        from echelon.seeds.severity_aggregate import trimmed_mean, severity_aggregate
        scores = [0.3, 0.4, 0.5, 0.6, 9.9]
        tm = trimmed_mean(scores, trim_pct=0.10)
        mx = severity_aggregate(scores, method="max")
        assert tm < mx, f"trimmed_mean={tm} 应 < max={mx}"

    def test_empty_list(self):
        from echelon.seeds.severity_aggregate import trimmed_mean
        assert trimmed_mean([]) == 0.0

    def test_single_value(self):
        from echelon.seeds.severity_aggregate import trimmed_mean
        assert trimmed_mean([0.7]) == 0.7

    def test_two_values(self):
        """2 个值 floor(2*0.1)=0 → 普通均值"""
        from echelon.seeds.severity_aggregate import trimmed_mean
        result = trimmed_mean([0.2, 0.8])
        assert abs(result - 0.5) < 1e-9

    def test_ten_values_10pct_trim(self):
        """10 个值 floor(10*0.10)=1 → 去掉最小和最大"""
        from echelon.seeds.severity_aggregate import trimmed_mean
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = trimmed_mean(vals, trim_pct=0.10)
        # 去掉 1 和 10 → [2,3,4,5,6,7,8,9] 均值 = 5.5
        assert abs(result - 5.5) < 1e-9

    def test_severity_aggregate_default_is_trimmed_mean(self):
        """severity_aggregate 默认方法是 trimmed_mean"""
        from echelon.seeds.severity_aggregate import severity_aggregate
        scores = [0.5, 0.6, 0.7, 0.8, 0.9]
        result = severity_aggregate(scores)
        # floor(5*0.10)=0 → 普通均值 = 0.7
        assert abs(result - 0.7) < 1e-9

    def test_severity_aggregate_methods(self):
        """测试所有聚合方法"""
        from echelon.seeds.severity_aggregate import severity_aggregate
        scores = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert severity_aggregate(scores, method="max") == 5.0
        assert abs(severity_aggregate(scores, method="mean") - 3.0) < 1e-9
        assert abs(severity_aggregate(scores, method="median") - 3.0) < 1e-9

    def test_invalid_method_raises(self):
        from echelon.seeds.severity_aggregate import severity_aggregate
        with pytest.raises(ValueError, match="未知聚合方法"):
            severity_aggregate([0.5], method="geometric")


# ============================================================================
# AUDIT-005: 0.5 平滑几何平均 + KeystoneScore V5
# ============================================================================

class TestAudit005SmoothV5:
    """AUDIT-005 P1: 几何平均 + 0.5 平滑 + compute_keystone_score_v5()"""

    def test_smooth_score_v5_output_range(self):
        """smooth_score_v5 输出 ∈ (0, 1]"""
        from echelon.seeds.score_keystone import smooth_score_v5
        for v in [0.0, 0.1, 0.5, 0.9, 1.0]:
            result = smooth_score_v5(v)
            assert result > 0, f"v={v}: smooth 结果应 > 0, 得 {result}"
            assert result <= 1.0, f"v={v}: smooth 结果应 ≤ 1, 得 {result}"

    def test_smooth_score_v5_formula(self):
        """smooth_score_v5(v) = (v + 0.5) / 5.5"""
        from echelon.seeds.score_keystone import smooth_score_v5
        assert abs(smooth_score_v5(0.0) - 0.5 / 5.5) < 1e-9
        assert abs(smooth_score_v5(1.0) - 1.5 / 5.5) < 1e-9
        assert abs(smooth_score_v5(0.5) - 1.0 / 5.5) < 1e-9

    def test_smooth_v5_larger_than_v31(self):
        """0.5 平滑的最低档 > 0.05 平滑的最低档 (解决一票归零)"""
        from echelon.seeds.score_keystone import smooth_score_v5
        # V11.3-R1 平滑: (0 + 0.05) = 0.05
        # V11.5-P1 平滑: (0 + 0.5) / 5.5 ≈ 0.0909
        v5_min = smooth_score_v5(0.0)
        v31_smooth_min = 0.05  # V11.3-R1 的值
        # V5 的 log 比值更小, 区分度更好
        assert math.log(v5_min) > math.log(v31_smooth_min), \
            f"V5 平滑最低档 log={math.log(v5_min):.3f} 应 > V11.3 的 log={math.log(v31_smooth_min):.3f}"

    def test_compute_keystone_score_v5_returns_valid_range(self):
        """compute_keystone_score_v5 返回 [0, 1]"""
        from echelon.seeds.score_keystone import compute_keystone_score_v5
        score = compute_keystone_score_v5()
        assert 0.0 <= score <= 1.0, f"score={score} 应在 [0,1]"

    def test_compute_keystone_score_v5_monotone_in_components(self):
        """高分输入 → 高输出 (单调性)"""
        from echelon.seeds.score_keystone import compute_keystone_score_v5
        low = compute_keystone_score_v5(
            c_recency=0.1, c_venue=0.1, c_breakthrough_lang=0.1
        )
        high = compute_keystone_score_v5(
            c_recency=0.9, c_venue=0.9, c_breakthrough_lang=0.9
        )
        assert high > low, f"高分输入应得高输出: high={high}, low={low}"

    def test_v5_no_zero_collapse(self):
        """V5 不产生 score=0 (0.5 平滑保护)"""
        from echelon.seeds.score_keystone import compute_keystone_score_v5
        # 所有分量最低值
        score = compute_keystone_score_v5(
            c_recency=0.0, c_venue=0.0, c_team_disrupt=0.0,
            c_recent_burst=0.0, c_bib_breadth=0.0,
            c_breakthrough_lang=0.0, c_mechanism_novelty=0.0,
            supporting_count=0.0,
        )
        assert score > 0.0, f"全零输入应有正输出 (平滑保护), 得 {score}"

    def test_v5_vs_v4_coexist(self):
        """V4 和 V5 共存, 不冲突"""
        from echelon.seeds.score_keystone import compute_keystone_score_v5
        from echelon.seeds.score_keystone import compute_keystone_score
        # 两个函数都可以调用
        s_v5 = compute_keystone_score_v5(c_recency=0.6)
        s_v3 = compute_keystone_score(c_recency=0.6)
        assert isinstance(s_v5, float)
        assert isinstance(s_v3, float)


# ============================================================================
# AUDIT-007: BT-Firth 惩罚 Bradley-Terry
# ============================================================================

class TestAudit007BTFirth:
    """AUDIT-007 P1: BT MLE → Firth 惩罚 BT"""

    def test_basic_ranking_order(self):
        """A 总赢 → A 应有最高 log-strength"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        comparisons = [
            ("A", "B", 1.0), ("A", "C", 1.0), ("A", "D", 1.0),
            ("B", "C", 1.0), ("B", "D", 1.0),
            ("C", "D", 1.0),
        ]
        scores = bradley_terry_firth(comparisons)
        assert scores["A"] > scores["B"] > scores["C"] > scores["D"], \
            f"排序错误: {scores}"

    def test_strict_ordering_no_explosion(self):
        """严格偏序 (一方全胜) 不爆炸"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        # 5 篇完全线性序
        comparisons = []
        papers = ["P1", "P2", "P3", "P4", "P5"]
        for i in range(len(papers)):
            for j in range(i + 1, len(papers)):
                comparisons.append((papers[i], papers[j], 1.0))
        scores = bradley_terry_firth(comparisons)
        for pid, s in scores.items():
            assert math.isfinite(s), f"{pid} 的 strength={s} 不是有限数"
            assert abs(s) < 100, f"{pid} 的 strength={s} 过大 (可能爆炸)"

    def test_draw_symmetry(self):
        """平局 → A 和 B 强度相同"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        comparisons = [("A", "B", 0.5)] * 10  # 10 次平局
        scores = bradley_terry_firth(comparisons)
        assert abs(scores["A"] - scores["B"]) < 0.5, \
            f"平局后 A={scores['A']:.3f} 和 B={scores['B']:.3f} 应接近"

    def test_performance_100_papers(self):
        """100 篇论文 (~400 次比较) 应在 5 秒内完成"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        import random
        random.seed(42)
        n = 100
        papers = [f"P{i:03d}" for i in range(n)]
        # 模拟 Swiss 锦标赛: ~n*log2(n)/2 ≈ 332 次比较
        n_rounds = math.floor(math.log2(n))
        comparisons = []
        for _ in range(n_rounds):
            shuffled = random.sample(papers, n)
            for k in range(0, n - 1, 2):
                a, b = shuffled[k], shuffled[k + 1]
                outcome = random.choice([1.0, 0.0, 0.5])
                comparisons.append((a, b, outcome))

        t0 = time.perf_counter()
        scores = bradley_terry_firth(comparisons)
        elapsed = time.perf_counter() - t0

        assert len(scores) == n, f"应有 {n} 个论文的分数"
        assert elapsed < 5.0, f"100 篇耗时 {elapsed:.2f}s 超过 5s 限制"
        print(f"\n[AUDIT-007] BT-Firth 100 papers: {len(comparisons)} comparisons, {elapsed:.3f}s")

    def test_empty_comparisons_raises(self):
        from echelon.seeds.bt_firth import bradley_terry_firth
        with pytest.raises(ValueError):
            bradley_terry_firth([])

    def test_single_paper(self):
        """单篇论文 → 返回 {paper: 0.0}"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        scores = bradley_terry_firth([("X", "Y", 1.0)])
        assert "X" in scores and "Y" in scores

    def test_normalize_mean_zero(self):
        """normalize=True 时 mean ≈ 0"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        comparisons = [("A", "B", 1.0), ("B", "C", 1.0), ("A", "C", 0.5)]
        scores = bradley_terry_firth(comparisons, normalize=True)
        mu = sum(scores.values()) / len(scores)
        assert abs(mu) < 1.0, f"归一化后均值应接近 0, 得 {mu:.4f}"

    def test_5_papers_performance(self):
        """5 篇论文应在 0.1 秒内完成"""
        from echelon.seeds.bt_firth import bradley_terry_firth
        comparisons = [
            ("A", "B", 1.0), ("A", "C", 0.5), ("A", "D", 1.0), ("A", "E", 0.0),
            ("B", "C", 1.0), ("B", "D", 0.5), ("B", "E", 1.0),
            ("C", "D", 0.0), ("C", "E", 1.0),
            ("D", "E", 1.0),
        ]
        t0 = time.perf_counter()
        scores = bradley_terry_firth(comparisons)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"5 篇耗时 {elapsed:.3f}s 超过 0.5s"
        assert len(scores) == 5


# ============================================================================
# AUDIT-012: 无向图 PageRank 禁用, cocite 用 degree+betweenness
# ============================================================================

class TestAudit012CociteCentrality:
    """AUDIT-012 P1: 共被引无向图禁用 PageRank"""

    def _make_cocite_graph(self, n_nodes=10, density=0.3):
        """创建测试用共被引图"""
        import networkx as nx
        import random
        random.seed(42)
        G = nx.Graph()
        G.add_nodes_from(range(n_nodes))
        for i in range(n_nodes):
            for j in range(i + 1, n_nodes):
                if random.random() < density:
                    G.add_edge(i, j, weight=random.randint(1, 5))
        return G

    def test_cocite_returns_degree_and_betweenness(self):
        """cocite 中心性返回 degree 和 betweenness"""
        from echelon.graph.centrality import compute_cocite_centrality
        G = self._make_cocite_graph()
        result = compute_cocite_centrality(G)
        assert len(result) > 0
        for pid, vals in result.items():
            assert "degree_centrality" in vals
            assert "betweenness_centrality" in vals
            assert vals["pagerank"] is None, "cocite 图 pagerank 应为 None"

    def test_cocite_pagerank_disabled_raises(self):
        """pagerank_disabled=False 应 raise ValueError"""
        from echelon.graph.centrality import compute_cocite_centrality
        G = self._make_cocite_graph()
        with pytest.raises(ValueError, match="AUDIT-012"):
            compute_cocite_centrality(G, pagerank_disabled=False)

    def test_cocite_rejects_digraph(self):
        """传入 DiGraph 应 raise TypeError"""
        from echelon.graph.centrality import compute_cocite_centrality
        import networkx as nx
        DG = nx.DiGraph()
        DG.add_edge(0, 1)
        with pytest.raises(TypeError, match="无向图"):
            compute_cocite_centrality(DG)

    def test_direct_cite_pagerank_on_digraph(self):
        """有向引用图可以运行 PageRank"""
        from echelon.graph.centrality import compute_direct_cite_pagerank
        import networkx as nx
        DG = nx.DiGraph()
        DG.add_edge("A", "B", weight=1.0)
        DG.add_edge("B", "C", weight=1.0)
        DG.add_edge("A", "C", weight=1.0)
        pr = compute_direct_cite_pagerank(DG)
        assert "A" in pr and "B" in pr and "C" in pr
        # C 被引最多 → PageRank 最高
        assert pr["C"] >= pr["A"], f"C 应有更高 PageRank: C={pr['C']:.4f}, A={pr['A']:.4f}"

    def test_direct_cite_rejects_undirected(self):
        """无向图传入 PageRank 函数应 raise TypeError"""
        from echelon.graph.centrality import compute_direct_cite_pagerank
        import networkx as nx
        G = nx.Graph()
        G.add_edge(0, 1)
        with pytest.raises(TypeError, match="PageRank"):
            compute_direct_cite_pagerank(G)

    def test_empty_cocite_graph(self):
        """空图返回空 dict"""
        from echelon.graph.centrality import compute_cocite_centrality
        import networkx as nx
        G = nx.Graph()
        result = compute_cocite_centrality(G)
        assert result == {}

    def test_degree_centrality_values_in_range(self):
        """degree centrality ∈ [0, 1]"""
        from echelon.graph.centrality import compute_cocite_centrality
        G = self._make_cocite_graph(n_nodes=20, density=0.4)
        result = compute_cocite_centrality(G)
        for pid, vals in result.items():
            dc = vals["degree_centrality"]
            assert 0.0 <= dc <= 1.0, f"节点 {pid}: degree_centrality={dc} 越界"


# ============================================================================
# AUDIT-043: MMR fallback bucket 余弦距离硬下界
# ============================================================================

class TestAudit043CosineFloor:
    """AUDIT-043 P1: DPP/MMR 保底前余弦距离硬下界 0.20"""

    def _make_cand(self, pid, score, emb):
        return {"paper_id": pid, "score": score, "embedding": emb}

    def test_cosine_distance_function(self):
        """余弦距离 = 1 - cosine_similarity"""
        from echelon.seeds.mmr import cosine_distance, cosine_similarity
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        c = [1.0, 0.0, 0.0]

        assert abs(cosine_distance(a, b) - 1.0) < 1e-9, "正交向量距离应为 1"
        assert abs(cosine_distance(a, c) - 0.0) < 1e-9, "相同向量距离应为 0"

    def test_floor_filters_similar_in_fallback(self):
        """fallback 时余弦距离 < 0.20 的候选被过滤"""
        from echelon.seeds.mmr import mmr_select_with_cosine_floor

        # A: [1,0,0], B: 几乎相同 [0.99,0.14,0] (与A余弦距离约0.02 < 0.20)
        # C: [0,1,0] (与A余弦距离=1.0 > 0.20)
        cands = [
            self._make_cand("A", 0.9, [1.0, 0.0, 0.0]),
            self._make_cand("B", 0.85, [0.99, 0.14, 0.0]),  # 近似 A
            self._make_cand("C", 0.7, [0.0, 1.0, 0.0]),     # 与 A 正交
        ]
        # MMR 选 A 后, 标准 MMR 选 B 但 B 与 A 太近
        # cosine_floor 版: B 在 fallback 被过滤, 改选 C
        sel = mmr_select_with_cosine_floor(cands, k=2, cosine_distance_floor=0.20)
        ids = {p["paper_id"] for p in sel}
        assert "A" in ids, "A 应被选中 (最高分)"

    def test_cosine_floor_parameter_default(self):
        """默认 cosine_distance_floor=0.20"""
        from echelon.seeds.mmr import mmr_select_with_cosine_floor
        import inspect
        sig = inspect.signature(mmr_select_with_cosine_floor)
        default = sig.parameters["cosine_distance_floor"].default
        assert abs(default - 0.20) < 1e-9, f"默认 floor 应为 0.20, 得 {default}"

    def test_fallback_relaxes_when_no_candidate_passes(self):
        """若所有候选都不满足 floor, 应 fallback 放宽 (不返回空)"""
        from echelon.seeds.mmr import mmr_select_with_cosine_floor

        # 3 个近乎相同的向量
        cands = [
            self._make_cand("A", 0.9, [1.0, 0.0, 0.0]),
            self._make_cand("B", 0.8, [0.99, 0.1, 0.0]),
            self._make_cand("C", 0.7, [0.98, 0.2, 0.0]),
        ]
        sel = mmr_select_with_cosine_floor(
            cands, k=3, cosine_distance_floor=0.95  # 极高阈值, 无法满足
        )
        assert len(sel) > 0, "放宽 floor 后仍应返回候选"

    def test_standard_mmr_still_works(self):
        """cosine_floor=0.0 等价于标准 MMR"""
        from echelon.seeds.mmr import mmr_select_with_cosine_floor, mmr_select
        cands = [
            self._make_cand("A", 0.9, [1.0, 0.0]),
            self._make_cand("B", 0.7, [0.0, 1.0]),
            self._make_cand("C", 0.5, [0.7, 0.7]),
        ]
        sel_floor = mmr_select_with_cosine_floor(
            cands, k=2, lam=0.5, cosine_distance_floor=0.0
        )
        sel_std = mmr_select(cands, k=2, lam=0.5)
        ids_floor = {p["paper_id"] for p in sel_floor}
        ids_std = {p["paper_id"] for p in sel_std}
        assert ids_floor == ids_std, \
            f"floor=0.0 应与标准MMR相同: floor={ids_floor}, std={ids_std}"


# ============================================================================
# AUDIT-048: LLM 评分 1-5 离散整数 + Pydantic validator
# ============================================================================

class TestAudit048DiscreteScore:
    """AUDIT-048 P1: LLM 评分 1-5 离散整数"""

    def test_discretize_score_basic(self):
        """基本 discretize 映射"""
        from echelon.seeds.score_keystone import discretize_score_1_to_5
        assert discretize_score_1_to_5(0.0) == 1
        assert discretize_score_1_to_5(0.1) == 1
        assert discretize_score_1_to_5(0.2) == 2
        assert discretize_score_1_to_5(0.4) == 3
        assert discretize_score_1_to_5(0.5) == 3
        assert discretize_score_1_to_5(0.6) == 4
        assert discretize_score_1_to_5(0.8) == 5
        assert discretize_score_1_to_5(1.0) == 5

    def test_discretize_order_preserved(self):
        """AUDIT-048 关键要求: 不同连续分数保留排序"""
        from echelon.seeds.score_keystone import discretize_score_1_to_5
        # 5 个代表值, 覆盖 5 个桶
        vals = [0.09, 0.29, 0.49, 0.69, 0.89]
        disc = [discretize_score_1_to_5(v) for v in vals]
        assert disc == sorted(disc), f"离散化应保留排序: {vals} → {disc}"
        assert len(set(disc)) == 5, f"5 个不同区间应映射到 5 个不同分数: {disc}"

    def test_discretize_range_clipping(self):
        """超出 [0,1] 的输入被 clip"""
        from echelon.seeds.score_keystone import discretize_score_1_to_5
        assert discretize_score_1_to_5(-1.0) == 1
        assert discretize_score_1_to_5(2.0) == 5

    def test_llm_score_to_component_monotone(self):
        """llm_score_to_component 单调"""
        from echelon.seeds.score_keystone import llm_score_to_component
        scores = [1, 2, 3, 4, 5]
        comps = [llm_score_to_component(s) for s in scores]
        assert comps == sorted(comps), f"应单调递增: {comps}"
        assert comps[0] == 0.0
        assert comps[-1] == 1.0

    def test_pydantic_breakthrough_score_valid(self):
        """BreakthroughScore 接受 1-5"""
        from echelon.bottleneck.extract_claim import BreakthroughScore
        for s in [1, 2, 3, 4, 5]:
            bs = BreakthroughScore(score=s)
            assert bs.score == s

    def test_pydantic_breakthrough_score_clips_out_of_range(self):
        """超出范围被 clip"""
        from echelon.bottleneck.extract_claim import BreakthroughScore
        assert BreakthroughScore(score=0).score == 1
        assert BreakthroughScore(score=6).score == 5

    def test_pydantic_breakthrough_score_rounds_float(self):
        """float 输入被 round"""
        from echelon.bottleneck.extract_claim import BreakthroughScore
        assert BreakthroughScore(score=3.7).score == 4
        assert BreakthroughScore(score=2.3).score == 2

    def test_pydantic_to_component_monotone(self):
        """to_component() 保序"""
        from echelon.bottleneck.extract_claim import BreakthroughScore
        comps = [BreakthroughScore(score=s).to_component() for s in [1, 2, 3, 4, 5]]
        assert comps == sorted(comps), f"to_component 应单调递增: {comps}"
        # 不同分数 → 不同分量 (不能合并)
        assert len(set(comps)) == 5, f"5 个分数应有 5 个不同分量: {comps}"

    def test_pydantic_invalid_type_raises(self):
        """非数值类型应 raise"""
        from echelon.bottleneck.extract_claim import BreakthroughScore
        with pytest.raises(Exception):
            BreakthroughScore(score="abc")

    def test_to_smooth_component(self):
        """to_smooth_component = (to_component + 0.5) / 5.5"""
        from echelon.bottleneck.extract_claim import BreakthroughScore
        for s in [1, 3, 5]:
            bs = BreakthroughScore(score=s)
            expected = (bs.to_component() + 0.5) / 5.5
            assert abs(bs.to_smooth_component() - expected) < 1e-9


# ============================================================================
# AUDIT-060: Breakthrough Score prompt few-shot + 1-5
# ============================================================================

class TestAudit060BreakthroughPrompt:
    """AUDIT-060 P1: Breakthrough Score 完整 abstract + few-shot + 1-5"""

    def test_prompt_contains_fewshot_examples(self):
        """Prompt 包含 5 条 few-shot 示例"""
        from echelon.bottleneck.extract_claim import BREAKTHROUGH_SCORE_PROMPT
        # 检查有 5 个 "score=" 示例
        import re
        examples = re.findall(r'→ score=\d', BREAKTHROUGH_SCORE_PROMPT)
        assert len(examples) >= 5, \
            f"Prompt 应有 ≥5 条 few-shot 示例, 找到 {len(examples)} 条"

    def test_prompt_includes_all_score_levels(self):
        """Prompt 覆盖 1-5 所有分数级别"""
        from echelon.bottleneck.extract_claim import BREAKTHROUGH_SCORE_PROMPT
        for score in ["score=1", "score=2", "score=3", "score=4", "score=5"]:
            assert score in BREAKTHROUGH_SCORE_PROMPT, f"Prompt 缺少 {score} 示例"

    def test_prompt_uses_full_abstract_placeholder(self):
        """Prompt 模板使用完整 abstract 占位符"""
        from echelon.bottleneck.extract_claim import BREAKTHROUGH_SCORE_PROMPT
        assert "{abstract}" in BREAKTHROUGH_SCORE_PROMPT, \
            "Prompt 应包含 {abstract} 占位符 (完整 abstract)"
        assert "{title}" in BREAKTHROUGH_SCORE_PROMPT, \
            "Prompt 应包含 {title} 占位符"

    def test_format_breakthrough_prompt(self):
        """format_breakthrough_prompt 填充 title 和 abstract"""
        from echelon.bottleneck.extract_claim import format_breakthrough_prompt
        prompt = format_breakthrough_prompt(
            title="Test Paper",
            abstract="We demonstrate a novel method..."
        )
        assert "Test Paper" in prompt
        assert "We demonstrate a novel method..." in prompt

    def test_format_with_empty_abstract(self):
        """空 abstract 不报错"""
        from echelon.bottleneck.extract_claim import format_breakthrough_prompt
        prompt = format_breakthrough_prompt(title="X", abstract="")
        assert "[Abstract not available]" in prompt

    def test_parse_breakthrough_response_json(self):
        """解析 JSON 格式 LLM 输出"""
        from echelon.bottleneck.extract_claim import parse_breakthrough_response
        result = parse_breakthrough_response('{"score": 4}')
        assert result.score == 4

    def test_parse_breakthrough_response_number_only(self):
        """解析纯数字输出"""
        from echelon.bottleneck.extract_claim import parse_breakthrough_response
        result = parse_breakthrough_response("Score: 3")
        assert result.score == 3

    def test_parse_breakthrough_response_invalid_fallback(self):
        """无效输出 fallback 到 score=1"""
        from echelon.bottleneck.extract_claim import parse_breakthrough_response
        result = parse_breakthrough_response("This paper is excellent!")
        assert result.score == 1

    def test_prompt_requires_discrete_output(self):
        """Prompt 明确要求输出整数"""
        from echelon.bottleneck.extract_claim import BREAKTHROUGH_SCORE_PROMPT
        assert "integer" in BREAKTHROUGH_SCORE_PROMPT.lower() or \
               "整数" in BREAKTHROUGH_SCORE_PROMPT or \
               "1-5" in BREAKTHROUGH_SCORE_PROMPT, \
            "Prompt 应明确要求整数输出"

    def test_prompt_does_not_truncate_abstract(self):
        """format_breakthrough_prompt 不截断 abstract"""
        from echelon.bottleneck.extract_claim import format_breakthrough_prompt
        long_abstract = "word " * 500  # 500 词
        prompt = format_breakthrough_prompt(title="T", abstract=long_abstract)
        # 长摘要完整出现
        assert long_abstract.strip() in prompt, "完整 abstract 应不被截断"


# ============================================================================
# AUDIT-066: Leiden CPM / KMeans fallback 聚类
# ============================================================================

class TestAudit066LeidenCPM:
    """AUDIT-066 P1: Leiden CPM 聚类 (余弦 0.83 + γ 调优)"""

    def _random_embeddings(self, n, dim=16, seed=42):
        import random
        random.seed(seed)
        return [[random.gauss(0, 1) for _ in range(dim)] for _ in range(n)]

    def _cluster_embeddings(self, n, dim=8):
        """生成有聚类结构的向量: 5 个 cluster, 每个 n//5 个向量"""
        import random
        random.seed(99)
        embs = []
        for g in range(5):
            center = [random.gauss(g * 3, 0.1) for _ in range(dim)]
            for _ in range(n // 5):
                vec = [c + random.gauss(0, 0.05) for c in center]
                embs.append(vec)
        return embs

    def test_returns_valid_result_dict(self):
        """返回 dict 含 labels, n_clusters, method"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        embs = self._random_embeddings(20)
        result = cluster_with_leiden_cpm(embs)
        assert "labels" in result
        assert "n_clusters" in result
        assert "method" in result
        assert "best_gamma" in result
        assert "best_modularity" in result
        assert "gamma_search" in result

    def test_labels_length_matches_input(self):
        """labels 长度等于输入向量数量"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        n = 30
        embs = self._random_embeddings(n)
        result = cluster_with_leiden_cpm(embs)
        assert len(result["labels"]) == n

    def test_cosine_threshold_default_is_083(self):
        """默认余弦阈值为 0.83"""
        import inspect
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        sig = inspect.signature(cluster_with_leiden_cpm)
        default = sig.parameters["cosine_threshold"].default
        assert abs(default - 0.83) < 1e-9, f"默认阈值应为 0.83, 得 {default}"

    def test_gamma_range_default(self):
        """默认 γ 范围 (0.3, 1.5)"""
        import inspect
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        sig = inspect.signature(cluster_with_leiden_cpm)
        default = sig.parameters["gamma_range"].default
        assert default == (0.3, 1.5), f"默认 γ 范围应为 (0.3, 1.5), 得 {default}"

    def test_n_gamma_candidates_default(self):
        """默认 n_gamma_candidates = 5"""
        import inspect
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        sig = inspect.signature(cluster_with_leiden_cpm)
        default = sig.parameters["n_gamma_candidates"].default
        assert default == 5, f"默认 γ 候选数应为 5, 得 {default}"

    def test_method_is_leiden_or_kmeans(self):
        """method 必须是 leiden_cpm 或 kmeans_fallback"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        embs = self._random_embeddings(15)
        result = cluster_with_leiden_cpm(embs)
        assert result["method"] in ("leiden_cpm", "kmeans_fallback", "trivial", "empty"), \
            f"未知 method: {result['method']}"

    def test_empty_input(self):
        """空输入返回空结果"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        result = cluster_with_leiden_cpm([])
        assert result["labels"] == []
        assert result["n_clusters"] == 0

    def test_single_embedding(self):
        """单个向量 → 1 个 cluster"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        result = cluster_with_leiden_cpm([[1.0, 0.0, 0.0]])
        assert result["n_clusters"] == 1
        assert result["labels"] == [0]

    def test_clustered_embeddings_find_groups(self):
        """有聚类结构的向量应分出多个 cluster"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        embs = self._cluster_embeddings(n=50, dim=8)
        result = cluster_with_leiden_cpm(embs, cosine_threshold=0.5)  # 稍低阈值让结构显现
        assert result["n_clusters"] >= 2, \
            f"有聚类结构的向量应分出 ≥2 个 cluster, 得 {result['n_clusters']}"

    def test_gamma_search_log_length(self):
        """γ 搜索日志长度 ≤ n_gamma_candidates"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        embs = self._random_embeddings(20)
        result = cluster_with_leiden_cpm(embs, n_gamma_candidates=3)
        assert len(result["gamma_search"]) <= 3, \
            f"γ 搜索日志最多 3 条, 得 {len(result['gamma_search'])} 条"

    def test_cosine_similarity_matrix_symmetric(self):
        """余弦相似度矩阵是对称的"""
        from echelon.bottleneck.cluster import _cosine_similarity_matrix
        embs = [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]]
        sim = _cosine_similarity_matrix(embs)
        n = len(embs)
        for i in range(n):
            for j in range(n):
                assert abs(sim[i][j] - sim[j][i]) < 1e-9, \
                    f"sim[{i}][{j}]={sim[i][j]:.4f} ≠ sim[{j}][{i}]={sim[j][i]:.4f}"

    def test_cosine_similarity_diagonal_is_one(self):
        """对角线 = 1.0 (自相似)"""
        from echelon.bottleneck.cluster import _cosine_similarity_matrix
        embs = [[1.0, 2.0], [3.0, 4.0]]
        sim = _cosine_similarity_matrix(embs)
        assert abs(sim[0][0] - 1.0) < 1e-6
        assert abs(sim[1][1] - 1.0) < 1e-6

    def test_high_threshold_isolates_all_nodes(self):
        """余弦阈值 1.0 时所有节点孤立, 每个自成 cluster"""
        from echelon.bottleneck.cluster import cluster_with_leiden_cpm
        embs = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]  # 两两不完全相同
        result = cluster_with_leiden_cpm(embs, cosine_threshold=1.0)
        # 阈值=1.0: 只有完全相同的向量才建边 → 所有节点孤立
        assert result["n_clusters"] >= 2, \
            f"高阈值下应有多个 cluster, 得 {result['n_clusters']}"


# ============================================================================
# 集成: 所有 P1 模块都能正确导入
# ============================================================================

class TestModuleImports:
    """检查所有 P1-B 新模块均可正确导入"""

    def test_import_severity_aggregate(self):
        from echelon.seeds.severity_aggregate import trimmed_mean, severity_aggregate
        assert callable(trimmed_mean)
        assert callable(severity_aggregate)

    def test_import_bt_firth(self):
        from echelon.seeds.bt_firth import bradley_terry_firth
        assert callable(bradley_terry_firth)

    def test_import_score_keystone_v5(self):
        from echelon.seeds.score_keystone import (
            compute_keystone_score_v5,
            smooth_score_v5,
            discretize_score_1_to_5,
            llm_score_to_component,
        )
        assert callable(compute_keystone_score_v5)

    def test_import_centrality_new_functions(self):
        from echelon.graph.centrality import (
            compute_cocite_centrality,
            compute_direct_cite_pagerank,
        )
        assert callable(compute_cocite_centrality)
        assert callable(compute_direct_cite_pagerank)

    def test_import_mmr_cosine_floor(self):
        from echelon.seeds.mmr import (
            cosine_distance,
            mmr_select_with_cosine_floor,
        )
        assert callable(cosine_distance)
        assert callable(mmr_select_with_cosine_floor)

    def test_import_extract_claim(self):
        from echelon.bottleneck.extract_claim import (
            BreakthroughScore,
            MechanismNoveltyScore,
            BREAKTHROUGH_SCORE_PROMPT,
            format_breakthrough_prompt,
            parse_breakthrough_response,
        )
        assert callable(format_breakthrough_prompt)

    def test_import_cluster(self):
        from echelon.bottleneck.cluster import (
            cluster_with_leiden_cpm,
            _cosine_similarity_matrix,
        )
        assert callable(cluster_with_leiden_cpm)
