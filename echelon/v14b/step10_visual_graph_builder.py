"""Step 10: build the V14B visual graph product layer.

This step materializes the data model needed by a Nature-style 2.5D
interactive evolution tree. It does not render the frontend. Instead it writes
queryable tables that a WebGL viewer, search endpoint, or recommendation API
can consume.

Layers:
  - citation: true time-forward citation DAG, older paper -> newer paper
  - cocitation: co-cited / co-referenced topic structure
  - semantic: embedding kNN links for search and local similarity
  - future: VGAE + limitation/fusion-derived future growth links

Visual model:
  - x/y: semantic-community layout
  - z: publication year
  - main path: high-emphasis edges
  - branch lineage: cluster-level parent -> child growth explanation
  - LOD tiles: overview, cluster, node, and local-edge levels
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import networkx as nx
import numpy as np

from echelon.v14b.config import DB_MAIN, DB_V14, YEAR_MIN, YEAR_MAX
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.id_normalization import (
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)
from echelon.v14b.utils import add_common_args, setup_logging, table_columns

logger = logging.getLogger("echelon.v14b.step10_visual_graph_builder")


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "its", "of", "on", "or", "that", "the", "their",
    "this", "to", "using", "via", "we", "with", "within", "without",
    "optical", "optic", "optics", "study", "studies", "paper", "based",
    "new", "show", "shows", "demonstrate", "demonstrates",
}


@dataclass
class VisualConfig:
    semantic_k: int = 8
    cocitation_max_refs_per_paper: int = 80
    cocitation_min_weight: int = 2
    cocitation_top_per_node: int = 12
    max_cocitation_edges: int = 250_000
    max_semantic_edges: int = 450_000
    max_louvain_edges: int = 500_000
    tile_top_nodes: int = 80
    recommendation_top_k: int = 200
    use_umap: bool = True
    allow_legacy_ids: bool = False

    @classmethod
    def from_env(cls) -> "VisualConfig":
        import os

        def i(name: str, default: int) -> int:
            return int(os.environ.get(name, str(default)))

        return cls(
            semantic_k=i("V14B_VISUAL_SEMANTIC_K", 8),
            cocitation_max_refs_per_paper=i("V14B_VISUAL_COCITE_MAX_REFS", 80),
            cocitation_min_weight=i("V14B_VISUAL_COCITE_MIN_WEIGHT", 2),
            cocitation_top_per_node=i("V14B_VISUAL_COCITE_TOP_PER_NODE", 12),
            max_cocitation_edges=i("V14B_VISUAL_MAX_COCITE_EDGES", 250_000),
            max_semantic_edges=i("V14B_VISUAL_MAX_SEMANTIC_EDGES", 450_000),
            max_louvain_edges=i("V14B_VISUAL_MAX_LOUVAIN_EDGES", 500_000),
            tile_top_nodes=i("V14B_VISUAL_TILE_TOP_NODES", 80),
            recommendation_top_k=i("V14B_VISUAL_RECOMMEND_TOP_K", 200),
            use_umap=os.environ.get("V14B_VISUAL_USE_UMAP", "true").lower()
            in ("1", "true", "yes"),
            allow_legacy_ids=os.environ.get("V14B_VISUAL_ALLOW_LEGACY_IDS", "false").lower()
            in ("1", "true", "yes"),
        )


def jdumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def parse_year(row: sqlite3.Row | dict) -> int:
    year = row.get("publication_year") if isinstance(row, dict) else row["publication_year"]
    if year:
        try:
            return int(year)
        except Exception:
            pass
    date_value = row.get("publication_date") if isinstance(row, dict) else row["publication_date"]
    if date_value:
        m = re.match(r"^(\d{4})", str(date_value))
        if m:
            return int(m.group(1))
    return 2000


def year_to_z(year: int) -> float:
    return clamp01((year - YEAR_MIN) / max(1, YEAR_MAX - YEAR_MIN))


def norm_array(arr: np.ndarray) -> np.ndarray:
    if arr.size == 0:
        return arr
    out = arr.astype(np.float32, copy=True)
    for dim in range(out.shape[1]):
        col = out[:, dim]
        lo = float(np.nanmin(col))
        hi = float(np.nanmax(col))
        if hi - lo > 1e-8:
            out[:, dim] = 2.0 * (col - lo) / (hi - lo) - 1.0
        else:
            out[:, dim] = 0.0
    return out


def ensure_visual_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS visual_nodes (
            paper_id TEXT PRIMARY KEY,
            cluster_id TEXT,
            branch_id TEXT,
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,
            publication_year INTEGER,
            node_size REAL,
            color_hex TEXT,
            visual_role TEXT,
            uncertainty_score REAL,
            flags_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_visual_nodes_cluster
            ON visual_nodes(cluster_id);
        CREATE INDEX IF NOT EXISTS idx_visual_nodes_branch
            ON visual_nodes(branch_id);
        CREATE INDEX IF NOT EXISTS idx_visual_nodes_year
            ON visual_nodes(publication_year);

        CREATE TABLE IF NOT EXISTS visual_edges (
            edge_id TEXT PRIMARY KEY,
            source_paper_id TEXT NOT NULL,
            target_paper_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            layer TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            confidence REAL,
            is_directed INTEGER NOT NULL DEFAULT 1,
            is_main_path INTEGER NOT NULL DEFAULT 0,
            lod_min INTEGER NOT NULL DEFAULT 2,
            style_json TEXT,
            evidence_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_visual_edges_source
            ON visual_edges(source_paper_id);
        CREATE INDEX IF NOT EXISTS idx_visual_edges_target
            ON visual_edges(target_paper_id);
        CREATE INDEX IF NOT EXISTS idx_visual_edges_layer_lod
            ON visual_edges(layer, lod_min);

        CREATE TABLE IF NOT EXISTS visual_clusters (
            cluster_id TEXT PRIMARY KEY,
            branch_id TEXT,
            label TEXT,
            n_nodes INTEGER,
            year_start INTEGER,
            year_end INTEGER,
            centroid_x REAL,
            centroid_y REAL,
            centroid_z REAL,
            top_terms_json TEXT,
            representative_papers_json TEXT,
            evidence_json TEXT
        );

        CREATE TABLE IF NOT EXISTS branch_lineages (
            branch_id TEXT PRIMARY KEY,
            parent_branch_id TEXT,
            split_year INTEGER,
            strength REAL,
            why_json TEXT,
            future_json TEXT
        );

        CREATE TABLE IF NOT EXISTS visual_tiles (
            tile_id TEXT PRIMARY KEY,
            lod_level INTEGER NOT NULL,
            cluster_id TEXT,
            year_start INTEGER,
            year_end INTEGER,
            bounds_json TEXT,
            node_count INTEGER,
            edge_count INTEGER,
            payload_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_visual_tiles_lod
            ON visual_tiles(lod_level, cluster_id);

        CREATE TABLE IF NOT EXISTS visual_story_steps (
            story_step_id TEXT PRIMARY KEY,
            order_idx INTEGER NOT NULL,
            year_start INTEGER,
            year_end INTEGER,
            title TEXT,
            narrative TEXT,
            focus_cluster_id TEXT,
            focus_papers_json TEXT,
            evidence_json TEXT
        );

        CREATE TABLE IF NOT EXISTS visual_paper_details (
            paper_id TEXT PRIMARY KEY,
            ids_json TEXT,
            metadata_json TEXT,
            abstract TEXT,
            sections_json TEXT,
            limitations_json TEXT,
            recommendation_json TEXT
        );

        CREATE TABLE IF NOT EXISTS visual_recommendations (
            mode TEXT NOT NULL,
            rank INTEGER NOT NULL,
            paper_id TEXT NOT NULL,
            score REAL NOT NULL,
            reason_json TEXT,
            PRIMARY KEY(mode, rank)
        );
        """
    )
    try:
        conn.execute("DROP TABLE IF EXISTS visual_search_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE visual_search_fts USING fts5(
                paper_id UNINDEXED,
                title,
                abstract,
                sections,
                limitations,
                branch_label,
                topics
            )
            """
        )
    except sqlite3.OperationalError as exc:
        logger.warning("FTS5 unavailable, visual_search_fts skipped: %s", exc)
    conn.commit()


def reset_visual_tables(conn: sqlite3.Connection) -> None:
    for table in (
        "visual_nodes",
        "visual_edges",
        "visual_clusters",
        "branch_lineages",
        "visual_tiles",
        "visual_story_steps",
        "visual_paper_details",
        "visual_recommendations",
    ):
        conn.execute(f"DELETE FROM {table}")
    try:
        conn.execute("DELETE FROM visual_search_fts")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def validate_graph_ready_schema(
    conn: sqlite3.Connection,
    *,
    allow_legacy_ids: bool = False,
) -> dict:
    """Fail fast unless the library has the repaired V14B provider-ID schema.

    Step10 is a materialized product layer. Running it against the transitional
    mixed-ID database would create a visually coherent but scientifically
    ambiguous graph. The normal path is therefore strict: run Step0 ID repair
    before visual graph export. The legacy escape hatch is only for diagnostics
    and small smoke tests.
    """
    paper_cols = table_columns(conn, "papers")
    ref_cols = table_columns(conn, "paper_references")
    errors: list[str] = []

    if "s2_paper_id" not in paper_cols:
        errors.append("papers.s2_paper_id missing; run provider ID repair first")
    if "cited_paper_id_provider" not in ref_cols or "cited_paper_id_norm" not in ref_cols:
        errors.append(
            "paper_references provider columns missing; run provider ID repair first"
        )

    invalid_openalex_rows = conn.execute(
        """
        SELECT id, openalex_id
        FROM papers
        WHERE openalex_id IS NOT NULL
          AND length(trim(openalex_id)) > 0
        LIMIT 1000000
        """
    ).fetchall()
    invalid_openalex = [
        (row[0], row[1])
        for row in invalid_openalex_rows
        if normalize_openalex_work_id(row[1]) is None
    ]
    if invalid_openalex and not allow_legacy_ids:
        sample = ", ".join(f"{pid}:{oid}" for pid, oid in invalid_openalex[:5])
        errors.append(
            "legacy/non-OpenAlex values remain in papers.openalex_id "
            f"(n={len(invalid_openalex)}, sample={sample})"
        )

    missing_ref_norm = 0
    if {"cited_paper_id_provider", "cited_paper_id_norm"}.issubset(ref_cols):
        missing_ref_norm = conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_references
            WHERE cited_paper_id_external IS NOT NULL
              AND (
                cited_paper_id_provider IS NULL
                OR cited_paper_id_norm IS NULL
                OR cited_paper_id_provider = ''
                OR cited_paper_id_norm = ''
              )
            """
        ).fetchone()[0]
        if missing_ref_norm and not allow_legacy_ids:
            errors.append(
                "unnormalized reference provider IDs remain "
                f"(n={missing_ref_norm}); run provider ID repair first"
            )

    stats = {
        "has_s2_paper_id": "s2_paper_id" in paper_cols,
        "has_reference_provider_columns": {
            "cited_paper_id_provider",
            "cited_paper_id_norm",
        }.issubset(ref_cols),
        "invalid_openalex_id_count": len(invalid_openalex),
        "missing_reference_norm_count": int(missing_ref_norm),
        "allow_legacy_ids": allow_legacy_ids,
    }
    if errors:
        raise RuntimeError(
            "Step10 visual graph builder requires repaired enrich/ID schema. "
            + " | ".join(errors)
            + ". Normal fix: make id-repair, then rerun visual-graph. "
            + "Diagnostic override only: V14B_VISUAL_ALLOW_LEGACY_IDS=1."
        )
    logger.info("visual graph readiness check passed: %s", stats)
    return stats


def load_papers(conn: sqlite3.Connection, limit: Optional[int]) -> list[dict]:
    cols = table_columns(conn, "papers")
    provider_id_cols = [
        "s2_paper_id",
        "s2_corpus_id",
        "pmid",
    ]
    optional_cols = [
        "c_bridging_centrality",
        "c_recent_burst",
        "c_cd_subdomain",
        "c_semantic_outlier",
        "c_breakthrough_lang",
        "c_mechanism_novelty",
    ]
    optional_select = [
        f"p.{c}" if c in cols else f"NULL AS {c}" for c in optional_cols
    ]
    provider_id_select = [
        f"p.{c}" if c in cols else f"NULL AS {c}" for c in provider_id_cols
    ]
    q = f"""
        SELECT
            p.id, p.openalex_id, p.doi, p.arxiv_id, p.title, p.abstract,
            p.publication_date, p.publication_year, p.cited_by_count,
            p.primary_domain_id, p.primary_field_id, p.primary_subfield_id,
            p.primary_topic_id, p.venue_id, p.source_provider,
            p.openalex_enriched, p.keystone_score_v14, p.lifecycle_v14,
            {", ".join(provider_id_select + optional_select)}
        FROM papers p
        ORDER BY COALESCE(p.publication_year, CAST(substr(p.publication_date, 1, 4) AS INTEGER), 2000), p.id
    """
    if limit:
        q += " LIMIT ?"
        rows = conn.execute(q, (limit,)).fetchall()
    else:
        rows = conn.execute(q).fetchall()
    papers = [dict(r) for r in rows]
    for p in papers:
        p["year"] = parse_year(p)
        # Keep provider IDs semantically separated. Historical runs sometimes
        # stored Semantic Scholar paper IDs in openalex_id; Step0 repair moves
        # them to s2_paper_id, but Step10 stays defensive so future visual
        # exports do not reintroduce the mixed-ID ambiguity.
        openalex_work_id = normalize_openalex_work_id(p.get("openalex_id"))
        legacy_s2_id = None
        if p.get("openalex_id") and not openalex_work_id:
            legacy_s2_id = normalize_s2_paper_id(p.get("openalex_id"))
        p["openalex_work_id"] = openalex_work_id
        p["s2_paper_id_norm"] = normalize_s2_paper_id(p.get("s2_paper_id")) or legacy_s2_id
        p["legacy_openalex_id_value"] = (
            p.get("openalex_id") if p.get("openalex_id") and not openalex_work_id else None
        )
    logger.info("visual papers loaded: %d", len(papers))
    return papers


def load_embeddings(conn: sqlite3.Connection, paper_ids: list[str]) -> tuple[dict[str, np.ndarray], Optional[np.ndarray]]:
    if not paper_ids:
        return {}, None
    table_exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='paper_embeddings'"
    ).fetchone()[0]
    if not table_exists:
        return {}, None
    placeholders = ",".join("?" * len(paper_ids))
    rows = conn.execute(
        f"""
        SELECT paper_id, embedding_blob, embedding_dim
        FROM paper_embeddings
        WHERE paper_id IN ({placeholders})
        """,
        paper_ids,
    ).fetchall()
    emb_by_id: dict[str, np.ndarray] = {}
    dim = None
    for row in rows:
        blob = row["embedding_blob"]
        if not blob:
            continue
        arr = np.frombuffer(blob, dtype=np.float32)
        if arr.size == 0:
            continue
        dim = dim or int(row["embedding_dim"] or arr.size)
        if arr.size != dim:
            arr = arr[:dim] if arr.size > dim else np.pad(arr, (0, dim - arr.size))
        emb_by_id[row["paper_id"]] = arr.astype(np.float32, copy=False)
    if not emb_by_id or dim is None:
        return emb_by_id, None
    matrix = np.zeros((len(paper_ids), dim), dtype=np.float32)
    for i, pid in enumerate(paper_ids):
        arr = emb_by_id.get(pid)
        if arr is not None:
            matrix[i] = arr
    logger.info("visual embeddings loaded: %d/%d dim=%d", len(emb_by_id), len(paper_ids), dim)
    return emb_by_id, matrix


def build_text_feature_matrix(papers: list[dict]) -> np.ndarray:
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    texts = [f"{p.get('title') or ''}\n{p.get('abstract') or ''}"[:6000] for p in papers]
    tfidf = TfidfVectorizer(
        max_features=4096,
        min_df=1 if len(texts) < 20 else 2,
        max_df=0.85,
        stop_words="english",
        ngram_range=(1, 2),
    )
    try:
        x = tfidf.fit_transform(texts)
    except ValueError:
        return np.zeros((len(papers), 2), dtype=np.float32)
    if x.shape[0] < 3 or x.shape[1] < 2:
        return np.zeros((len(papers), 2), dtype=np.float32)
    n_components = min(64, x.shape[1] - 1, x.shape[0] - 1)
    svd = TruncatedSVD(n_components=n_components, random_state=42)
    features = svd.fit_transform(x).astype(np.float32)
    return normalize(features).astype(np.float32)


def compute_xy(features: np.ndarray, cfg: VisualConfig) -> np.ndarray:
    if len(features) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    if features.shape[1] == 2:
        return norm_array(features[:, :2])
    if cfg.use_umap and len(features) >= 20:
        try:
            import umap

            reducer = umap.UMAP(
                n_neighbors=20,
                min_dist=0.05,
                n_components=2,
                metric="cosine",
                random_state=42,
                low_memory=True,
            )
            logger.info("visual UMAP layout: input=%s", features.shape)
            return norm_array(reducer.fit_transform(features))
        except Exception as exc:
            logger.warning("visual UMAP fallback to SVD/PCA: %s", exc)
    from sklearn.decomposition import TruncatedSVD

    svd = TruncatedSVD(n_components=2, random_state=42)
    return norm_array(svd.fit_transform(features))


def load_citation_edges(conn: sqlite3.Connection, allowed: set[str]) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT citing_paper_id, cited_paper_id_internal
        FROM paper_references
        WHERE cited_paper_id_internal IS NOT NULL
        """
    ).fetchall()
    edges = []
    for row in rows:
        citing = row["citing_paper_id"]
        cited = row["cited_paper_id_internal"]
        if citing in allowed and cited in allowed and citing != cited:
            edges.append((cited, citing))
    logger.info("visual citation DAG edges: %d", len(edges))
    return edges


def load_main_path_edges(conn_v14: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    try:
        cols = table_columns(conn_v14, "main_path_edges")
        src_expr = "source_paper_id" if "source_paper_id" in cols else "citing_id"
        dst_expr = "target_paper_id" if "target_paper_id" in cols else "cited_id"
        rows = conn_v14.execute(
            f"""
            SELECT {src_expr} AS source_paper_id,
                   {dst_expr} AS target_paper_id,
                   citing_id,
                   cited_id,
                   spc,
                   main_path_weight,
                   is_main_path
            FROM main_path_edges
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for r in rows:
        out[(r["source_paper_id"], r["target_paper_id"])] = dict(r)
    return out


def build_cocitation_edges(
    conn: sqlite3.Connection,
    allowed: set[str],
    cfg: VisualConfig,
) -> list[tuple[str, str, int]]:
    rows = conn.execute(
        """
        SELECT citing_paper_id, cited_paper_id_internal
        FROM paper_references
        WHERE cited_paper_id_internal IS NOT NULL
        ORDER BY citing_paper_id
        """
    ).fetchall()
    refs_by_citing: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        citing = row["citing_paper_id"]
        cited = row["cited_paper_id_internal"]
        if citing in allowed and cited in allowed and cited != citing:
            refs_by_citing[citing].append(cited)

    pair_counts: Counter[tuple[str, str]] = Counter()
    for refs in refs_by_citing.values():
        refs = sorted(set(refs))
        if len(refs) < 2:
            continue
        if len(refs) > cfg.cocitation_max_refs_per_paper:
            refs = refs[: cfg.cocitation_max_refs_per_paper]
        for a, b in itertools.combinations(refs, 2):
            pair_counts[(a, b)] += 1

    by_node: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for (a, b), w in pair_counts.items():
        if w >= cfg.cocitation_min_weight:
            by_node[a].append((a, b, w))
            by_node[b].append((a, b, w))

    selected: dict[tuple[str, str], int] = {}
    for edges in by_node.values():
        for a, b, w in sorted(edges, key=lambda x: x[2], reverse=True)[: cfg.cocitation_top_per_node]:
            selected[(a, b)] = max(selected.get((a, b), 0), w)

    out = [(a, b, w) for (a, b), w in selected.items()]
    out.sort(key=lambda x: x[2], reverse=True)
    out = out[: cfg.max_cocitation_edges]
    logger.info("visual cocitation/topic edges: %d", len(out))
    return out


def build_semantic_edges(
    paper_ids: list[str],
    features: np.ndarray,
    cfg: VisualConfig,
) -> list[tuple[str, str, float]]:
    if len(paper_ids) < 3 or features.size == 0:
        return []

    k = min(cfg.semantic_k + 1, len(paper_ids))
    edges: dict[tuple[str, str], float] = {}
    try:
        import hnswlib

        dim = features.shape[1]
        index = hnswlib.Index(space="cosine", dim=dim)
        index.init_index(max_elements=len(paper_ids), ef_construction=160, M=32)
        index.add_items(features.astype(np.float32), np.arange(len(paper_ids)))
        index.set_ef(max(64, k * 4))
        labels, distances = index.knn_query(features.astype(np.float32), k=k)
        for i, row in enumerate(labels):
            for j, dist in zip(row[1:], distances[i][1:]):
                a, b = paper_ids[i], paper_ids[int(j)]
                if a == b:
                    continue
                key = tuple(sorted((a, b)))
                sim = 1.0 - float(dist)
                edges[key] = max(edges.get(key, 0.0), sim)
    except Exception:
        from sklearn.neighbors import NearestNeighbors

        # Exact kNN is expensive in 768D. If embeddings are high-dimensional,
        # use the already reduced feature projection supplied by the caller.
        nbrs = NearestNeighbors(n_neighbors=k, metric="cosine")
        nbrs.fit(features)
        distances, indices = nbrs.kneighbors(features)
        for i, row in enumerate(indices):
            for j, dist in zip(row[1:], distances[i][1:]):
                a, b = paper_ids[i], paper_ids[int(j)]
                if a == b:
                    continue
                key = tuple(sorted((a, b)))
                sim = 1.0 - float(dist)
                edges[key] = max(edges.get(key, 0.0), sim)

    out = [(a, b, w) for (a, b), w in edges.items()]
    out.sort(key=lambda x: x[2], reverse=True)
    out = out[: cfg.max_semantic_edges]
    logger.info("visual semantic kNN edges: %d", len(out))
    return out


def detect_clusters(
    paper_ids: list[str],
    citation_edges: list[tuple[str, str]],
    cocitation_edges: list[tuple[str, str, int]],
    semantic_edges: list[tuple[str, str, float]],
    cfg: VisualConfig,
) -> dict[str, str]:
    graph = nx.Graph()
    graph.add_nodes_from(paper_ids)
    for a, b in citation_edges[: cfg.max_louvain_edges // 3]:
        graph.add_edge(a, b, weight=graph.get_edge_data(a, b, {}).get("weight", 0.0) + 1.0)
    for a, b, w in cocitation_edges[: cfg.max_louvain_edges // 3]:
        graph.add_edge(a, b, weight=graph.get_edge_data(a, b, {}).get("weight", 0.0) + math.log1p(w))
    for a, b, w in semantic_edges[: cfg.max_louvain_edges // 3]:
        graph.add_edge(a, b, weight=graph.get_edge_data(a, b, {}).get("weight", 0.0) + max(w, 0.0))

    try:
        communities = nx.algorithms.community.louvain_communities(
            graph, weight="weight", resolution=1.05, seed=42
        )
    except Exception as exc:
        logger.warning("louvain fallback to connected components: %s", exc)
        communities = [set(c) for c in nx.connected_components(graph)]

    communities = sorted(communities, key=len, reverse=True)
    assignment = {}
    for idx, comm in enumerate(communities):
        cid = f"C{idx:04d}"
        for pid in comm:
            assignment[pid] = cid
    logger.info("visual clusters detected: %d", len(communities))
    return assignment


def tokens(text: str) -> list[str]:
    out = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()):
        if tok not in STOPWORDS and not tok.isdigit():
            out.append(tok)
    return out


def cluster_terms(papers: list[dict], paper_ids: Iterable[str]) -> list[str]:
    by_id = {p["id"]: p for p in papers}
    counts: Counter[str] = Counter()
    for pid in paper_ids:
        p = by_id.get(pid)
        if not p:
            continue
        counts.update(tokens(f"{p.get('title') or ''} {p.get('abstract') or ''}"[:1200]))
    return [term for term, _ in counts.most_common(8)]


def color_for_cluster(cluster_id: str) -> str:
    m = re.search(r"\d+", cluster_id or "")
    idx = int(m.group(0)) if m else 0
    hue = (idx * 137.508) % 360
    c = 0.72
    x = c * (1 - abs((hue / 60) % 2 - 1))
    if hue < 60:
        r, g, b = c, x, 0
    elif hue < 120:
        r, g, b = x, c, 0
    elif hue < 180:
        r, g, b = 0, c, x
    elif hue < 240:
        r, g, b = 0, x, c
    elif hue < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    m0 = 0.22
    return f"#{int((r + m0) * 255):02x}{int((g + m0) * 255):02x}{int((b + m0) * 255):02x}"


def build_cluster_records(
    papers: list[dict],
    coords: np.ndarray,
    assignment: dict[str, str],
) -> tuple[list[dict], dict[str, list[str]]]:
    ids = [p["id"] for p in papers]
    idx = {pid: i for i, pid in enumerate(ids)}
    by_cluster: dict[str, list[str]] = defaultdict(list)
    for pid, cid in assignment.items():
        by_cluster[cid].append(pid)

    records = []
    for cid, node_ids in sorted(by_cluster.items()):
        indices = [idx[pid] for pid in node_ids if pid in idx]
        years = [papers[i]["year"] for i in indices]
        cx = float(np.mean(coords[indices, 0])) if indices else 0.0
        cy = float(np.mean(coords[indices, 1])) if indices else 0.0
        cz = float(np.mean([year_to_z(y) for y in years])) if years else 0.0
        terms = cluster_terms(papers, node_ids)
        ranked = sorted(
            (papers[i] for i in indices),
            key=lambda p: ((p.get("keystone_score_v14") or 0), (p.get("cited_by_count") or 0)),
            reverse=True,
        )
        reps = [
            {
                "paper_id": p["id"],
                "title": p.get("title"),
                "year": p.get("year"),
                "score": p.get("keystone_score_v14"),
            }
            for p in ranked[:10]
        ]
        records.append(
            {
                "cluster_id": cid,
                "branch_id": f"B{cid[1:]}",
                "label": ", ".join(terms[:3]) if terms else cid,
                "n_nodes": len(node_ids),
                "year_start": min(years) if years else None,
                "year_end": max(years) if years else None,
                "centroid_x": cx,
                "centroid_y": cy,
                "centroid_z": cz,
                "top_terms_json": jdumps(terms),
                "representative_papers_json": jdumps(reps),
                "evidence_json": jdumps(
                    {
                        "purpose": "topic branch from citation+cocitation+semantic community detection",
                        "representative_rule": "top keystone_score_v14 then citations",
                    }
                ),
            }
        )
    return records, by_cluster


def build_branch_lineages(
    papers: list[dict],
    assignment: dict[str, str],
    citation_edges: list[tuple[str, str]],
    predicted_future: list[dict],
) -> list[dict]:
    by_id = {p["id"]: p for p in papers}
    influence: Counter[tuple[str, str]] = Counter()
    drivers: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for src, dst in citation_edges:
        c_src = assignment.get(src)
        c_dst = assignment.get(dst)
        if not c_src or not c_dst or c_src == c_dst:
            continue
        y_src = by_id.get(src, {}).get("year", 2000)
        y_dst = by_id.get(dst, {}).get("year", 2000)
        if y_src <= y_dst:
            influence[(c_src, c_dst)] += 1
            drivers[(c_src, c_dst)][src] += 1

    by_child: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (parent, child), w in influence.items():
        by_child[child].append((parent, w))

    child_future: dict[str, list[dict]] = defaultdict(list)
    for pred in predicted_future:
        cid = assignment.get(pred.get("dst_paper_id")) or assignment.get(pred.get("src_paper_id"))
        if cid:
            child_future[cid].append(pred)

    all_clusters = set(assignment.values())
    records = []
    for cid in sorted(all_clusters):
        branch_id = f"B{cid[1:]}"
        parent_id = None
        strength = 0.0
        top_parent = None
        if by_child.get(cid):
            top_parent = max(by_child[cid], key=lambda x: x[1])
            parent_id = f"B{top_parent[0][1:]}"
            total = sum(w for _, w in by_child[cid])
            strength = top_parent[1] / max(total, 1)
        cluster_papers = [p for p in papers if assignment.get(p["id"]) == cid]
        years = sorted(p["year"] for p in cluster_papers)
        split_year = years[max(0, min(len(years) - 1, int(len(years) * 0.10)))] if years else None
        driver_ids = []
        if top_parent:
            driver_ids = [pid for pid, _ in drivers[(top_parent[0], cid)].most_common(8)]
        records.append(
            {
                "branch_id": branch_id,
                "parent_branch_id": parent_id,
                "split_year": split_year,
                "strength": strength,
                "why_json": jdumps(
                    {
                        "parent_cluster": top_parent[0] if top_parent else None,
                        "parent_citation_support": top_parent[1] if top_parent else 0,
                        "driver_papers": driver_ids,
                        "interpretation": "Parent branch chosen by strongest time-forward cross-cluster citation flow.",
                    }
                ),
                "future_json": jdumps(
                    {
                        "predicted_edges": child_future.get(cid, [])[:20],
                        "interpretation": "Future growth candidates from VGAE and fusion evidence.",
                    }
                ),
            }
        )
    return records


def load_future_predictions(conn_v14: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn_v14.execute(
            """
            SELECT src_paper_id, dst_paper_id, predicted_prob, src_year, dst_year, is_cross_field
            FROM predicted_future_edges
            ORDER BY predicted_prob DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def load_unresolved_limitations(conn_v14: sqlite3.Connection) -> dict[str, list[dict]]:
    try:
        cols = table_columns(conn_v14, "limitation_atoms")
        evidence_cols = ""
        if {"evidence_source", "evidence_quality", "evidence_weight"} <= cols:
            evidence_cols = ", a.evidence_source, a.evidence_quality, a.evidence_weight"
        rows = conn_v14.execute(
            f"""
            SELECT a.atom_id, a.paper_id, a.description, a.keyword, a.severity,
                   COUNT(r.atom_id) AS n_resolutions
                   {evidence_cols}
            FROM limitation_atoms a
            LEFT JOIN limitation_resolutions r
              ON r.atom_id = a.atom_id AND r.confidence > 0.6
            GROUP BY a.atom_id
            HAVING n_resolutions = 0
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["paper_id"]].append(dict(r))
    return out


def load_sections(conn: sqlite3.Connection, paper_ids: list[str]) -> dict[str, list[dict]]:
    table_names = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    section_table = None
    for candidate in ("paper_sections", "scibot_sections", "paper_fulltext_sections"):
        if candidate in table_names:
            section_table = candidate
            break
    if not section_table or not paper_ids:
        return {}
    ph = ",".join("?" * len(paper_ids))
    try:
        rows = conn.execute(
            f"""
            SELECT paper_id, section_name, section_text
            FROM {section_table}
            WHERE paper_id IN ({ph})
            """,
            paper_ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("visual sections skipped: %s", exc)
        return {}
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["paper_id"]].append(
            {"section_name": r["section_name"], "section_text": r["section_text"]}
        )
    return out


def uncertainty_score(p: dict, has_embedding: bool, ref_count: int, linked_count: int) -> float:
    penalties = 0.0
    if not p.get("abstract"):
        penalties += 0.20
    if not p.get("primary_field_id"):
        penalties += 0.20
    if not has_embedding:
        penalties += 0.20
    if not p.get("openalex_enriched"):
        penalties += 0.15
    if ref_count == 0:
        penalties += 0.15
    elif linked_count / max(ref_count, 1) < 0.2:
        penalties += 0.10
    return clamp01(penalties)


def write_visual_nodes(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    papers: list[dict],
    coords: np.ndarray,
    assignment: dict[str, str],
    emb_by_id: dict[str, np.ndarray],
    main_nodes: set[str],
    future_nodes: set[str],
    limitations: dict[str, list[dict]],
) -> None:
    ids = [p["id"] for p in papers]
    ref_counts = Counter()
    linked_counts = Counter()
    for r in conn_main.execute(
        """
        SELECT citing_paper_id,
               COUNT(*) AS refs,
               SUM(CASE WHEN cited_paper_id_internal IS NOT NULL THEN 1 ELSE 0 END) AS linked_refs
        FROM paper_references
        GROUP BY citing_paper_id
        """
    ):
        ref_counts[r["citing_paper_id"]] = int(r["refs"] or 0)
        linked_counts[r["citing_paper_id"]] = int(r["linked_refs"] or 0)

    max_cite_log = max([math.log((p.get("cited_by_count") or 0) + 1) for p in papers] or [1.0])
    rows = []
    for i, p in enumerate(papers):
        pid = p["id"]
        cid = assignment.get(pid, "C9999")
        lims = limitations.get(pid, [])
        lim_weights = [float(l.get("evidence_weight") or 0.35) for l in lims]
        lim_qualities = sorted({l.get("evidence_quality") or "unknown" for l in lims})
        flags = {
            "is_main_path": pid in main_nodes,
            "is_future_anchor": pid in future_nodes,
            "has_unresolved_limitation": pid in limitations,
            "limitation_evidence_quality": ",".join(lim_qualities) if lim_qualities else None,
            "limitation_evidence_weight": sum(lim_weights) / max(1, len(lim_weights)) if lim_weights else None,
            "is_keystone": (p.get("keystone_score_v14") or 0) >= 0.75,
            "lifecycle": p.get("lifecycle_v14"),
        }
        role = "paper"
        if flags["is_main_path"]:
            role = "main_path"
        elif flags["is_future_anchor"]:
            role = "future_anchor"
        elif flags["has_unresolved_limitation"]:
            role = "limitation_bottleneck"
        cite_log = math.log((p.get("cited_by_count") or 0) + 1)
        size = 2.0 + 16.0 * (cite_log / max(max_cite_log, 1.0))
        rows.append(
            (
                pid,
                cid,
                f"B{cid[1:]}" if cid.startswith("C") else cid,
                float(coords[i, 0]),
                float(coords[i, 1]),
                year_to_z(p["year"]),
                p["year"],
                size,
                color_for_cluster(cid),
                role,
                uncertainty_score(
                    p, pid in emb_by_id, ref_counts[pid], linked_counts[pid]
                ),
                jdumps(flags),
            )
        )
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_nodes
            (paper_id, cluster_id, branch_id, x, y, z, publication_year,
             node_size, color_hex, visual_role, uncertainty_score, flags_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn_v14.commit()
    logger.info("visual_nodes written: %d", len(rows))


def edge_id(edge_type: str, src: str, dst: str) -> str:
    return f"{edge_type}:{src}:{dst}"


def write_visual_edges(
    conn_v14: sqlite3.Connection,
    citation_edges: list[tuple[str, str]],
    main_edges: dict[tuple[str, str], dict],
    cocitation_edges: list[tuple[str, str, int]],
    semantic_edges: list[tuple[str, str, float]],
    future_predictions: list[dict],
) -> None:
    rows_by_id = {}

    def add_row(row: tuple) -> None:
        edge_key = row[0]
        existing = rows_by_id.get(edge_key)
        if existing is None or (row[8] and not existing[8]):
            rows_by_id[edge_key] = row

    for src, dst in citation_edges:
        m = main_edges.get((src, dst)) or main_edges.get((dst, src))
        is_main = int(bool(m and m.get("is_main_path")))
        weight = float(m.get("main_path_weight") if m else 1.0)
        add_row(
            (
                edge_id("citation", src, dst),
                src,
                dst,
                "main_path" if is_main else "citation",
                "citation",
                weight,
                1.0,
                1,
                is_main,
                0 if is_main else 3,
                jdumps({"stroke": "main" if is_main else "faint", "dash": False}),
                jdumps({"spc": m.get("spc") if m else None, "why": "true linked citation"}),
            )
        )
    for src, dst, w in cocitation_edges:
        add_row(
            (
                edge_id("cocitation", src, dst),
                src,
                dst,
                "cocitation",
                "topic",
                float(math.log1p(w)),
                min(1.0, w / 10.0),
                0,
                0,
                1,
                jdumps({"stroke": "topic", "dash": False}),
                jdumps({"co_cited_count": w, "why": "papers co-cited/co-referenced by library papers"}),
            )
        )
    for src, dst, sim in semantic_edges:
        add_row(
            (
                edge_id("semantic", src, dst),
                src,
                dst,
                "semantic_similarity",
                "semantic",
                float(max(sim, 0.0)),
                float(clamp01(sim)),
                0,
                0,
                2,
                jdumps({"stroke": "semantic", "dash": False}),
                jdumps({"similarity": sim, "why": "embedding nearest neighbor"}),
            )
        )
    for pred in future_predictions:
        src = pred["src_paper_id"]
        dst = pred["dst_paper_id"]
        add_row(
            (
                edge_id("future", src, dst),
                src,
                dst,
                "future_growth",
                "future",
                float(pred.get("predicted_prob") or 0.0),
                float(pred.get("predicted_prob") or 0.0),
                1,
                0,
                0,
                jdumps({"stroke": "future", "dash": True, "glow": True}),
                jdumps({**pred, "why": "VGAE/temporal prediction candidate"}),
            )
        )
    rows = list(rows_by_id.values())
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_edges
            (edge_id, source_paper_id, target_paper_id, edge_type, layer,
             weight, confidence, is_directed, is_main_path, lod_min,
             style_json, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn_v14.commit()
    actual = conn_v14.execute("SELECT COUNT(*) FROM visual_edges").fetchone()[0]
    logger.info(
        "visual_edges written: %d unique (attempted=%d actual_table=%d)",
        len(rows),
        len(citation_edges) + len(cocitation_edges) + len(semantic_edges) + len(future_predictions),
        actual,
    )


def write_clusters_and_lineage(
    conn_v14: sqlite3.Connection,
    clusters: list[dict],
    lineages: list[dict],
) -> None:
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_clusters
            (cluster_id, branch_id, label, n_nodes, year_start, year_end,
             centroid_x, centroid_y, centroid_z, top_terms_json,
             representative_papers_json, evidence_json)
        VALUES
            (:cluster_id, :branch_id, :label, :n_nodes, :year_start, :year_end,
             :centroid_x, :centroid_y, :centroid_z, :top_terms_json,
             :representative_papers_json, :evidence_json)
        """,
        clusters,
    )
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO branch_lineages
            (branch_id, parent_branch_id, split_year, strength, why_json, future_json)
        VALUES
            (:branch_id, :parent_branch_id, :split_year, :strength, :why_json, :future_json)
        """,
        lineages,
    )
    conn_v14.commit()
    logger.info("visual_clusters=%d branch_lineages=%d", len(clusters), len(lineages))


def write_tiles(conn_v14: sqlite3.Connection, clusters: list[dict], cfg: VisualConfig) -> None:
    rows = []
    for c in clusters:
        cid = c["cluster_id"]
        bounds = {
            "x": c["centroid_x"],
            "y": c["centroid_y"],
            "z": c["centroid_z"],
            "year_start": c["year_start"],
            "year_end": c["year_end"],
        }
        reps = json.loads(c["representative_papers_json"] or "[]")
        for lod in range(4):
            payload = {
                "mode": ["overview", "cluster", "nodes", "local_edges"][lod],
                "representative_papers": reps[: cfg.tile_top_nodes if lod == 0 else len(reps)],
                "query_hint": {
                    "nodes": f"cluster_id = '{cid}'",
                    "edges": f"lod_min <= {lod}",
                },
            }
            rows.append(
                (
                    f"LOD{lod}:{cid}",
                    lod,
                    cid,
                    c["year_start"],
                    c["year_end"],
                    jdumps(bounds),
                    c["n_nodes"],
                    0,
                    jdumps(payload),
                )
            )
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_tiles
            (tile_id, lod_level, cluster_id, year_start, year_end, bounds_json,
             node_count, edge_count, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn_v14.commit()
    logger.info("visual_tiles written: %d", len(rows))


def write_story_steps(conn_v14: sqlite3.Connection, clusters: list[dict]) -> None:
    if not clusters:
        return
    year_min = min(c["year_start"] for c in clusters if c["year_start"])
    year_max = max(c["year_end"] for c in clusters if c["year_end"])
    rows = []
    order = 0
    for start in range(year_min, year_max + 1, 5):
        end = min(year_max, start + 4)
        active = [
            c for c in clusters
            if (c["year_start"] or 9999) <= end and (c["year_end"] or 0) >= start
        ]
        active = sorted(active, key=lambda c: c["n_nodes"], reverse=True)[:5]
        rows.append(
            (
                f"story:{start}-{end}",
                order,
                start,
                end,
                f"{start}-{end}: branch expansion",
                "Time-sliced view of active optics branches and their dominant representative papers.",
                active[0]["cluster_id"] if active else None,
                jdumps([
                    p
                    for c in active
                    for p in json.loads(c["representative_papers_json"] or "[]")[:3]
                ]),
                jdumps({"active_clusters": [c["cluster_id"] for c in active]}),
            )
        )
        order += 1
    rows.append(
        (
            "story:future",
            order,
            year_max,
            year_max + 5,
            "Future growth candidates",
            "Predicted growth arcs and unresolved limitation bottlenecks that may shape next branches.",
            None,
            "[]",
            jdumps({"source": "predicted_future_edges + limitation_atoms + future_directions"}),
        )
    )
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_story_steps
            (story_step_id, order_idx, year_start, year_end, title, narrative,
             focus_cluster_id, focus_papers_json, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn_v14.commit()
    logger.info("visual_story_steps written: %d", len(rows))


def write_details_and_search(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    papers: list[dict],
    clusters_by_id: dict[str, dict],
    assignment: dict[str, str],
    limitations: dict[str, list[dict]],
) -> None:
    paper_ids = [p["id"] for p in papers]
    sections = load_sections(conn_main, paper_ids)
    details_rows = []
    fts_rows = []
    for p in papers:
        pid = p["id"]
        cid = assignment.get(pid)
        cluster = clusters_by_id.get(cid or "", {})
        lims = limitations.get(pid, [])
        paper_sections = sections.get(pid, [])
        ids_json = {
            "paper_id": pid,
            "arxiv_id": p.get("arxiv_id"),
            "doi": p.get("doi"),
            "openalex_work_id": p.get("openalex_work_id"),
            "s2_paper_id": p.get("s2_paper_id_norm"),
            "s2_corpus_id": p.get("s2_corpus_id"),
            "pmid": p.get("pmid"),
            "legacy_openalex_id_value": p.get("legacy_openalex_id_value"),
        }
        metadata = {
            "title": p.get("title"),
            "year": p.get("year"),
            "publication_date": p.get("publication_date"),
            "cited_by_count": p.get("cited_by_count"),
            "field": p.get("primary_field_id"),
            "subfield": p.get("primary_subfield_id"),
            "topic": p.get("primary_topic_id"),
            "cluster_id": cid,
            "branch_id": f"B{cid[1:]}" if cid and cid.startswith("C") else cid,
            "branch_label": cluster.get("label"),
        }
        rec_json = {
            "starter": bool((p.get("cited_by_count") or 0) > 100),
            "frontier": bool((p.get("year") or 0) >= date.today().year - 2),
            "bridge": bool((p.get("c_bridging_centrality") or 0) > 0.2),
            "bottleneck": bool(lims),
        }
        details_rows.append(
            (
                pid,
                jdumps(ids_json),
                jdumps(metadata),
                p.get("abstract"),
                jdumps(paper_sections),
                jdumps(lims),
                jdumps(rec_json),
            )
        )
        section_text = "\n".join(s.get("section_text") or "" for s in paper_sections)
        limitation_text = "\n".join(l.get("description") or "" for l in lims)
        fts_rows.append(
            (
                pid,
                p.get("title") or "",
                p.get("abstract") or "",
                section_text,
                limitation_text,
                cluster.get("label") or "",
                " ".join(
                    str(x or "")
                    for x in (
                        p.get("primary_domain_id"),
                        p.get("primary_field_id"),
                        p.get("primary_subfield_id"),
                        p.get("primary_topic_id"),
                    )
                ),
            )
        )
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_paper_details
            (paper_id, ids_json, metadata_json, abstract, sections_json,
             limitations_json, recommendation_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        details_rows,
    )
    try:
        conn_v14.executemany(
            """
            INSERT INTO visual_search_fts
                (paper_id, title, abstract, sections, limitations, branch_label, topics)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            fts_rows,
        )
    except sqlite3.OperationalError:
        pass
    conn_v14.commit()
    logger.info("visual details/search rows written: %d", len(details_rows))


def write_recommendations(
    conn_v14: sqlite3.Connection,
    papers: list[dict],
    assignment: dict[str, str],
    limitations: dict[str, list[dict]],
    future_predictions: list[dict],
    top_k: int,
) -> None:
    future_score = Counter()
    for pred in future_predictions:
        prob = float(pred.get("predicted_prob") or 0)
        future_score[pred["src_paper_id"]] += prob * 0.5
        future_score[pred["dst_paper_id"]] += prob

    def cite_norm(p):
        return math.log((p.get("cited_by_count") or 0) + 1)

    max_cite = max([cite_norm(p) for p in papers] or [1.0])
    this_year = date.today().year
    modes: dict[str, list[tuple[str, float, dict]]] = defaultdict(list)
    for p in papers:
        pid = p["id"]
        cite = cite_norm(p) / max(max_cite, 1.0)
        key = float(p.get("keystone_score_v14") or 0.0)
        bridge = float(p.get("c_bridging_centrality") or 0.0)
        burst = float(p.get("c_recent_burst") or 0.0)
        age = max(0, this_year - int(p.get("year") or this_year))
        recent = clamp01(1.0 - age / 5.0)
        lim_count = len(limitations.get(pid, []))
        modes["starter"].append((pid, 0.55 * cite + 0.45 * key, {"why": "high citation + keystone"}))
        modes["frontier"].append((pid, 0.45 * recent + 0.35 * burst + 0.20 * key, {"why": "recent + burst + keystone"}))
        modes["bridge"].append((pid, 0.65 * bridge + 0.20 * key + 0.15 * cite, {"why": "cross-field bridge"}))
        modes["bottleneck"].append((pid, 0.60 * min(lim_count / 3, 1) + 0.25 * key + 0.15 * cite, {"why": "unresolved limitations"}))
        modes["future"].append((pid, future_score[pid] + 0.20 * recent + 0.20 * key, {"why": "future prediction support"}))

    rows = []
    for mode, items in modes.items():
        items = sorted(items, key=lambda x: x[1], reverse=True)[:top_k]
        for rank, (pid, score, reason) in enumerate(items, 1):
            reason["cluster_id"] = assignment.get(pid)
            rows.append((mode, rank, pid, float(score), jdumps(reason)))
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO visual_recommendations
            (mode, rank, paper_id, score, reason_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn_v14.commit()
    logger.info("visual_recommendations written: %d", len(rows))


def run_visual_graph_builder(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    cfg: Optional[VisualConfig] = None,
    allow_legacy_ids: Optional[bool] = None,
) -> dict:
    cfg = cfg or VisualConfig.from_env()
    if allow_legacy_ids is not None:
        cfg.allow_legacy_ids = allow_legacy_ids
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_v14 = get_v14b_conn(db_v14)
    conn_v14.row_factory = sqlite3.Row

    validate_graph_ready_schema(conn_main, allow_legacy_ids=cfg.allow_legacy_ids)

    ensure_visual_schema(conn_v14)
    reset_visual_tables(conn_v14)
    upsert_step_meta(conn_v14, "step10_visual_graph_builder", "running")

    papers = load_papers(conn_main, limit)
    paper_ids = [p["id"] for p in papers]
    allowed = set(paper_ids)

    emb_by_id, emb_matrix = load_embeddings(conn_main, paper_ids)
    if emb_matrix is not None and np.count_nonzero(emb_matrix) > 0:
        feature_matrix = emb_matrix
    else:
        logger.info("visual embeddings unavailable; using TF-IDF/SVD text features")
        feature_matrix = build_text_feature_matrix(papers)

    # For exact kNN fallback, use compact features when the source matrix is high-dimensional.
    if feature_matrix.shape[1] > 96:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.preprocessing import normalize

        compact_dim = min(96, feature_matrix.shape[1] - 1, max(2, len(papers) - 1))
        semantic_matrix = normalize(
            TruncatedSVD(n_components=compact_dim, random_state=42).fit_transform(feature_matrix)
        ).astype(np.float32)
    else:
        semantic_matrix = feature_matrix.astype(np.float32)

    coords = compute_xy(semantic_matrix, cfg)
    citation_edges = load_citation_edges(conn_main, allowed)
    cocitation_edges = build_cocitation_edges(conn_main, allowed, cfg)
    semantic_edges = build_semantic_edges(paper_ids, semantic_matrix, cfg)
    main_edges = load_main_path_edges(conn_v14)
    future_predictions = load_future_predictions(conn_v14)
    limitations = load_unresolved_limitations(conn_v14)

    assignment = detect_clusters(paper_ids, citation_edges, cocitation_edges, semantic_edges, cfg)
    clusters, _by_cluster = build_cluster_records(papers, coords, assignment)
    lineages = build_branch_lineages(papers, assignment, citation_edges, future_predictions)

    main_nodes = {x for e, data in main_edges.items() if data.get("is_main_path") for x in e}
    future_nodes = {
        pid
        for pred in future_predictions
        for pid in (pred.get("src_paper_id"), pred.get("dst_paper_id"))
        if pid
    }

    write_clusters_and_lineage(conn_v14, clusters, lineages)
    write_visual_nodes(
        conn_main, conn_v14, papers, coords, assignment, emb_by_id,
        main_nodes, future_nodes, limitations,
    )
    write_visual_edges(
        conn_v14, citation_edges, main_edges, cocitation_edges, semantic_edges, future_predictions
    )
    write_tiles(conn_v14, clusters, cfg)
    write_story_steps(conn_v14, clusters)
    clusters_by_id = {c["cluster_id"]: c for c in clusters}
    write_details_and_search(conn_main, conn_v14, papers, clusters_by_id, assignment, limitations)
    write_recommendations(
        conn_v14, papers, assignment, limitations, future_predictions, cfg.recommendation_top_k
    )

    stats = {
        "records_n": len(papers),
        "visual_nodes": len(papers),
        "citation_edges": len(citation_edges),
        "cocitation_edges": len(cocitation_edges),
        "semantic_edges": len(semantic_edges),
        "future_edges": len(future_predictions),
        "clusters": len(clusters),
        "branch_lineages": len(lineages),
    }
    upsert_step_meta(conn_v14, "step10_visual_graph_builder", "done", records_n=len(papers), notes=jdumps(stats))
    conn_main.close()
    conn_v14.close()
    logger.info("Step10 visual graph builder done: %s", stats)
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step10_visual_graph_builder",
        description="Step 10: build visual graph product tables",
    )
    add_common_args(parser)
    parser.add_argument(
        "--allow-legacy-ids",
        action="store_true",
        help="Diagnostic only: allow mixed legacy provider IDs instead of failing readiness checks.",
    )
    args = parser.parse_args(argv)
    setup_logging("step10_visual_graph_builder", level=getattr(logging, args.log_level))
    run_visual_graph_builder(
        db_main=Path(args.db) if args.db else DB_MAIN,
        db_v14=Path(args.db_v14) if args.db_v14 else DB_V14,
        limit=args.limit,
        allow_legacy_ids=args.allow_legacy_ids,
    )


if __name__ == "__main__":
    main()
