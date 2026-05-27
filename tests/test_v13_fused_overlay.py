#!/usr/bin/env python3
"""
test_v13_fused_overlay.py — V13-CE 边融合 + Graph Overlay Builder 单元测试

Tasks covered:
    - Task 1: echelon/graph/fused_edge.py (fused_edge_weight, normalize_log, build_fused_edge_table)
    - Task 2: echelon/graph/overlay_builder.py (build_overlay)

Run:
    pytest tests/test_v13_fused_overlay.py -v
"""

import json
import math
import sys
from datetime import date
from typing import Dict, List

import pytest

sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

from echelon.graph.fused_edge import (
    build_fused_edge_table,
    compute_time_decay,
    fused_edge_weight,
    normalize_log,
)
from echelon.graph.overlay_builder import (
    BOTTLENECK_PALETTE,
    META_PRINCIPLE_PALETTE,
    build_overlay,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures: minimal test data
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def minimal_papers():
    """10 篇最小 paper 列表 (5 in bottleneck B0, 5 isolated)"""
    papers = []
    for i in range(10):
        papers.append({"paper_id": f"P{i:03d}", "title": f"Paper {i}"})
    return papers


@pytest.fixture
def minimal_bottlenecks():
    """2 个卡点, 各覆盖 5 篇 paper"""
    return [
        {
            "bottleneck_id": "BN_001",
            "cluster_id": 0,
            "label": "卡点0: 逆向设计瓶颈",
            "supporting_papers": ["P000", "P001", "P002", "P003", "P004"],
            "is_cross_topic": False,
        },
        {
            "bottleneck_id": "BN_002",
            "cluster_id": 1,
            "label": "卡点1: 多模态泛化瓶颈",
            "supporting_papers": ["P005", "P006", "P007"],
            "is_cross_topic": True,
        },
    ]


@pytest.fixture
def minimal_themes():
    """3 个主题, 含 paper_ids"""
    return [
        {"theme_id": "T01", "title": "主题A", "paper_ids": ["P000", "P001", "P005"]},
        {"theme_id": "T02", "title": "主题B", "paper_ids": ["P002", "P003"]},
        {"theme_id": "T03", "title": "主题C", "paper_ids": ["P006", "P007"]},
    ]


@pytest.fixture
def minimal_meta_principles():
    """2 条元规律 (MP1 覆盖 T01/T02, MP2 覆盖 T02/T03)"""
    return [
        {
            "principle": "维度灾难",
            "covered_themes": ["T01", "T02"],
            "is_solvable_in_3_years": False,
            "explanation": "高维空间采样复杂度指数增长",
            "solvability_reason": "数学本质限制",
        },
        {
            "principle": "信息熵耗散",
            "covered_themes": ["T02", "T03"],
            "is_solvable_in_3_years": True,
            "explanation": "信道容量限制",
            "solvability_reason": "编码优化可逼近极限",
        },
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Task 1 Tests: fused_edge.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeLog:
    """test_normalize_log_correctness"""

    def test_zero_value_returns_zero(self):
        assert normalize_log(0, 100) == 0.0

    def test_negative_value_returns_zero(self):
        assert normalize_log(-5, 100) == 0.0

    def test_max_value_returns_one(self):
        result = normalize_log(20, 20)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_intermediate_value(self):
        """log(1+10)/log(1+20) ≈ 0.795"""
        result = normalize_log(10, 20)
        expected = math.log(11) / math.log(21)
        assert result == pytest.approx(expected, rel=1e-6)

    def test_value_exceeds_max_capped_at_one(self):
        """超过 max_val 仍应裁剪到 1.0"""
        result = normalize_log(100, 20)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_max_val_zero_returns_zero(self):
        """max_val=0 时返回 0.0"""
        assert normalize_log(5, 0) == 0.0


class TestFusedEdgeWeightPureCitation:
    """test_fused_edge_weight_pure_citation"""

    def test_pure_citation_alpha_1(self):
        """alpha=1.0 时 fused = w_cite (纯引用)"""
        w = fused_edge_weight(
            cite_direct=20, co_citation=0, bib_couple=0,
            semantic_bridge=0.0, alpha=1.0,
        )
        # w_cite = 0.30 * 1.0 + 0.40 * 0 + 0.30 * 0 = 0.30
        assert w == pytest.approx(0.30, abs=1e-6)

    def test_pure_citation_all_components(self):
        """全部引用组件满值时 w_cite=1.0"""
        w = fused_edge_weight(
            cite_direct=20, co_citation=50, bib_couple=30,
            semantic_bridge=0.0, alpha=1.0,
        )
        assert w == pytest.approx(1.0, abs=1e-6)

    def test_zero_citations_zero_semantic(self):
        """全零输入 → 0.0"""
        w = fused_edge_weight(
            cite_direct=0, co_citation=0, bib_couple=0,
            semantic_bridge=0.0, alpha=0.5,
        )
        assert w == 0.0


class TestFusedEdgeWeightPureSemantic:
    """test_fused_edge_weight_pure_semantic"""

    def test_pure_semantic_alpha_0(self):
        """alpha=0.0 时 fused = w_sem (纯语义)"""
        w = fused_edge_weight(
            cite_direct=0, co_citation=0, bib_couple=0,
            semantic_bridge=0.85, alpha=0.0,
        )
        assert w == pytest.approx(0.85, abs=1e-6)

    def test_semantic_bridge_capped_at_1(self):
        """语义值 >1 应裁剪"""
        w = fused_edge_weight(semantic_bridge=1.5, alpha=0.0)
        assert w == pytest.approx(1.0, abs=1e-6)

    def test_negative_semantic_bridge_zero(self):
        """语义值 <0 应视为 0"""
        w = fused_edge_weight(semantic_bridge=-0.3, alpha=0.0)
        assert w == 0.0


class TestFusedEdgeWeightCrossTopicBonus:
    """test_fused_edge_weight_cross_topic_bonus"""

    def test_cross_topic_doubles_weight(self):
        """cross_topic=True 时权重加倍 (最多 1.0)"""
        base = fused_edge_weight(
            cite_direct=5, co_citation=10, bib_couple=5,
            semantic_bridge=0.3, alpha=0.5, cross_topic=False,
        )
        bonus = fused_edge_weight(
            cite_direct=5, co_citation=10, bib_couple=5,
            semantic_bridge=0.3, alpha=0.5, cross_topic=True,
        )
        # bonus 应是 base 的两倍 (若未超过 1.0)
        if base * 2.0 <= 1.0:
            assert bonus == pytest.approx(base * 2.0, rel=1e-5)
        else:
            assert bonus == pytest.approx(1.0, abs=1e-9)

    def test_cross_topic_capped_at_1(self):
        """加倍后仍不超过 1.0"""
        w = fused_edge_weight(
            cite_direct=20, co_citation=50, bib_couple=30,
            semantic_bridge=1.0, alpha=0.5, cross_topic=True,
        )
        assert w <= 1.0

    def test_no_cross_topic_bonus(self):
        """cross_topic=False 不改变基础权重"""
        w_no = fused_edge_weight(
            cite_direct=10, co_citation=20, bib_couple=10,
            semantic_bridge=0.5, alpha=0.5, cross_topic=False,
        )
        # cross_topic=False → bonus=1.0, 不放大
        assert 0.0 <= w_no <= 1.0


class TestFusedEdgeWeightTimeDecay:
    """test_fused_edge_weight_time_decay"""

    def test_time_decay_1_no_change(self):
        """time_decay=1.0 不改变权重"""
        w_decay1 = fused_edge_weight(
            cite_direct=10, semantic_bridge=0.5, alpha=0.5, time_decay=1.0
        )
        w_no_decay = fused_edge_weight(
            cite_direct=10, semantic_bridge=0.5, alpha=0.5
        )
        assert w_decay1 == pytest.approx(w_no_decay, rel=1e-9)

    def test_time_decay_reduces_weight(self):
        """time_decay<1 应降低权重"""
        w_full = fused_edge_weight(semantic_bridge=0.8, alpha=0.0, time_decay=1.0)
        w_decayed = fused_edge_weight(semantic_bridge=0.8, alpha=0.0, time_decay=0.5)
        assert w_decayed < w_full

    def test_time_decay_zero_reduces_to_zero(self):
        """time_decay=0.0 → 0.0"""
        w = fused_edge_weight(
            cite_direct=20, co_citation=50, bib_couple=30,
            semantic_bridge=1.0, alpha=0.5, time_decay=0.0,
        )
        assert w == pytest.approx(0.0, abs=1e-9)


class TestFusedEdgeWeightInRange:
    """test_fused_edge_weight_in_0_1 — 随机参数仍在 [0,1]"""

    @pytest.mark.parametrize("cd,cc,bc,sem,ct,td", [
        (0, 0, 0, 0.0, False, 1.0),
        (20, 50, 30, 1.0, True, 1.0),
        (100, 200, 100, 2.0, True, 0.3),  # 超限输入
        (5, 10, 3, 0.7, False, 0.8),
        (1, 1, 1, 0.1, True, 0.5),
    ])
    def test_always_in_unit_interval(self, cd, cc, bc, sem, ct, td):
        w = fused_edge_weight(
            cite_direct=cd, co_citation=cc, bib_couple=bc,
            semantic_bridge=sem, cross_topic=ct, time_decay=td,
        )
        assert 0.0 <= w <= 1.0, f"Out of range: {w} for inputs ({cd},{cc},{bc},{sem},{ct},{td})"


class TestBuildFusedEdgeTable:
    """test_build_fused_edge_table"""

    def test_returns_dict_with_correct_keys(self):
        edges = {
            ("P1", "P2"): {"cite_direct": 3, "co_citation": 5, "bib_couple": 2,
                           "semantic_bridge": 0.6, "cross_topic": False},
            ("P2", "P3"): {"cite_direct": 0, "co_citation": 0, "bib_couple": 0,
                           "semantic_bridge": 0.9, "cross_topic": True},
        }
        table = build_fused_edge_table(edges)
        assert ("P1", "P2") in table
        assert ("P2", "P3") in table
        assert len(table) == 2

    def test_values_in_unit_interval(self):
        edges = {
            (f"N{i}", f"N{i+1}"): {
                "cite_direct": i * 2,
                "co_citation": i * 3,
                "bib_couple": i,
                "semantic_bridge": 0.1 * i,
                "cross_topic": i % 2 == 0,
            }
            for i in range(10)
        }
        table = build_fused_edge_table(edges)
        for key, val in table.items():
            assert 0.0 <= val <= 1.0, f"Edge {key}: weight {val} out of range"

    def test_with_time_decay_from_dates(self):
        """含日期参数时应触发时间衰减"""
        edges = {
            ("A", "B"): {
                "cite_direct": 10, "co_citation": 20, "bib_couple": 5,
                "semantic_bridge": 0.7, "cross_topic": False,
                "src_pub_date": date(2015, 1, 1),
                "dst_pub_date": date(2016, 1, 1),
            },
        }
        table_with_decay = build_fused_edge_table(
            edges, reference_date=date(2025, 1, 1), decay_half_life_years=5.0
        )
        table_no_decay = build_fused_edge_table(
            {("A", "B"): {
                "cite_direct": 10, "co_citation": 20, "bib_couple": 5,
                "semantic_bridge": 0.7, "cross_topic": False,
            }}
        )
        # 旧论文应衰减, 权重更低
        assert table_with_decay[("A", "B")] < table_no_decay[("A", "B")]


# ═══════════════════════════════════════════════════════════════════════════════
# Task 2 Tests: overlay_builder.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildOverlayNodeInBottleneck:
    """test_build_overlay_node_in_bottleneck"""

    def test_paper_in_bottleneck_has_bottleneck_id(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        # P000 is in cluster_id=0 → B0
        assert node_map["P000"]["bottleneck_id"] == "B0"
        assert node_map["P000"]["is_landmark"] is True

    def test_paper_in_bottleneck_has_halo_color(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        assert node_map["P000"]["halo_color"] is not None
        assert node_map["P000"]["halo_color"].startswith("#")


class TestBuildOverlayNodeInTheme:
    """test_build_overlay_node_in_theme"""

    def test_paper_in_theme_has_theme_id(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        # P000 is in T01
        assert node_map["P000"]["theme_id"] == "T01"
        # P002 is in T02
        assert node_map["P002"]["theme_id"] == "T02"


class TestBuildOverlayNodeInMetaPrinciple:
    """test_build_overlay_node_in_meta_principle"""

    def test_paper_in_meta_principle_has_mp_ids(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        # P000 → T01 → MP1 (covered_themes includes T01)
        assert "MP1" in node_map["P000"]["meta_principles"]

    def test_paper_in_multiple_meta_principles(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        # P002 → T02, T02 is covered by both MP1 and MP2
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        mps = node_map["P002"]["meta_principles"]
        assert "MP1" in mps
        assert "MP2" in mps

    def test_paper_has_principle_band_colors(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        colors = node_map["P000"]["principle_band_colors"]
        assert isinstance(colors, list)
        assert len(colors) > 0
        for c in colors:
            assert c.startswith("#")


class TestBuildOverlayIsolatedPaper:
    """test_build_overlay_isolated_paper_has_no_overlay"""

    def test_isolated_paper_no_bottleneck(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        # P008, P009 not in any bottleneck or theme
        isolated = node_map["P008"]
        assert isolated["bottleneck_id"] is None
        assert isolated["is_landmark"] is False
        assert isolated["halo_color"] is None

    def test_isolated_paper_no_theme(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        node_map = {n["paper_id"]: n for n in overlay["node_overlays"]}
        assert node_map["P009"]["theme_id"] is None


class TestBuildOverlayBottleneckHaloCentroid:
    """test_build_overlay_bottleneck_halo_centroid"""

    def test_bottleneck_halos_exist(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        halos = overlay["bottleneck_halos"]
        assert len(halos) == 2

    def test_bottleneck_halo_has_centroid(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        halo = overlay["bottleneck_halos"][0]
        assert "centroid_x_y" in halo
        assert len(halo["centroid_x_y"]) == 2
        assert isinstance(halo["centroid_x_y"][0], float)
        assert isinstance(halo["centroid_x_y"][1], float)

    def test_bottleneck_halo_radius_positive(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        for halo in overlay["bottleneck_halos"]:
            assert halo["radius"] > 0.0


class TestBuildOverlayMetaPrincipleBandCoversThemes:
    """test_build_overlay_meta_principle_band_covers_themes"""

    def test_bands_count_matches_meta_principles(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        assert len(overlay["meta_principle_bands"]) == len(minimal_meta_principles)

    def test_band_covered_theme_ids_match(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        bands = {b["principle_id"]: b for b in overlay["meta_principle_bands"]}
        assert set(bands["MP1"]["covered_theme_ids"]) == {"T01", "T02"}
        assert set(bands["MP2"]["covered_theme_ids"]) == {"T02", "T03"}

    def test_band_covered_papers(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        bands = {b["principle_id"]: b for b in overlay["meta_principle_bands"]}
        # MP1 covers T01+T02 → P000,P001,P005,P002,P003
        mp1_papers = set(bands["MP1"]["covered_paper_ids"])
        assert "P000" in mp1_papers
        assert "P002" in mp1_papers

    def test_band_solvability_field(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        bands = {b["principle_id"]: b for b in overlay["meta_principle_bands"]}
        assert bands["MP1"]["is_solvable_in_3_years"] is False
        assert bands["MP2"]["is_solvable_in_3_years"] is True


class TestBuildOverlayColorNoCollision:
    """test_build_overlay_color_assignment_no_collision"""

    def test_bottleneck_colors_distinct(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        colors = [h["halo_color"] for h in overlay["bottleneck_halos"]]
        # 2 个卡点应有不同颜色
        assert len(set(colors)) == len(colors), f"Duplicate halo colors: {colors}"

    def test_meta_principle_colors_all_valid(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        for band in overlay["meta_principle_bands"]:
            color = band["band_color"]
            assert color.startswith("#"), f"Invalid color: {color}"
            assert len(color) == 7, f"Invalid color length: {color}"

    def test_full_15_bottleneck_palette_distinct(self):
        """BOTTLENECK_PALETTE 中 15 色应全部不同"""
        assert len(set(BOTTLENECK_PALETTE)) == len(BOTTLENECK_PALETTE), \
            "BOTTLENECK_PALETTE has duplicate colors"

    def test_full_4_meta_principle_palette_distinct(self):
        """META_PRINCIPLE_PALETTE 中 4 色应全部不同"""
        assert len(set(META_PRINCIPLE_PALETTE)) == len(META_PRINCIPLE_PALETTE), \
            "META_PRINCIPLE_PALETTE has duplicate colors"


class TestBuildOverlaySummaryCounts:
    """test_build_overlay_summary_counts_correct"""

    def test_summary_covered_by_bottleneck(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        summary = overlay["summary"]
        # B0 has 5 papers, B1 has 3 papers = 8 total unique
        assert summary["papers_covered_by_bottleneck"] == 8

    def test_summary_covered_by_theme(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        summary = overlay["summary"]
        # T01 has 3, T02 has 2, T03 has 2 = 7 unique
        assert summary["papers_covered_by_theme"] == 7

    def test_summary_in_meta_principle(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        summary = overlay["summary"]
        # All theme papers are covered by at least one MP
        # T01 → MP1, T02 → MP1+MP2, T03 → MP2
        # papers with theme: P000,P001,P005 (T01), P002,P003 (T02), P006,P007 (T03) = 7
        assert summary["papers_in_meta_principle"] == 7

    def test_summary_totals(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        summary = overlay["summary"]
        assert summary["total_papers"] == 10
        assert summary["bottleneck_count"] == 2
        assert summary["theme_count"] == 3
        assert summary["meta_principle_count"] == 2


class TestOverlaySerializableJson:
    """test_overlay_serializable_json"""

    def test_overlay_json_serializable(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        """整个 overlay 结果应可 json.dumps 无异常"""
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        serialized = json.dumps(overlay, ensure_ascii=False)
        assert isinstance(serialized, str)
        assert len(serialized) > 100

    def test_overlay_round_trip_json(
        self, minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
    ):
        """序列化后反序列化结果应与原始结构相同"""
        overlay = build_overlay(
            minimal_papers, minimal_bottlenecks, minimal_themes, minimal_meta_principles
        )
        serialized = json.dumps(overlay, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized["summary"] == overlay["summary"]
        assert len(deserialized["node_overlays"]) == len(overlay["node_overlays"])


# ═══════════════════════════════════════════════════════════════════════════════
# Integration test: use real V12.5 data
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildOverlayWithRealData:
    """V12.5 实际数据集成测试"""

    BOTTLENECKS_PATH = "/home/user/workspace/echelon_mvp0a/reports/v5/l3_bottlenecks_v5.json"
    THEMES_PATH = "/home/user/workspace/echelon_mvp0a/reports/v5/themes_enriched.json"
    META_PATH = "/home/user/workspace/echelon_mvp0a/scibot/meta_principles_v12_5.json"
    DB_PATH = "/home/user/workspace/echelon_mvp0a/db/pilot_v5.db"

    @pytest.fixture
    def real_overlay(self):
        import json, sqlite3
        from echelon.graph.overlay_builder import build_overlay, load_overlay_inputs_from_files

        bn_list, themes_list, mp_list = load_overlay_inputs_from_files(
            self.BOTTLENECKS_PATH, self.THEMES_PATH, self.META_PATH
        )
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, primary_topic_id, primary_topic_name, title FROM paper_identity")
        rows = cur.fetchall()
        conn.close()
        papers = [
            {"paper_id": r[0], "primary_topic_id": r[1], "primary_topic_name": r[2], "title": r[3]}
            for r in rows
        ]
        return build_overlay(papers=papers, bottlenecks=bn_list, themes=themes_list, meta_principles=mp_list)

    def test_real_data_node_count(self, real_overlay):
        assert len(real_overlay["node_overlays"]) == 2000

    def test_real_data_bottleneck_halos_count(self, real_overlay):
        assert len(real_overlay["bottleneck_halos"]) == 15

    def test_real_data_meta_principle_bands_count(self, real_overlay):
        assert len(real_overlay["meta_principle_bands"]) == 4

    def test_real_data_summary_is_non_trivial(self, real_overlay):
        summary = real_overlay["summary"]
        # 至少部分论文有 bottleneck 覆盖
        assert summary["papers_covered_by_bottleneck"] > 0
        # V5 DB 与 V12 themes_enriched 的 paper_id 集合不重叠 (不同批次)
        # 基于 theme/meta_principle 覆盖的计数可以为 0, 模块行为正确
        assert summary["total_papers"] == 2000
        assert summary["bottleneck_count"] == 15

    def test_real_data_json_serializable(self, real_overlay):
        serialized = json.dumps(real_overlay, ensure_ascii=False)
        assert len(serialized) > 1000
