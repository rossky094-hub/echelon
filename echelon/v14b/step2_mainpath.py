"""
Step 2: SPC Main Path Analysis

算法: Batagelj 2003 Search Path Count (SPC)
  - 图方向: cited → citing (时间方向)
  - 动态规划计算 f(v) 和 g(v)
  - SPC(u→v) = f(u) × g(v)
  - main_path_weight = log(SPC+1) × v13_weight

输出: v14_pilot.sqlite3 的 main_path_edges 表

CLI:
    python -m echelon.v14b.step2_mainpath --help
    python -m echelon.v14b.step2_mainpath
    python -m echelon.v14b.step2_mainpath --limit 1000  # 调试
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import networkx as nx

from echelon.v14b.config import DB_MAIN, DB_V14, SPC_MAIN_PATH_PERCENTILE, LIMIT
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import (
    setup_logging, Checkpoint, add_common_args, make_progress,
    ensure_library_schema_compat, table_columns,
)

logger = logging.getLogger("echelon.v14b.step2_mainpath")

# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

def _parse_publication_time(publication_date: str | None, publication_year: int | None) -> tuple[int, int, int, int]:
    """
    Return (year, month, day, precision).

    precision: 0 unknown, 1 year, 2 month, 3 day.  The graph builder only uses
    these values to reject clear time-inverted citations; ambiguous same-year
    and unknown-date edges are preserved for SCC condensation instead of being
    ordered by ingestion id.
    """
    year = int(publication_year or 0)
    month = 0
    day = 0
    precision = 1 if year else 0

    if publication_date:
        parts = str(publication_date).strip().split("-")
        try:
            if parts and len(parts[0]) == 4:
                year = int(parts[0])
                precision = max(precision, 1)
            if len(parts) >= 2 and parts[1]:
                month = int(parts[1])
                precision = max(precision, 2)
            if len(parts) >= 3 and parts[2]:
                day = int(parts[2][:2])
                precision = max(precision, 3)
        except ValueError:
            pass

    return year, month, day, precision


def _temporal_status(cited: dict, citing: dict) -> str:
    """Classify a real citation edge before converting it to cited -> citing."""
    cy, cm, cd, cp = cited["time"]
    ty, tm, td, tp = citing["time"]
    if cy and ty:
        if cy > ty:
            return "time_inverted"
        if cy < ty:
            return "forward"
        if cp >= 3 and tp >= 3:
            if (cm, cd) > (tm, td):
                return "time_inverted"
            if (cm, cd) < (tm, td):
                return "forward"
        return "same_time"
    return "unknown_time"


def load_citation_graph(
    db_main: Path,
    limit: Optional[int] = None,
) -> nx.DiGraph:
    """
    从 echelon_library.sqlite3 加载引用图。

    边方向: cited → citing (时间向前方向,用于 SPC)
    节点 ID = paper.id (INTEGER)

    Returns:
        nx.DiGraph.  The graph may contain cycles caused by same-year/same-day
        or incomplete metadata; Step2 resolves those with SCC condensation
        before SPC rather than deleting arbitrary edges.
    """
    logger.info("加载引用图: %s", db_main)
    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    ensure_library_schema_compat(conn)

    # 加载所有 paper 及时间信息
    cols = table_columns(conn, "papers")
    date_expr = "publication_date" if "publication_date" in cols else "NULL AS publication_date"
    year_expr = "publication_year" if "publication_year" in cols else "NULL AS publication_year"
    papers_q = f"SELECT id, {date_expr}, {year_expr} FROM papers"
    if limit:
        papers_q += f" LIMIT {limit}"
    papers = {}
    for row in conn.execute(papers_q):
        year, month, day, precision = _parse_publication_time(
            row["publication_date"], row["publication_year"]
        )
        papers[row["id"]] = {
            "year": year,
            "time": (year, month, day, precision),
            "precision": precision,
        }
    logger.info("论文节点: %d", len(papers))

    # 加载引用边 (paper_references 表)
    # citing → cited (reversed for our time-forward graph: cited → citing)
    edges_q = """
        SELECT citing_paper_id, cited_paper_id_internal
        FROM paper_references
        WHERE cited_paper_id_internal IS NOT NULL
    """
    rows = conn.execute(edges_q).fetchall()
    logger.info("原始引用边: %d", len(rows))
    conn.close()

    G = nx.DiGraph()
    G.add_nodes_from(papers.keys())
    for n, meta in papers.items():
        G.nodes[n]["year"] = meta["year"]
        G.nodes[n]["time"] = meta["time"]

    skip_count = 0
    temporal_counts: Counter[str] = Counter()

    for row in rows:
        citing = row["citing_paper_id"]
        cited = row["cited_paper_id_internal"]
        if citing not in papers or cited not in papers:
            continue
        if cited == citing:
            continue  # 跳过自引

        status = _temporal_status(papers[cited], papers[citing])
        temporal_counts[status] += 1
        if status == "time_inverted":
            skip_count += 1
            continue  # 跳过时间倒置的边
        # 时间方向: cited → citing (older/ambiguous → newer/ambiguous)
        G.add_edge(cited, citing, temporal_status=status)

    logger.info(
        "时间方向图边: %d (跳过时间倒置: %d, temporal_status=%s)",
        G.number_of_edges(),
        skip_count,
        dict(temporal_counts),
    )
    G.graph["step2_audit"] = {
        "raw_reference_rows": len(rows),
        "time_inverted_skipped": skip_count,
        "temporal_status_counts": dict(temporal_counts),
    }

    return G


def build_spc_dag(
    G: nx.DiGraph,
) -> tuple[nx.DiGraph, dict[tuple[int, int], list[tuple[str, str, str]]], list[dict], dict]:
    """
    Convert the possibly cyclic paper citation graph into a DAG for SPC.

    Instead of deleting edges one cycle at a time, strongly connected components
    are treated as ambiguous temporal components and collapsed with NetworkX's
    condensation graph.  SPC is then computed on the component DAG and expanded
    back to original inter-component citation edges.
    """
    components = list(nx.strongly_connected_components(G))
    dag = nx.condensation(G, scc=components)
    if not nx.is_directed_acyclic_graph(dag):
        raise RuntimeError("NetworkX condensation graph is unexpectedly cyclic")

    mapping: dict[str, int] = dag.graph["mapping"]
    edge_map: dict[tuple[int, int], list[tuple[str, str, str]]] = defaultdict(list)
    intra_edges: dict[int, list[tuple[str, str, str]]] = defaultdict(list)

    for u, v, data in G.edges(data=True):
        cu = mapping[u]
        cv = mapping[v]
        status = data.get("temporal_status", "unknown_time")
        if cu == cv:
            intra_edges[cu].append((u, v, status))
        else:
            edge_map[(cu, cv)].append((u, v, status))

    cycle_records = []
    cyclic_node_count = 0
    max_component_size = 0
    for cid, members in ((n, dag.nodes[n].get("members", set())) for n in dag.nodes()):
        size = len(members)
        max_component_size = max(max_component_size, size)
        if size <= 1:
            continue
        cyclic_node_count += size
        years = [int(G.nodes[m].get("year") or 0) for m in members if int(G.nodes[m].get("year") or 0) > 0]
        sample_edges = [
            {"source": u, "target": v, "temporal_status": status}
            for u, v, status in intra_edges.get(cid, [])[:20]
        ]
        cycle_records.append({
            "component_id": str(cid),
            "component_size": size,
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "intra_edges": len(intra_edges.get(cid, [])),
            "member_ids_json": json.dumps(sorted(members), ensure_ascii=False),
            "sample_edges_json": json.dumps(sample_edges, ensure_ascii=False),
        })

    stats = {
        "paper_nodes": G.number_of_nodes(),
        "paper_edges": G.number_of_edges(),
        "spc_dag_nodes": dag.number_of_nodes(),
        "spc_dag_edges": dag.number_of_edges(),
        "cyclic_components": len(cycle_records),
        "cyclic_nodes": cyclic_node_count,
        "intra_cycle_edges": sum(len(v) for v in intra_edges.values()),
        "max_component_size": max_component_size,
        "component_edge_groups": len(edge_map),
        "parallel_inter_component_edges": sum(max(0, len(v) - 1) for v in edge_map.values()),
    }

    if cycle_records:
        logger.warning(
            "引用图含 %d 个强连通循环分量(%d nodes, %d intra edges); "
            "使用 SCC condensation DAG 计算 SPC,不按 ULID/任意顺序删边",
            stats["cyclic_components"],
            stats["cyclic_nodes"],
            stats["intra_cycle_edges"],
        )
    else:
        logger.info("引用图已是 DAG; SCC condensation 未发现循环分量")
    logger.info("SPC DAG: nodes=%d edges=%d", dag.number_of_nodes(), dag.number_of_edges())

    return dag, dict(edge_map), cycle_records, stats


def expand_component_spc_to_edges(
    spc: dict[tuple[int, int], float],
    edge_map: dict[tuple[int, int], list[tuple[str, str, str]]],
    cycle_component_ids: set[str] | None = None,
) -> tuple[dict[tuple[str, str], float], list[dict]]:
    """
    Expand component-level SPC to original inter-component paper edges.

    If multiple paper citations connect the same two SCC components, the SPC
    mass is divided across those edges. This keeps component transition weight
    conserved and avoids making dense ambiguous components dominate simply
    because they contain many parallel paper-level citations.
    """
    cycle_component_ids = cycle_component_ids or set()
    paper_spc: dict[tuple[str, str], float] = {}
    edge_audit: list[dict] = []

    for (cu, cv), originals in edge_map.items():
        comp_spc = float(spc.get((cu, cv), 0.0))
        parallel_n = max(1, len(originals))
        per_edge_spc = comp_spc / parallel_n
        scope = (
            "scc_condensed"
            if str(cu) in cycle_component_ids or str(cv) in cycle_component_ids or parallel_n > 1
            else "paper_dag"
        )
        for u, v, status in originals:
            paper_spc[(u, v)] = per_edge_spc
            edge_audit.append({
                "citing_id": u,
                "cited_id": v,
                "source_component_id": str(cu),
                "target_component_id": str(cv),
                "component_edge_size": parallel_n,
                "spc_scope": scope,
                "temporal_status": status,
            })

    return paper_spc, edge_audit


# ---------------------------------------------------------------------------
# SPC 计算
# ---------------------------------------------------------------------------

def compute_spc(G: nx.DiGraph) -> dict[tuple[int, int], float]:
    """
    Batagelj (2003) SPC 算法。

    SPC(u→v) = f(u) × g(v)

    where:
      f(v) = 从 sources 到 v 的路径条数
      g(v) = 从 v 到 sinks 的路径条数

    Returns:
        Dict {(u, v): spc_value}
    """
    logger.info("计算 SPC,节点数=%d 边数=%d", G.number_of_nodes(), G.number_of_edges())

    sources = [n for n, d in G.in_degree() if d == 0]
    sinks = [n for n, d in G.out_degree() if d == 0]
    logger.info("源节点(in_degree=0): %d, 汇节点(out_degree=0): %d",
                len(sources), len(sinks))

    # 拓扑排序
    topo = list(nx.topological_sort(G))

    # 正向 DP: f(v) = 从 source 到 v 的路径数
    f: dict[int, float] = {s: 1.0 for s in sources}
    for v in topo:
        if v not in f:
            f[v] = sum(f.get(u, 0.0) for u in G.predecessors(v))

    # 反向 DP: g(v) = 从 v 到 sink 的路径数
    g: dict[int, float] = {t: 1.0 for t in sinks}
    for v in reversed(topo):
        if v not in g:
            g[v] = sum(g.get(w, 0.0) for w in G.successors(v))

    # SPC(u→v) = f(u) * g(v)
    spc = {}
    for u, v in G.edges():
        spc[(u, v)] = f.get(u, 0.0) * g.get(v, 0.0)

    logger.info("SPC 计算完成,共 %d 条边", len(spc))
    return spc


def compute_main_path_weights(
    G: nx.DiGraph,
    spc: dict[tuple[int, int], float],
    db_main: Path,
) -> list[dict]:
    """
    计算最终边权并确定 is_main_path。

    main_path_weight = log(SPC + 1) × v13_weight

    v13_weight 从 fused_edges / edge_override 表读取,默认 1.0

    Returns:
        List of edge dicts for DB insert
    """
    # 尝试读取 V13 边权
    v13_weights: dict[tuple[int, int], float] = {}
    try:
        conn = sqlite3.connect(str(db_main))
        rows = conn.execute("""
            SELECT citing_id, cited_id, weight
            FROM fused_edges
        """).fetchall()
        for row in rows:
            v13_weights[(row[0], row[1])] = row[2] or 1.0
        conn.close()
        logger.info("读取 V13 边权: %d 条", len(v13_weights))
    except Exception:
        logger.info("V13 边权表不存在,使用默认值 1.0")

    edges = []
    for (u, v), spc_val in spc.items():
        v13_w = v13_weights.get((u, v), 1.0)
        mpw = math.log(spc_val + 1) * v13_w
        edges.append({
            "citing_id": u,
            "cited_id": v,
            "spc": spc_val,
            "v13_weight": v13_w,
            "main_path_weight": mpw,
            "is_main_path": 0,  # 后续用分位数标记
        })

    # 标记 top 1% 为主干道
    if edges:
        weights = sorted([e["main_path_weight"] for e in edges], reverse=True)
        threshold_idx = max(0, int(len(weights) * (1 - SPC_MAIN_PATH_PERCENTILE)) - 1)
        threshold = weights[threshold_idx]
        for e in edges:
            if e["main_path_weight"] >= threshold:
                e["is_main_path"] = 1
        main_path_count = sum(1 for e in edges if e["is_main_path"])
        logger.info("主干道边数: %d (threshold=%.4f)", main_path_count, threshold)

    return edges


# ---------------------------------------------------------------------------
# DB 写入
# ---------------------------------------------------------------------------

def write_main_path_edges(
    conn_v14: sqlite3.Connection,
    edges: list[dict],
    batch_size: int = 5000,
) -> int:
    """批量写入 main_path_edges 表"""
    conn_v14.execute("DELETE FROM main_path_edges")
    written = 0
    for i in range(0, len(edges), batch_size):
        batch = edges[i: i + batch_size]
        conn_v14.executemany("""
            INSERT OR REPLACE INTO main_path_edges
                (citing_id, cited_id, spc, v13_weight, main_path_weight, is_main_path)
            VALUES (:citing_id, :cited_id, :spc, :v13_weight, :main_path_weight, :is_main_path)
        """, batch)
        conn_v14.commit()
        written += len(batch)
    return written


def write_main_path_audit(
    conn_v14: sqlite3.Connection,
    run_id: str,
    cycle_records: list[dict],
    edge_audit: list[dict],
    batch_size: int = 5000,
) -> None:
    """Write SCC condensation diagnostics for Step2."""
    conn_v14.execute("DELETE FROM main_path_cycle_audit")
    conn_v14.execute("DELETE FROM main_path_edge_audit")

    if cycle_records:
        conn_v14.executemany("""
            INSERT OR REPLACE INTO main_path_cycle_audit
                (run_id, component_id, component_size, year_min, year_max,
                 intra_edges, member_ids_json, sample_edges_json)
            VALUES
                (:run_id, :component_id, :component_size, :year_min, :year_max,
                 :intra_edges, :member_ids_json, :sample_edges_json)
        """, [{**row, "run_id": run_id} for row in cycle_records])

    for i in range(0, len(edge_audit), batch_size):
        batch = edge_audit[i: i + batch_size]
        conn_v14.executemany("""
            INSERT OR REPLACE INTO main_path_edge_audit
                (citing_id, cited_id, source_component_id, target_component_id,
                 component_edge_size, spc_scope, temporal_status)
            VALUES
                (:citing_id, :cited_id, :source_component_id, :target_component_id,
                 :component_edge_size, :spc_scope, :temporal_status)
        """, batch)
        conn_v14.commit()
    conn_v14.commit()


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_mainpath(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    """执行 Step 2: SPC Main Path"""
    step_name = "step2_mainpath"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step2 已完成 (%d edges),跳过", data.get("records_n", 0))
        return data

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 1. 加载引用图
    G = load_citation_graph(db_main, limit=limit)

    # 2. 将含环引用图压缩为 SCC condensation DAG 后计算 SPC
    spc_dag, edge_map, cycle_records, dag_stats = build_spc_dag(G)
    spc_component = compute_spc(spc_dag)
    cycle_component_ids = {row["component_id"] for row in cycle_records}
    spc, edge_audit = expand_component_spc_to_edges(
        spc_component,
        edge_map,
        cycle_component_ids=cycle_component_ids,
    )

    # 3. 计算最终边权
    edges = compute_main_path_weights(G, spc, db_main)

    # 4. 写入 DB 和审计信息
    n_written = write_main_path_edges(conn_v14, edges)
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    write_main_path_audit(conn_v14, run_id, cycle_records, edge_audit)

    # 统计
    main_path_count = sum(1 for e in edges if e["is_main_path"])
    stats = {
        "total_edges": len(edges),
        "main_path_edges": main_path_count,
        "records_n": n_written,
        **dag_stats,
    }

    upsert_step_meta(conn_v14, step_name, "done", records_n=n_written)
    conn_v14.close()

    ck.mark_done(records_n=n_written, meta=stats)
    logger.info("Step2 完成: edges=%d main_path=%d", len(edges), main_path_count)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step2_mainpath",
        description="Step 2: SPC Main Path Analysis",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step2_mainpath", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_mainpath(db_main=db_main, db_v14=db_v14, limit=limit, resume=args.resume)


if __name__ == "__main__":
    main()
