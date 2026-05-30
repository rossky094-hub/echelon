"""
Step 8: UMAP-3D 演化树布局

坐标:
  X, Y: UMAP 降维 (abstract embedding 768d)
  Z: (publication_year - 1991) / (2026 - 1991)

节点视觉:
  size: log(cite_count + 1) 归一化
  color: primary_field 映射 (26 色)

输出: subgraph_nodes 表的 umap_x, umap_y, z_year, node_size, color_hex 列

CLI:
    python -m echelon.v14b.step8_layout --help
    python -m echelon.v14b.step8_layout
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    UMAP_N_NEIGHBORS, UMAP_MIN_DIST, UMAP_N_COMPONENTS, UMAP_RANDOM_STATE,
    YEAR_MIN, YEAR_MAX, NODE_SIZE_MIN, NODE_SIZE_MAX,
    VGAE_ABSTRACT_DIM, VGAE_FIELD_DIM,
    LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args, year_to_z

logger = logging.getLogger("echelon.v14b.step8_layout")

# 26 色映射 (HSL 均匀分布)
def field_to_color(field_id: Optional[int]) -> str:
    """将 primary_field_id 映射到十六进制颜色"""
    if field_id is None:
        return "#888888"
    m = re.search(r"\d+", str(field_id))
    if not m:
        return "#888888"
    hue = (int(m.group(0)) * 137.5) % 360  # 黄金角分布
    # HSL(hue, 70%, 55%) → RGB (简化转换)
    h = hue / 360.0
    s = 0.70
    l = 0.55

    def hue2rgb(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = int(255 * hue2rgb(p, q, h + 1/3))
    g = int(255 * hue2rgb(p, q, h))
    b = int(255 * hue2rgb(p, q, h - 1/3))
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# UMAP 降维
# ---------------------------------------------------------------------------

def compute_pca_fallback_layout(features: np.ndarray) -> np.ndarray:
    """Deterministic 2D fallback when UMAP/numba is unavailable.

    UMAP is still the preferred layout because it preserves local semantic
    neighborhoods better.  The fallback keeps the product chain runnable in
    restricted environments where numba cannot create its cache, and it is
    acceptable because Step8 coordinates are a visual projection, not evidence.
    """
    n = int(len(features))
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    if n == 1:
        return np.zeros((1, 2), dtype=np.float32)

    x = np.asarray(features, dtype=np.float32)
    x = np.nan_to_num(x, copy=False)
    x = x - x.mean(axis=0, keepdims=True)
    try:
        _u, _s, vt = np.linalg.svd(x, full_matrices=False)
        coords = x @ vt[:2].T
    except Exception:
        coords = x[:, :2] if x.shape[1] >= 2 else np.column_stack([x[:, 0], np.zeros(n)])
    if coords.shape[1] == 1:
        coords = np.column_stack([coords[:, 0], np.zeros(n)])
    return coords[:, :2].astype(np.float32, copy=False)

def load_subgraph_features(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: list[int],
) -> tuple[np.ndarray, list[dict]]:
    """
    加载子图节点的特征用于 UMAP 降维。

    Returns:
        (feature_matrix, node_meta_list)
        feature_matrix: shape (N, D)
    """
    placeholders = ",".join("?" * len(node_ids))

    # 读取论文元数据
    rows = conn_main.execute(f"""
        SELECT id, publication_year, cited_by_count, primary_field_id, abstract
        FROM papers WHERE id IN ({placeholders})
    """, node_ids).fetchall()
    meta_by_id = {row[0]: dict(row) for row in rows}

    # 尝试读取 embedding
    emb_by_id = {}
    try:
        rows_emb = conn_main.execute(f"""
            SELECT paper_id, embedding_blob
            FROM paper_embeddings
            WHERE paper_id IN ({placeholders})
        """, node_ids).fetchall()
        emb_by_id = {row[0]: row[1] for row in rows_emb}
    except Exception:
        pass

    features = []
    node_meta = []

    for nid in node_ids:
        meta = meta_by_id.get(nid, {})
        node_meta.append(meta)

        # 特征: embedding (768d) 或 TF-IDF 代理
        feat = np.zeros(VGAE_ABSTRACT_DIM, dtype=np.float32)
        if nid in emb_by_id and emb_by_id[nid]:
            try:
                emb = np.frombuffer(emb_by_id[nid], dtype=np.float32)
                min_len = min(len(emb), VGAE_ABSTRACT_DIM)
                feat[:min_len] = emb[:min_len]
            except Exception:
                pass

        # 如果没有 embedding,用年份 + field one-hot 代理
        if feat.sum() == 0:
            year = meta.get("publication_year") or 2010
            feat[0] = (year - 1991) / 35.0
            field_id = meta.get("primary_field_id")
            if field_id is not None:
                m = re.search(r"\d+", str(field_id))
                field_idx = int(m.group(0)) % 64 if m else -1
                if 0 <= field_idx < VGAE_ABSTRACT_DIM:
                    feat[field_idx] = 1.0

        features.append(feat)

    return np.array(features, dtype=np.float32), node_meta


def compute_umap_layout(
    features: np.ndarray,
    n_neighbors: int = UMAP_N_NEIGHBORS,
    min_dist: float = UMAP_MIN_DIST,
    n_components: int = UMAP_N_COMPONENTS,
    random_state: int = UMAP_RANDOM_STATE,
) -> np.ndarray:
    """
    使用 UMAP 降维到 2D。

    Returns:
        shape (N, 2) array of (x, y) coordinates
    """
    try:
        import umap
        reducer = umap.UMAP(
            n_neighbors=n_neighbors,
            min_dist=min_dist,
            n_components=n_components,
            random_state=random_state,
            metric="cosine",
        )
        logger.info("UMAP 降维: input=%s neighbors=%d", features.shape, n_neighbors)
        embedding = reducer.fit_transform(features)
        logger.info("UMAP 降维完成: output=%s", embedding.shape)
        return embedding
    except Exception as exc:
        logger.warning("UMAP 不可用,使用 PCA fallback 布局: %s", exc)
        return compute_pca_fallback_layout(features)


def normalize_xy(coords: np.ndarray) -> np.ndarray:
    """将 UMAP 坐标归一化到 [-1, 1]"""
    for dim in range(coords.shape[1]):
        col = coords[:, dim]
        col_min, col_max = col.min(), col.max()
        if col_max - col_min > 1e-8:
            coords[:, dim] = 2 * (col - col_min) / (col_max - col_min) - 1
    return coords


# ---------------------------------------------------------------------------
# 节点大小计算
# ---------------------------------------------------------------------------

def compute_node_sizes(
    cite_counts: list[int],
    size_min: float = NODE_SIZE_MIN,
    size_max: float = NODE_SIZE_MAX,
) -> list[float]:
    """将 cited_by_count 映射到节点大小"""
    log_cites = [math.log(c + 1) for c in cite_counts]
    max_log = max(log_cites) if log_cites else 1.0
    if max_log == 0:
        max_log = 1.0
    sizes = [
        size_min + (size_max - size_min) * (lc / max_log)
        for lc in log_cites
    ]
    return sizes


# ---------------------------------------------------------------------------
# DB 写入
# ---------------------------------------------------------------------------

def write_layout(
    conn_v14: sqlite3.Connection,
    node_ids: list[int],
    xy_coords: np.ndarray,
    node_meta: list[dict],
    batch_size: int = 500,
) -> int:
    """将布局结果写入 subgraph_nodes 表"""
    cite_counts = [m.get("cited_by_count") or 0 for m in node_meta]
    sizes = compute_node_sizes(cite_counts)

    updates = []
    for i, nid in enumerate(node_ids):
        meta = node_meta[i]
        year = meta.get("publication_year") or 2000
        z = year_to_z(year, YEAR_MIN, YEAR_MAX)
        color = field_to_color(meta.get("primary_field_id"))

        x = float(xy_coords[i, 0])
        y = float(xy_coords[i, 1])

        updates.append((x, y, z, sizes[i], color, nid))

    written = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i: i + batch_size]
        conn_v14.executemany("""
            UPDATE subgraph_nodes
            SET umap_x = ?, umap_y = ?, z_year = ?, node_size = ?, color_hex = ?
            WHERE paper_id = ?
        """, batch)
        conn_v14.commit()
        written += len(batch)

    return written


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_layout(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
    corpus_id: str | None = None,
) -> dict:
    """执行 Step 8: UMAP-3D 布局"""
    step_name = "step8_layout"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step8 已完成 (%d nodes),跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 读取子图节点
    rows = conn_v14.execute("SELECT paper_id FROM subgraph_nodes").fetchall()
    node_ids = [row[0] for row in rows]
    if corpus_id:
        node_ids = [
            pid
            for pid in node_ids
            if conn_main.execute(
                "SELECT 1 FROM temp.v14b_corpus_papers WHERE paper_id = ? LIMIT 1",
                (pid,),
            ).fetchone()
        ]
    if limit:
        node_ids = node_ids[:limit]
    logger.info("布局节点数: %d", len(node_ids))

    # 加载特征
    features, node_meta = load_subgraph_features(conn_main, conn_v14, node_ids)

    # UMAP 降维
    xy_coords = compute_umap_layout(features)
    xy_coords = normalize_xy(xy_coords)

    # 写入布局
    n_written = write_layout(conn_v14, node_ids, xy_coords, node_meta)
    upsert_step_meta(conn_v14, step_name, "done", records_n=n_written)

    conn_main.close()
    conn_v14.close()

    stats = {
        "records_n": n_written,
        "n_nodes": len(node_ids),
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(node_ids),
    }
    ck.mark_done(records_n=n_written, meta=stats)
    logger.info("Step8 完成: %d nodes laid out", n_written)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step8_layout",
        description="Step 8: UMAP-3D 布局",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step8_layout", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_layout(
        db_main=db_main,
        db_v14=db_v14,
        limit=limit,
        resume=args.resume,
        corpus_id=args.corpus_id,
    )


if __name__ == "__main__":
    main()
