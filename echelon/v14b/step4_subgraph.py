"""
Step 4: 子图构建

选取策略:
  1. top 1000 by keystone_score_v14 (跨 lifecycle)
  2. top 500 fresh (publication_year >= 2024) by keystone_score_v14
  3. 以上 1500 节点的 1 度引用邻居 (~1500)
  总计 ~3000 节点

输出: v14_pilot.sqlite3 的 subgraph_nodes, subgraph_edges 表

CLI:
    python -m echelon.v14b.step4_subgraph --help
    python -m echelon.v14b.step4_subgraph
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    SUBGRAPH_TOP_KEYSTONE, SUBGRAPH_TOP_FRESH, SUBGRAPH_FRESH_YEAR,
    SUBGRAPH_MAX_SIZE, LIMIT,
)
from echelon.v14b.db_schema import ensure_v14b_text_paper_ids, get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args, make_progress, table_columns

logger = logging.getLogger("echelon.v14b.step4_subgraph")


# ---------------------------------------------------------------------------
# 节点选取
# ---------------------------------------------------------------------------

def select_seed_nodes(
    conn_main: sqlite3.Connection,
    top_keystone: int = SUBGRAPH_TOP_KEYSTONE,
    top_fresh: int = SUBGRAPH_TOP_FRESH,
    fresh_year: int = SUBGRAPH_FRESH_YEAR,
) -> tuple[Set[str], Set[str]]:
    """
    选取种子节点。

    Returns:
        (keystone_set, fresh_set)
    """
    # Top keystone (all lifecycle)
    rows = conn_main.execute("""
        SELECT id FROM papers
        WHERE keystone_score_v14 IS NOT NULL
        ORDER BY keystone_score_v14 DESC
        LIMIT ?
    """, (top_keystone,)).fetchall()
    keystone_ids = {row[0] for row in rows}
    logger.info("Top keystone 节点: %d", len(keystone_ids))

    # Top fresh
    rows = conn_main.execute("""
        SELECT id FROM papers
        WHERE keystone_score_v14 IS NOT NULL
          AND (
            (publication_date IS NOT NULL AND CAST(SUBSTR(publication_date, 1, 4) AS INTEGER) >= ?)
            OR (publication_year IS NOT NULL AND publication_year >= ?)
          )
        ORDER BY keystone_score_v14 DESC
        LIMIT ?
    """, (fresh_year, fresh_year, top_fresh)).fetchall()
    fresh_ids = {row[0] for row in rows}
    logger.info("Top fresh (%d+) 节点: %d", fresh_year, len(fresh_ids))

    return keystone_ids, fresh_ids


def expand_to_neighbors(
    conn_main: sqlite3.Connection,
    seed_ids: Set[str],
    max_size: int = SUBGRAPH_MAX_SIZE,
) -> Set[str]:
    """
    将种子节点扩展到 1 度引用邻居。

    Returns:
        neighbors_only set (不含 seed_ids)
    """
    if not seed_ids:
        return set()

    neighbors = set()

    # 找所有 citing 邻居(seed 论文引用了谁)
    placeholders = ",".join("?" * len(seed_ids))
    rows = conn_main.execute(f"""
        SELECT cited_paper_id_internal
        FROM paper_references
        WHERE citing_paper_id IN ({placeholders})
          AND cited_paper_id_internal IS NOT NULL
    """, list(seed_ids)).fetchall()
    for row in rows:
        if row[0] not in seed_ids:
            neighbors.add(row[0])

    # 找所有 cited 邻居(谁引用了 seed 论文)
    rows = conn_main.execute(f"""
        SELECT citing_paper_id
        FROM paper_references
        WHERE cited_paper_id_internal IN ({placeholders})
    """, list(seed_ids)).fetchall()
    for row in rows:
        if row[0] not in seed_ids:
            neighbors.add(row[0])

    # 如果邻居太多,截断到 max_size
    if len(seed_ids) + len(neighbors) > max_size:
        allowed_neighbors = max_size - len(seed_ids)
        # 按 keystone_score 排序截断
        if allowed_neighbors > 0:
            nb_list = list(neighbors)
            rows = conn_main.execute(f"""
                SELECT id FROM papers
                WHERE id IN ({','.join('?' * len(nb_list))})
                ORDER BY COALESCE(keystone_score_v14, 0) DESC
                LIMIT ?
            """, nb_list + [allowed_neighbors]).fetchall()
            neighbors = {row[0] for row in rows}
        else:
            neighbors = set()

    logger.info("1 度邻居节点: %d", len(neighbors))
    return neighbors


# ---------------------------------------------------------------------------
# 边选取
# ---------------------------------------------------------------------------

def select_subgraph_edges(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: Set[str],
) -> list[dict]:
    """
    选取子图内部的所有引用边,并附加 main_path_weight。
    """
    # 读取主干道边权
    main_path_weights: dict[tuple[str, str], tuple[float, int]] = {}
    try:
        cols = table_columns(conn_v14, "main_path_edges")
        src_expr = "source_paper_id" if "source_paper_id" in cols else "citing_id"
        dst_expr = "target_paper_id" if "target_paper_id" in cols else "cited_id"
        rows = conn_v14.execute(f"""
            SELECT {src_expr} AS source_paper_id,
                   {dst_expr} AS target_paper_id,
                   main_path_weight,
                   is_main_path
            FROM main_path_edges
        """).fetchall()
        for row in rows:
            main_path_weights[(row["source_paper_id"], row["target_paper_id"])] = (
                row["main_path_weight"],
                row["is_main_path"],
            )
    except Exception:
        logger.info("main_path_edges 不存在,边权默认 1.0")

    # 获取子图内部引用边
    placeholders = ",".join("?" * len(node_ids))
    node_list = list(node_ids)
    rows = conn_main.execute(f"""
        SELECT citing_paper_id, cited_paper_id_internal
        FROM paper_references
        WHERE citing_paper_id IN ({placeholders})
          AND cited_paper_id_internal IN ({placeholders})
    """, node_list + node_list).fetchall()

    edges_by_pair: dict[tuple[str, str], dict] = {}
    for row in rows:
        citing_id = row[0]
        cited_id = row[1]
        mpw_data = main_path_weights.get((cited_id, citing_id))  # cited→citing direction
        mpw = mpw_data[0] if mpw_data else 1.0
        key = (citing_id, cited_id)
        if key in edges_by_pair:
            continue
        edges_by_pair[key] = {
            "citing_id": citing_id,
            "cited_id": cited_id,
            "citation_function": None,
            "citation_function_confidence": None,
            "citation_function_method": None,
            "citation_function_evidence_level": None,
            "citation_context_available": 0,
            "citation_function_weight": None,
            "main_path_weight": mpw,
        }

    edges = list(edges_by_pair.values())
    logger.info("子图边数: %d", len(edges))
    return edges


# ---------------------------------------------------------------------------
# DB 写入
# ---------------------------------------------------------------------------

def write_subgraph_nodes(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: Set[str],
    keystone_ids: Set[str],
    fresh_ids: Set[str],
    neighbor_ids: Set[str],
) -> int:
    """写入 subgraph_nodes 表"""
    # 读取论文元数据
    placeholders = ",".join("?" * len(node_ids))
    rows = conn_main.execute(f"""
        SELECT id, keystone_score_v14, lifecycle_v14, primary_field_id
        FROM papers
        WHERE id IN ({placeholders})
    """, list(node_ids)).fetchall()
    paper_data = {row[0]: dict(row) for row in rows}

    conn_v14.execute("DELETE FROM subgraph_nodes")
    nodes = []
    for nid in node_ids:
        p = paper_data.get(nid, {})
        nodes.append({
            "paper_id": nid,
            "keystone_score_v14": p.get("keystone_score_v14"),
            "lifecycle_v14": p.get("lifecycle_v14"),
            "is_keystone": int(nid in keystone_ids),
            "is_fresh_top": int(nid in fresh_ids),
            "is_neighbor": int(nid in neighbor_ids),
            "primary_field_id": p.get("primary_field_id"),
            "mutation_red": 0,
            "mutation_orange": 0,
            "mutation_purple": 0,
            "umap_x": None,
            "umap_y": None,
            "z_year": None,
            "node_size": None,
            "color_hex": None,
        })

    conn_v14.executemany("""
        INSERT OR REPLACE INTO subgraph_nodes
            (paper_id, keystone_score_v14, lifecycle_v14,
             is_keystone, is_fresh_top, is_neighbor, primary_field_id,
             mutation_red, mutation_orange, mutation_purple,
             umap_x, umap_y, z_year, node_size, color_hex)
        VALUES
            (:paper_id, :keystone_score_v14, :lifecycle_v14,
             :is_keystone, :is_fresh_top, :is_neighbor, :primary_field_id,
             :mutation_red, :mutation_orange, :mutation_purple,
             :umap_x, :umap_y, :z_year, :node_size, :color_hex)
    """, nodes)
    conn_v14.commit()
    return len(nodes)


def write_subgraph_edges(
    conn_v14: sqlite3.Connection,
    edges: list[dict],
    batch_size: int = 5000,
) -> int:
    """写入 subgraph_edges 表"""
    conn_v14.execute("DELETE FROM subgraph_edges")
    written = 0
    for i in range(0, len(edges), batch_size):
        batch = edges[i: i + batch_size]
        conn_v14.executemany("""
            INSERT OR REPLACE INTO subgraph_edges
                (citing_id, cited_id, citation_function,
                 citation_function_confidence, citation_function_method,
                 citation_function_evidence_level, citation_context_available,
                 citation_function_weight, main_path_weight)
            VALUES
                (:citing_id, :cited_id, :citation_function,
                 :citation_function_confidence, :citation_function_method,
                 :citation_function_evidence_level, :citation_context_available,
                 :citation_function_weight, :main_path_weight)
        """, batch)
        conn_v14.commit()
        written += len(batch)
    actual = conn_v14.execute("SELECT COUNT(*) FROM subgraph_edges").fetchone()[0]
    if actual != written:
        logger.warning("subgraph_edges write count changed after PK de-dup: attempted=%d actual=%d", written, actual)
    return actual


def evaluate_subgraph_scope(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    configured_max_size: int,
    selected_nodes: int,
    selected_edges: int,
) -> dict:
    """Audit whether Step4 should be interpreted as pilot evidence or full graph."""
    total_papers = conn_main.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    total_linked_refs = conn_main.execute("""
        SELECT COUNT(*)
        FROM paper_references
        WHERE cited_paper_id_internal IS NOT NULL
    """).fetchone()[0]

    node_coverage = selected_nodes / max(1, total_papers)
    edge_coverage = selected_edges / max(1, total_linked_refs)
    edge_density = selected_edges / max(1, selected_nodes)

    if total_papers <= configured_max_size and selected_nodes >= total_papers * 0.95:
        conclusion_scope = "complete_graph"
        adequacy_label = "complete"
        recommended_max_size = total_papers
    else:
        conclusion_scope = "pilot_evidence_subgraph"
        baseline = max(3000, int(total_papers * 0.08))
        recommended_max_size = min(total_papers, max(configured_max_size, baseline))
        if selected_nodes < 3000 or selected_edges < selected_nodes * 0.5:
            adequacy_label = "pilot_sparse_increase_or_use_step10_full_graph"
            recommended_max_size = min(total_papers, max(recommended_max_size, 8000))
        elif configured_max_size < recommended_max_size:
            adequacy_label = "pilot_usable_but_cap_below_recommended"
        else:
            adequacy_label = "pilot_adequate_for_algorithmic_evidence"

    notes = {
        "interpretation": (
            "Step4 supports expensive downstream evidence extraction. "
            "Claims about the complete optics graph must come from Step10 visual graph."
        ),
        "configured_max_size_rationale": (
            "5000 is acceptable as a memory-conscious pilot for ~55k papers when Step10 "
            "separately positions all papers; increase if subgraph edge density is sparse."
        ),
    }
    audit = {
        "run_id": datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "total_papers": int(total_papers),
        "total_linked_refs": int(total_linked_refs),
        "configured_max_size": int(configured_max_size),
        "recommended_max_size": int(recommended_max_size),
        "selected_nodes": int(selected_nodes),
        "selected_edges": int(selected_edges),
        "node_coverage": float(node_coverage),
        "edge_coverage": float(edge_coverage),
        "edge_density": float(edge_density),
        "conclusion_scope": conclusion_scope,
        "adequacy_label": adequacy_label,
        "notes_json": json.dumps(notes, ensure_ascii=False),
    }
    conn_v14.execute("DELETE FROM subgraph_scope_audit")
    conn_v14.execute("""
        INSERT OR REPLACE INTO subgraph_scope_audit
            (run_id, total_papers, total_linked_refs, configured_max_size,
             recommended_max_size, selected_nodes, selected_edges, node_coverage,
             edge_coverage, edge_density, conclusion_scope, adequacy_label, notes_json)
        VALUES
            (:run_id, :total_papers, :total_linked_refs, :configured_max_size,
             :recommended_max_size, :selected_nodes, :selected_edges, :node_coverage,
             :edge_coverage, :edge_density, :conclusion_scope, :adequacy_label, :notes_json)
    """, audit)
    conn_v14.commit()
    return audit


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_subgraph(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    """执行 Step 4: 子图构建"""
    step_name = "step4_subgraph"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step4 已完成 (%d nodes),跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_main.execute("PRAGMA journal_mode=WAL")

    conn_v14 = get_v14b_conn(db_v14)
    ensure_v14b_text_paper_ids(conn_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 选取种子
    top_k = SUBGRAPH_TOP_KEYSTONE if not limit else min(SUBGRAPH_TOP_KEYSTONE, limit)
    top_f = SUBGRAPH_TOP_FRESH if not limit else min(SUBGRAPH_TOP_FRESH, limit // 3)
    keystone_ids, fresh_ids = select_seed_nodes(conn_main, top_k, top_f)

    seed_ids = keystone_ids | fresh_ids
    logger.info("种子节点总数: %d", len(seed_ids))

    # 扩展邻居
    max_size = SUBGRAPH_MAX_SIZE if not limit else limit
    neighbor_ids = expand_to_neighbors(conn_main, seed_ids, max_size=max_size)

    all_nodes = seed_ids | neighbor_ids
    logger.info("子图节点总数: %d", len(all_nodes))

    # 写入节点
    n_nodes = write_subgraph_nodes(
        conn_main, conn_v14, all_nodes,
        keystone_ids, fresh_ids, neighbor_ids,
    )

    # 选取并写入边
    edges = select_subgraph_edges(conn_main, conn_v14, all_nodes)
    n_edges = write_subgraph_edges(conn_v14, edges)
    scope_audit = evaluate_subgraph_scope(
        conn_main,
        conn_v14,
        configured_max_size=max_size,
        selected_nodes=n_nodes,
        selected_edges=n_edges,
    )

    # 验收检查
    conn_main.close()
    stats = {
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "keystone_nodes": len(keystone_ids),
        "fresh_nodes": len(fresh_ids),
        "neighbor_nodes": len(neighbor_ids),
        "scope_audit": scope_audit,
        "records_n": n_nodes,
    }

    upsert_step_meta(
        conn_v14,
        step_name,
        "done",
        records_n=n_nodes,
        notes=json.dumps(scope_audit, ensure_ascii=False),
    )
    conn_v14.close()

    ck.mark_done(records_n=n_nodes, meta=stats)
    logger.info("Step4 完成: nodes=%d edges=%d", n_nodes, n_edges)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step4_subgraph",
        description="Step 4: 子图构建",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step4_subgraph", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_subgraph(db_main=db_main, db_v14=db_v14, limit=limit, resume=args.resume)


if __name__ == "__main__":
    main()
