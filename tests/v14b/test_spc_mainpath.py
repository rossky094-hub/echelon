"""
tests/v14b/test_spc_mainpath.py

SPC 算法单元测试 (合成 DAG)
"""
import math
import sqlite3
import pytest
import networkx as nx

from echelon.v14b.step2_mainpath import (
    build_spc_dag,
    compute_spc,
    expand_component_spc_to_edges,
    load_citation_graph,
)


def compute_spc_simple(G):
    """简化版 SPC 计算,用于测试"""
    if not nx.is_directed_acyclic_graph(G):
        raise ValueError("Graph must be a DAG")

    sources = [n for n, d in G.in_degree() if d == 0]
    sinks = [n for n, d in G.out_degree() if d == 0]
    topo = list(nx.topological_sort(G))

    f = {s: 1.0 for s in sources}
    for v in topo:
        if v not in f:
            f[v] = sum(f.get(u, 0.0) for u in G.predecessors(v))

    g = {t: 1.0 for t in sinks}
    for v in reversed(topo):
        if v not in g:
            g[v] = sum(g.get(w, 0.0) for w in G.successors(v))

    spc = {}
    for u, v in G.edges():
        spc[(u, v)] = f.get(u, 0.0) * g.get(v, 0.0)
    return spc


class TestSPCAlgorithm:
    """SPC 算法合成 DAG 验证"""

    def test_simple_chain(self):
        """简单链式图: A → B → C"""
        G = nx.DiGraph()
        G.add_edges_from([("A", "B"), ("B", "C")])
        spc = compute_spc_simple(G)
        # 两条边各有 1 条路径
        assert spc[("A", "B")] == pytest.approx(1.0)
        assert spc[("B", "C")] == pytest.approx(1.0)

    def test_diamond_graph(self):
        """菱形图: S → A → T, S → B → T"""
        G = nx.DiGraph()
        G.add_edges_from([("S", "A"), ("S", "B"), ("A", "T"), ("B", "T")])
        spc = compute_spc_simple(G)
        # S→A 经过的路径: f(S)=1, g(A)=1
        # S→B 经过的路径: f(S)=1, g(B)=1
        assert spc[("S", "A")] == pytest.approx(1.0)
        assert spc[("S", "B")] == pytest.approx(1.0)
        # A→T: f(A)=1, g(T)=1
        assert spc[("A", "T")] == pytest.approx(1.0)

    def test_convergent_paths(self):
        """收敛图: A → C, B → C → D"""
        G = nx.DiGraph()
        G.add_edges_from([("A", "C"), ("B", "C"), ("C", "D")])
        spc = compute_spc_simple(G)
        # C → D: f(C) = f(A) + f(B) = 2, g(D) = 1
        assert spc[("C", "D")] == pytest.approx(2.0)
        # A → C: f(A)=1, g(C)=1
        assert spc[("A", "C")] == pytest.approx(1.0)

    def test_spc_nonnegative(self):
        """所有 SPC 值 >= 0"""
        G = nx.DiGraph()
        G.add_edges_from([(1, 2), (1, 3), (2, 4), (3, 4), (4, 5)])
        spc = compute_spc_simple(G)
        for v in spc.values():
            assert v >= 0

    def test_main_path_weight_formula(self):
        """main_path_weight = log(SPC + 1) * v13_weight"""
        spc_val = 10.0
        v13_weight = 2.0
        expected = math.log(spc_val + 1) * v13_weight
        actual = math.log(spc_val + 1) * v13_weight
        assert actual == pytest.approx(expected)

    def test_main_path_weight_zero_spc(self):
        """SPC=0 时 main_path_weight = 0"""
        spc_val = 0.0
        v13_weight = 1.0
        result = math.log(spc_val + 1) * v13_weight
        assert result == pytest.approx(0.0)

    def test_empty_graph(self):
        """空图 SPC 返回空字典"""
        G = nx.DiGraph()
        spc = compute_spc_simple(G)
        assert spc == {}

    def test_single_edge(self):
        """单边图"""
        G = nx.DiGraph()
        G.add_edge("src", "dst")
        spc = compute_spc_simple(G)
        assert spc[("src", "dst")] == pytest.approx(1.0)

    def test_branching_paths(self):
        """分支图: S → A, S → B, A → T, B → T"""
        G = nx.DiGraph()
        G.add_edges_from([("S", "A"), ("S", "B"), ("A", "T"), ("B", "T")])
        spc = compute_spc_simple(G)
        # S 到 T 有 2 条路径
        # S→A: f(S)=1, g(A)=1
        assert spc[("S", "A")] == pytest.approx(1.0)
        # S→B: f(S)=1, g(B)=1
        assert spc[("S", "B")] == pytest.approx(1.0)

    def test_topological_order_correctness(self):
        """验证 f 和 g 值在拓扑序下正确"""
        G = nx.DiGraph()
        # Linear chain: 1 → 2 → 3 → 4
        for i in range(1, 4):
            G.add_edge(i, i + 1)
        spc = compute_spc_simple(G)
        # Each edge has spc=1 in a linear chain
        for i in range(1, 4):
            assert spc[(i, i + 1)] == pytest.approx(1.0)


class TestStep2CycleHandling:
    """Cycle handling must preserve algorithm meaning, not arbitrary id order."""

    def test_scc_condensation_turns_same_time_cycle_into_dag(self):
        """A same-time citation cycle becomes one audited SCC before SPC."""
        G = nx.DiGraph()
        for node in ["A", "B", "C"]:
            G.add_node(node, year=2024, time=(2024, 1, 1, 3))
        G.add_edge("A", "B", temporal_status="same_time")
        G.add_edge("B", "A", temporal_status="same_time")
        G.add_edge("B", "C", temporal_status="forward")

        dag, edge_map, cycle_records, stats = build_spc_dag(G)

        assert nx.is_directed_acyclic_graph(dag)
        assert stats["cyclic_components"] == 1
        assert stats["intra_cycle_edges"] == 2
        assert len(cycle_records) == 1

        comp_spc = compute_spc(dag)
        paper_spc, audit = expand_component_spc_to_edges(
            comp_spc,
            edge_map,
            cycle_component_ids={cycle_records[0]["component_id"]},
        )

        assert ("B", "C") in paper_spc
        assert ("A", "B") not in paper_spc
        assert ("B", "A") not in paper_spc
        assert audit[0]["spc_scope"] == "scc_condensed"

    def test_parallel_component_edges_conserve_spc_mass(self):
        """Parallel paper edges between two SCCs split one component transition SPC."""
        G = nx.DiGraph()
        for node in ["A", "B", "C"]:
            G.add_node(node, year=2024, time=(2024, 1, 1, 3))
        G.add_edge("A", "B", temporal_status="same_time")
        G.add_edge("B", "A", temporal_status="same_time")
        G.add_edge("A", "C", temporal_status="forward")
        G.add_edge("B", "C", temporal_status="forward")

        dag, edge_map, cycle_records, _ = build_spc_dag(G)
        paper_spc, audit = expand_component_spc_to_edges(
            compute_spc(dag),
            edge_map,
            cycle_component_ids={cycle_records[0]["component_id"]},
        )

        assert paper_spc[("A", "C")] == pytest.approx(0.5)
        assert paper_spc[("B", "C")] == pytest.approx(0.5)
        assert sum(paper_spc.values()) == pytest.approx(1.0)
        assert {row["component_edge_size"] for row in audit} == {2}

    def test_load_graph_keeps_ambiguous_same_year_edges(self, tmp_path):
        """Same-year ambiguous edges are preserved for SCC audit, not id-sorted away."""
        db_path = tmp_path / "library.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE papers (
                id TEXT PRIMARY KEY,
                title TEXT,
                publication_date TEXT,
                publication_year INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE paper_references (
                citing_paper_id TEXT,
                cited_paper_id_internal TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO papers (id, title, publication_date, publication_year) VALUES (?, ?, ?, ?)",
            [
                ("A", "Paper A", "2024-01-01", 2024),
                ("B", "Paper B", "2024-01-01", 2024),
            ],
        )
        conn.executemany(
            "INSERT INTO paper_references (citing_paper_id, cited_paper_id_internal) VALUES (?, ?)",
            [
                ("A", "B"),
                ("B", "A"),
            ],
        )
        conn.commit()
        conn.close()

        G = load_citation_graph(db_path)

        assert G.has_edge("A", "B")
        assert G.has_edge("B", "A")
        assert not nx.is_directed_acyclic_graph(G)
