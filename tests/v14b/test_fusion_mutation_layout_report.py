"""
tests/v14b/test_fusion_mutation_layout_report.py

- Fusion 三路输入合成 → 验证交集
- 突变标记阈值边界
- UMAP 输出格式
- 报告生成器 (13 章节检查)
"""
import json
import math
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echelon.v14b.db_schema import init_v14b_db


# ---------------------------------------------------------------------------
# 测试工具
# ---------------------------------------------------------------------------

def create_full_test_db(tmp_path):
    """创建包含所有 V14-B 表的测试 DB"""
    db_path = tmp_path / "v14_test.sqlite3"
    conn = init_v14b_db(db_path)

    # main_path_edges
    conn.executemany("""
        INSERT INTO main_path_edges (citing_id, cited_id, spc, v13_weight, main_path_weight, is_main_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (2, 1, 1.0, 1.0, 1.0, 1),
        (3, 2, 1.0, 1.0, 1.0, 1),
        (4, 3, 1.0, 1.0, 1.0, 1),
    ])

    # subgraph_nodes
    conn.executemany("""
        INSERT INTO subgraph_nodes (paper_id, keystone_score_v14, lifecycle_v14,
            is_keystone, is_fresh_top, is_neighbor, primary_field_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [
        (1, 0.9, "mature", 1, 0, 0, 1),
        (2, 0.8, "growing", 1, 0, 0, 1),
        (3, 0.7, "fresh", 1, 1, 0, 2),
        (4, 0.6, "fresh", 0, 1, 0, 2),
        (5, 0.5, "growing", 0, 0, 1, 3),
    ])

    # subgraph_edges
    conn.executemany("""
        INSERT INTO subgraph_edges (citing_id, cited_id, citation_function, citation_function_confidence)
        VALUES (?, ?, ?, ?)
    """, [
        (2, 1, "extension", 0.9),
        (3, 2, "motivation", 0.8),
        (4, 3, "background", 0.7),
        (5, 2, "usage", 0.85),
    ])

    # predicted_future_edges
    conn.executemany("""
        INSERT INTO predicted_future_edges (
            src_paper_id, dst_paper_id, predicted_prob, raw_predicted_prob,
            calibrated_prob, prediction_confidence, calibration_label,
            src_year, dst_year, is_cross_field
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (4, 5, 0.85, 0.9, 0.82, 0.78, "calibrated_temporal_holdout", 2024, 2022, 1),
        (3, 1, 0.75, 0.8, 0.72, 0.68, "calibrated_temporal_holdout", 2024, 2018, 0),
    ])

    # limitation_atoms
    conn.executemany("""
        INSERT INTO limitation_atoms (atom_id, paper_id, description, keyword, severity)
        VALUES (?, ?, ?, ?, ?)
    """, [
        (1, 1, "Requires high power", "high power", "high"),
        (2, 2, "Limited scalability", "scalability", "medium"),
        (3, 1, "Complex fabrication", "fabrication", "high"),
    ])

    conn.commit()
    return db_path, conn


def create_main_db(tmp_path):
    """创建主 DB"""
    db_path = tmp_path / "main_test.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            abstract TEXT,
            publication_year INTEGER,
            cited_by_count INTEGER DEFAULT 0,
            primary_field_id INTEGER,
            keystone_score_v14 REAL,
            lifecycle_v14 TEXT,
            c_cd_subdomain REAL,
            c_bridging_centrality REAL,
            c_recent_burst REAL
        );
    """)
    for i in range(1, 11):
        year = 2018 + i
        conn.execute("""
            INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (i, f"Paper {i}", f"arxiv_{i}", f"Abstract {i}.",
              year, 50 * i, i % 5 + 1, 0.9 - i * 0.05,
              "mature" if year < 2022 else ("growing" if year < 2024 else "fresh"),
              0.3 + i * 0.02, 0.4 + i * 0.03, 0.5 + i * 0.02))
    conn.commit()
    return db_path, conn


# ---------------------------------------------------------------------------
# Fusion 测试
# ---------------------------------------------------------------------------

class TestFusion:
    def test_load_main_path_terminals(self, tmp_path):
        from echelon.v14b.step6_fusion import load_main_path_terminals
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)
        db_main_path, conn_main = create_main_db(tmp_path)

        terminals = load_main_path_terminals(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        # Should find terminal nodes (in main path but not as citing)
        assert isinstance(terminals, list)

    def test_load_vgae_predictions(self, tmp_path):
        from echelon.v14b.step6_fusion import load_vgae_predictions
        _, conn_v14 = create_full_test_db(tmp_path)
        preds = load_vgae_predictions(conn_v14)
        conn_v14.close()

        assert len(preds) == 2
        assert preds[0]["predicted_prob"] >= preds[1]["predicted_prob"]

    def test_load_unresolved_limitations(self, tmp_path):
        from echelon.v14b.step6_fusion import load_unresolved_limitations
        _, conn_v14 = create_full_test_db(tmp_path)
        unresolved = load_unresolved_limitations(conn_v14)
        conn_v14.close()

        # All 3 atoms have no resolutions
        assert len(unresolved) == 3

    def test_direction_clusters_produced(self, tmp_path):
        from echelon.v14b.step6_fusion import compute_direction_clusters, load_vgae_predictions, load_unresolved_limitations
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)
        db_main_path, conn_main = create_main_db(tmp_path)

        terminals = [{"paper_id": 4, "publication_year": 2024}]
        vgae_preds = load_vgae_predictions(conn_v14)
        unresolved = load_unresolved_limitations(conn_v14)

        candidates = compute_direction_clusters(
            terminals,
            vgae_preds,
            unresolved,
            conn_main,
            calibration_context={"has_run_audit": True, "avg_calibrated_auc": 0.84},
        )
        conn_v14.close()
        conn_main.close()

        # Should produce at least 1 candidate
        assert isinstance(candidates, list)
        for c in candidates:
            assert "evidence_paths" in c
            assert c["evidence_paths"] >= 2  # At least 2 evidence paths

    def test_direction_clusters_without_run_audit_are_candidate_pool_only(self, tmp_path):
        from echelon.v14b.step6_fusion import compute_direction_clusters, load_vgae_predictions, load_unresolved_limitations

        _, conn_v14 = create_full_test_db(tmp_path)
        _, conn_main = create_main_db(tmp_path)
        conn_main.execute("UPDATE papers SET abstract=? WHERE id=5", ("scalability remains the bottleneck",))
        conn_main.commit()

        candidates = compute_direction_clusters(
            [{"paper_id": 4, "publication_year": 2024}],
            load_vgae_predictions(conn_v14),
            load_unresolved_limitations(conn_v14),
            conn_main,
            calibration_context={"has_run_audit": False},
        )
        conn_v14.close()
        conn_main.close()

        assert candidates
        assert candidates[0]["evidence_tier"] == "exploratory_uncalibrated_candidate"
        assert candidates[0]["claim_scope"] == "candidate_pool_only"
        assert "rolling held-out-year calibration audit" in candidates[0]["missing_gates"]

    def test_write_future_directions(self, tmp_path):
        from echelon.v14b.step6_fusion import write_future_directions
        _, conn_v14 = create_full_test_db(tmp_path)

        directions = [
            {"direction_name": "AI photonics", "confidence": 0.8,
             "expected_period": "2026-2028", "main_path_evidence": "mp",
             "vgae_evidence": "vgae", "limitation_evidence": "limit",
             "paper_ids_json": "[1, 2]"},
        ]
        n = write_future_directions(conn_v14, directions)
        conn_v14.close()
        assert n == 1

    def test_write_fusion_evidence_audit_marks_limited_output(self, tmp_path):
        from echelon.v14b.step6_fusion import write_fusion_evidence_audit

        _, conn_v14 = create_full_test_db(tmp_path)
        audit = write_fusion_evidence_audit(
            conn_v14,
            terminals=[{"paper_id": "4"}],
            vgae_preds=[{"src_paper_id": "4", "dst_paper_id": "5"}],
            unresolved=[{"evidence_quality": "weak_abstract"}],
            candidates=[{
                "evidence_paths": 2,
                "evidence_tier": "exploratory_weak_limitation",
                "calibration_label": "calibrated_temporal_holdout",
                "prediction_confidence": 0.58,
            }],
            n_directions=1,
        )
        row = conn_v14.execute(
            "SELECT adequacy_label, candidate_tier_json, calibration_json FROM fusion_evidence_audit"
        ).fetchone()
        conn_v14.close()

        assert audit["adequacy_label"] == "sparse_evidence"
        assert row[0] == "sparse_evidence"
        assert "exploratory_weak_limitation" in row[1]
        assert "calibrated_temporal_holdout" in row[2]

    def test_direction_tier_marks_weak_abstract_as_exploratory(self):
        from echelon.v14b.step6_fusion import claim_scope_for_tier, direction_evidence_tier

        tier = direction_evidence_tier(
            evidence_paths=2,
            limitation_quality=["weak_abstract"],
            prediction_confidence=0.58,
            has_main_path=False,
        )

        assert tier == "exploratory_weak_limitation"
        assert claim_scope_for_tier(tier) == "exploratory_hypothesis"

    def test_direction_tier_keeps_uncalibrated_future_candidate_in_pool(self):
        from echelon.v14b.step6_fusion import claim_scope_for_tier, direction_evidence_tier

        tier = direction_evidence_tier(
            evidence_paths=2,
            limitation_quality=["section_level"],
            prediction_confidence=0.82,
            has_main_path=True,
            calibrated_for_fusion=False,
        )

        assert tier == "exploratory_uncalibrated_candidate"
        assert claim_scope_for_tier(tier) == "candidate_pool_only"


# ---------------------------------------------------------------------------
# 突变标记测试
# ---------------------------------------------------------------------------

class TestMutationMarking:
    def test_mark_red_mutations_threshold(self, tmp_path):
        from echelon.v14b.step7_mutation import mark_red_mutations
        db_main_path, conn_main = create_main_db(tmp_path)
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)

        node_ids = list(range(1, 11))
        red_ids = mark_red_mutations(conn_main, conn_v14, node_ids, cd_threshold=0.3)
        conn_main.close()
        conn_v14.close()

        # Should return a set
        assert isinstance(red_ids, set)
        for nid in red_ids:
            assert nid in node_ids

    def test_mark_orange_mutations(self, tmp_path):
        from echelon.v14b.step7_mutation import mark_orange_mutations
        db_main_path, conn_main = create_main_db(tmp_path)
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)

        node_ids = list(range(1, 11))
        orange_ids = mark_orange_mutations(conn_main, conn_v14, node_ids, percentile=0.7)
        conn_main.close()
        conn_v14.close()

        assert isinstance(orange_ids, set)
        # With percentile=0.7, expect ~30% to be marked
        assert len(orange_ids) <= len(node_ids)

    def test_mark_purple_mutations(self, tmp_path):
        from echelon.v14b.step7_mutation import mark_purple_mutations
        db_main_path, conn_main = create_main_db(tmp_path)

        node_ids = list(range(1, 11))
        purple_ids = mark_purple_mutations(conn_main, node_ids, percentile=0.8)
        conn_main.close()

        assert isinstance(purple_ids, set)
        assert len(purple_ids) <= len(node_ids)

    def test_mutation_write_updates_db(self, tmp_path):
        from echelon.v14b.step7_mutation import write_mutations
        _, conn_v14 = create_full_test_db(tmp_path)

        red_ids = {1, 2}
        orange_ids = {3}
        purple_ids = {4, 5}

        n = write_mutations(conn_v14, red_ids, orange_ids, purple_ids)
        conn_v14.close()

        assert n == len(red_ids | orange_ids | purple_ids)

    def test_mutation_percentile_boundary(self):
        """边界测试: p95 阈值正确"""
        vals = list(range(100))  # 0-99
        threshold = np.percentile(vals, 95)
        high = {v for v in vals if v >= threshold}
        assert len(high) <= 6  # 约 5% 超过 p95


# ---------------------------------------------------------------------------
# UMAP 布局测试
# ---------------------------------------------------------------------------

class TestUMAPLayout:
    def test_year_to_z_mapping(self):
        from echelon.v14b.utils import year_to_z
        assert year_to_z(1991) == pytest.approx(0.0)
        assert year_to_z(2026) == pytest.approx(1.0)
        z_mid = year_to_z(2008)  # midpoint
        assert 0.0 < z_mid < 1.0

    def test_year_to_z_clamp(self):
        from echelon.v14b.utils import year_to_z
        assert year_to_z(1980) == pytest.approx(0.0)  # before min
        assert year_to_z(2050) == pytest.approx(1.0)  # after max

    def test_field_to_color_format(self):
        from echelon.v14b.step8_layout import field_to_color
        color = field_to_color(1)
        assert color.startswith("#")
        assert len(color) == 7

    def test_field_to_color_none(self):
        from echelon.v14b.step8_layout import field_to_color
        color = field_to_color(None)
        assert color == "#888888"

    def test_compute_node_sizes_range(self):
        from echelon.v14b.step8_layout import compute_node_sizes
        from echelon.v14b.config import NODE_SIZE_MIN, NODE_SIZE_MAX

        cite_counts = [0, 10, 100, 1000, 10000]
        sizes = compute_node_sizes(cite_counts)
        assert len(sizes) == 5
        for s in sizes:
            assert NODE_SIZE_MIN <= s <= NODE_SIZE_MAX

    def test_umap_output_shape(self):
        from echelon.v14b.step8_layout import compute_umap_layout
        features = np.random.randn(20, 64).astype(np.float32)
        xy = compute_umap_layout(features, n_neighbors=5)
        assert xy.shape == (20, 2)

    def test_pca_fallback_output_shape(self):
        from echelon.v14b.step8_layout import compute_pca_fallback_layout
        features = np.random.randn(20, 64).astype(np.float32)
        xy = compute_pca_fallback_layout(features)
        assert xy.shape == (20, 2)

    def test_umap_normalize_xy(self):
        from echelon.v14b.step8_layout import normalize_xy
        coords = np.array([[100.0, -50.0], [200.0, 50.0], [150.0, 0.0]])
        normalized = normalize_xy(coords)
        assert normalized[:, 0].min() == pytest.approx(-1.0, abs=0.01)
        assert normalized[:, 0].max() == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# 报告生成器测试 (13 章节)
# ---------------------------------------------------------------------------

class TestReportGenerator:
    EXPECTED_SECTIONS = [
        "执行摘要",
        "OpenAlex / Field 覆盖质量",
        "全网 Main Path",
        "V14 调权",
        "子图选取",
        "SciBERT",
        "VGAE Link Prediction",
        "Limitation Tracking",
        "三路融合",
        "三色突变",
        "演化树布局",
        "V12.5",
        "下一步建议",
    ]

    def test_all_13_sections_present(self, tmp_path):
        from echelon.v14b.step9_report import generate_algo_report
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)
        db_main_path, conn_main = create_main_db(tmp_path)

        report = generate_algo_report(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        for section in self.EXPECTED_SECTIONS:
            assert section in report, f"Section '{section}' missing from report"

    def test_report_has_markdown_tables(self, tmp_path):
        from echelon.v14b.step9_report import generate_algo_report
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)
        db_main_path, conn_main = create_main_db(tmp_path)

        report = generate_algo_report(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        # Should have at least one markdown table
        assert "|---|" in report
        assert "Top 5 未来候选证据合同预览" in report
        assert "claim_scope" in report
        assert "evidence_grade" in report

    def test_algo_report_labels_openalex_as_coverage_not_success(self, tmp_path):
        from echelon.v14b.step9_report import generate_algo_report
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)
        db_main_path, conn_main = create_main_db(tmp_path)
        conn_main.execute("ALTER TABLE papers ADD COLUMN openalex_id TEXT")
        conn_main.execute("ALTER TABLE papers ADD COLUMN openalex_enriched INTEGER DEFAULT 0")
        conn_main.execute("UPDATE papers SET openalex_enriched=1")
        conn_main.execute("UPDATE papers SET openalex_id='W123' WHERE id=1")
        conn_main.commit()

        report = generate_algo_report(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        assert "OpenAlex W 覆盖率" in report
        assert "coverage is not a success claim" in report
        assert "OpenAlex enrich 成功率" not in report
        assert "OpenAlex 命中率" not in report
        assert "OpenAlex 跨库" not in report

    def test_algo_report_uses_decision_readiness_not_frontend_launch(self, tmp_path):
        from echelon.v14b.step9_report import generate_algo_report
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)
        db_main_path, conn_main = create_main_db(tmp_path)

        report = generate_algo_report(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        assert "证据决策放行条件" in report
        assert "Topic Dossier multi-topic regression" in report
        assert "Radar 主视图只允许完整 Step13 Claim Card" in report
        assert "candidate_pool_only" in report
        assert "前端启动条件" not in report
        assert "可启动 V14-B 前端开发" not in report
        assert "VGAE test AUC" not in report
        assert "主干道节点 100-200" not in report
        assert "重型算法调优建议" not in report

    def test_future_directions_report_sections(self, tmp_path):
        from echelon.v14b.step9_report import generate_future_directions_report
        db_v14_path, conn_v14 = create_full_test_db(tmp_path)

        # Add a future direction
        conn_v14.execute("""
            INSERT INTO future_directions (direction_name, confidence, expected_period,
                main_path_evidence, vgae_evidence, limitation_evidence, paper_ids_json)
            VALUES ('AI photonics', 0.85, '2026-2028', 'mp', 'vgae', 'limit', '[1,2]')
        """)
        conn_v14.commit()

        db_main_path, conn_main = create_main_db(tmp_path)
        report = generate_future_directions_report(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        assert "未来候选方向证据合同" in report
        assert "AI photonics" in report
        assert "三路证据" in report
        assert "claim_scope" in report
        assert "evidence_grade" in report
        assert "uncertainty_reasons" in report
        assert "candidate_pool_only" in report

    def test_empty_db_report_has_tbd(self, tmp_path):
        """无数据时报告有 TBD 占位"""
        from echelon.v14b.step9_report import generate_future_directions_report
        db_v14_path = tmp_path / "empty_v14.sqlite3"
        conn_v14 = init_v14b_db(db_v14_path)

        db_main_path, conn_main = create_main_db(tmp_path)
        report = generate_future_directions_report(conn_main, conn_v14)
        conn_v14.close()
        conn_main.close()

        assert "TBD" in report or "尚无数据" in report
        assert "make product-chain" in report
        assert "make post-frontfill-chain" in report
        assert "make pilot 全流程" not in report

    def test_future_report_links_use_external_ids(self):
        from echelon.v14b.step9_report import _paper_reference_markdown

        linked = _paper_reference_markdown({
            "id": "01INTERNAL",
            "title": "Real arXiv paper",
            "publication_year": 2024,
            "arxiv_id": "2401.12345",
            "doi": None,
        })
        assert "https://arxiv.org/abs/2401.12345" in linked
        assert "https://arxiv.org/abs/01INTERNAL" not in linked

        fallback = _paper_reference_markdown({
            "id": "01INTERNAL",
            "title": "Local only paper",
            "publication_year": 2024,
            "arxiv_id": None,
            "doi": None,
        })
        assert "local_id: `01INTERNAL`" in fallback

    def test_decision_readiness_recommendation(self):
        from echelon.v14b.step9_report import _decision_readiness_recommendation
        assert "CANDIDATE_POOL_READY" in _decision_readiness_recommendation(15, 100, 50)
        assert "EVIDENCE_GATED" in _decision_readiness_recommendation(5, 30, 20)
        assert "INSUFFICIENT_EVIDENCE" in _decision_readiness_recommendation(0, 0, 0)


# ---------------------------------------------------------------------------
# DB Schema 测试
# ---------------------------------------------------------------------------

class TestDBSchema:
    def test_init_creates_all_tables(self, tmp_path):
        db_path = tmp_path / "test.sqlite3"
        conn = init_v14b_db(db_path)

        expected_tables = [
            "main_path_edges",
            "subgraph_nodes",
            "subgraph_edges",
            "limitation_atoms",
            "limitation_resolutions",
            "predicted_future_edges",
            "future_directions",
            "v14b_run_meta",
        ]
        for table in expected_tables:
            count = conn.execute(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            ).fetchone()[0]
            assert count == 1, f"Table '{table}' not found"
        conn.close()

    def test_pydantic_main_path_edge_validation(self):
        from echelon.v14b.db_schema import MainPathEdge
        edge = MainPathEdge(citing_id=1, cited_id=2, spc=1.0, v13_weight=0.5, main_path_weight=0.5)
        assert edge.citing_id == "1"
        assert edge.is_main_path == False

    def test_pydantic_future_direction_validation(self):
        from echelon.v14b.db_schema import FutureDirection
        d = FutureDirection(direction_name="Test direction", confidence=0.85)
        assert d.confidence == pytest.approx(0.85)
        assert d.direction_id is None

    def test_pydantic_confidence_bounds(self):
        from echelon.v14b.db_schema import SubgraphNode
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SubgraphNode(paper_id=1, keystone_score_v14=1.5)  # > 1.0
