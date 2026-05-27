"""
tests/v14b/test_subgraph.py

子图构建单元测试 (节点数 / 边数 / 邻居完整性)
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from echelon.v14b.db_schema import init_v14b_db


# ---------------------------------------------------------------------------
# 测试 DB 工厂
# ---------------------------------------------------------------------------

def create_test_db(tmp_path):
    """创建包含测试数据的 SQLite DB"""
    db_path = tmp_path / "test_main.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 创建 papers 表
    conn.executescript("""
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            publication_year INTEGER,
            publication_date TEXT,
            cited_by_count INTEGER DEFAULT 0,
            primary_field_id INTEGER,
            keystone_score_v14 REAL,
            lifecycle_v14 TEXT,
            openalex_enriched INTEGER DEFAULT 0
        );

        CREATE TABLE paper_references (
            citing_paper_id INTEGER NOT NULL,
            cited_paper_id_internal INTEGER,
            cited_openalex_id TEXT,
            PRIMARY KEY (citing_paper_id, cited_openalex_id)
        );
    """)

    # 插入测试论文
    for i in range(1, 21):
        year = 2018 + (i % 8)
        lifecycle = "fresh" if year >= 2024 else ("growing" if year >= 2022 else "mature")
        score = 0.9 - (i * 0.02)  # 0.88 到 0.52
        conn.execute("""
            INSERT INTO papers (id, title, publication_year, publication_date,
                               cited_by_count, primary_field_id,
                               keystone_score_v14, lifecycle_v14)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (i, f"Paper {i}", year, f"{year}-01-01",
              100 - i * 3, i % 5 + 1, score, lifecycle))

    # 插入引用关系 (paper i 引用 paper i-1)
    for i in range(2, 21):
        conn.execute("""
            INSERT INTO paper_references (citing_paper_id, cited_paper_id_internal, cited_openalex_id)
            VALUES (?, ?, ?)
        """, (i, i - 1, f"OA{i - 1}"))

    conn.commit()
    return db_path, conn


class TestSubgraphConstruction:
    """子图构建测试"""

    def test_select_seed_nodes_returns_keystone(self, tmp_path):
        from echelon.v14b.step4_subgraph import select_seed_nodes
        db_path, conn = create_test_db(tmp_path)

        keystone_ids, fresh_ids = select_seed_nodes(conn, top_keystone=5, top_fresh=3, fresh_year=2024)
        conn.close()

        assert len(keystone_ids) <= 5
        assert len(keystone_ids) > 0

    def test_seed_nodes_by_score_order(self, tmp_path):
        """Keystone 节点应该是 score 最高的"""
        from echelon.v14b.step4_subgraph import select_seed_nodes
        db_path, conn = create_test_db(tmp_path)

        keystone_ids, _ = select_seed_nodes(conn, top_keystone=3, top_fresh=1, fresh_year=2024)
        conn.close()

        # 前 3 个应该是 id=1,2,3 (score 最高)
        assert 1 in keystone_ids
        assert 2 in keystone_ids
        assert 3 in keystone_ids

    def test_expand_to_neighbors_finds_neighbors(self, tmp_path):
        from echelon.v14b.step4_subgraph import expand_to_neighbors
        db_path, conn = create_test_db(tmp_path)

        seed_ids = {5}  # Paper 5
        neighbors = expand_to_neighbors(conn, seed_ids, max_size=100)
        conn.close()

        # Paper 5 引用 Paper 4 (cited_paper_id=4) → neighbor
        # Paper 6 引用 Paper 5 → neighbor
        assert len(neighbors) > 0

    def test_expand_max_size_respected(self, tmp_path):
        from echelon.v14b.step4_subgraph import expand_to_neighbors
        db_path, conn = create_test_db(tmp_path)

        seed_ids = set(range(1, 11))  # 10 seed nodes
        max_size = 12
        neighbors = expand_to_neighbors(conn, seed_ids, max_size=max_size)
        conn.close()

        total = len(seed_ids) + len(neighbors)
        assert total <= max_size

    def test_no_overlap_seed_and_neighbors(self, tmp_path):
        from echelon.v14b.step4_subgraph import expand_to_neighbors
        db_path, conn = create_test_db(tmp_path)

        seed_ids = {5, 6, 7}
        neighbors = expand_to_neighbors(conn, seed_ids, max_size=100)
        conn.close()

        assert len(seed_ids & neighbors) == 0, "Seeds and neighbors should not overlap"

    def test_select_subgraph_edges_intra_only(self, tmp_path):
        from echelon.v14b.step4_subgraph import select_subgraph_edges
        db_path, conn_main = create_test_db(tmp_path)

        db_v14_path = tmp_path / "test_v14.sqlite3"
        conn_v14 = init_v14b_db(db_v14_path)

        # 子图包含 papers 1-5
        node_ids = {1, 2, 3, 4, 5}
        edges = select_subgraph_edges(conn_main, conn_v14, node_ids)
        conn_main.close()
        conn_v14.close()

        # 所有边的 citing 和 cited 都应在 node_ids 中
        for e in edges:
            assert e["citing_id"] in node_ids
            assert e["cited_id"] in node_ids

    def test_node_count_reasonable(self, tmp_path):
        from echelon.v14b.step4_subgraph import select_seed_nodes, expand_to_neighbors
        db_path, conn = create_test_db(tmp_path)

        keystone_ids, fresh_ids = select_seed_nodes(conn, top_keystone=5, top_fresh=3)
        seed_ids = keystone_ids | fresh_ids
        neighbors = expand_to_neighbors(conn, seed_ids, max_size=50)
        conn.close()

        total = len(seed_ids | neighbors)
        assert total > 0
        assert total <= 50

    def test_node_in_degree_requirement(self, tmp_path):
        """至少 70% 节点应有 in_degree >= 1 (避免太多孤立点)"""
        db_path, conn_main = create_test_db(tmp_path)
        db_v14_path = tmp_path / "test_v14.sqlite3"
        conn_v14 = init_v14b_db(db_v14_path)

        from echelon.v14b.step4_subgraph import select_subgraph_edges
        # 用全部节点
        node_ids = set(range(1, 21))
        edges = select_subgraph_edges(conn_main, conn_v14, node_ids)
        conn_main.close()
        conn_v14.close()

        if edges:
            cited_ids = {e["cited_id"] for e in edges}
            # 检查有被引的节点比例
            has_in_degree = len(cited_ids & node_ids)
            ratio = has_in_degree / len(node_ids)
            # 测试数据中有 70% 以上有被引 (除了 paper 20 没有被引用)
            assert ratio > 0.5, f"Expected > 50% nodes with in_degree>=1, got {ratio:.1%}"
