"""
Step 5b: VGAE 训练 + Link Prediction

架构:
  Encoder: 2 层 GCN (797 → 256 → 128 μ/σ)
  Decoder: dot product sigmoid
  Loss: BCE + KL (β=0.5)
  节点特征: abstract_emb(768) + year(1) + cite_log(1) + keystone(1) + field_onehot(26) = 797

输出: v14_pilot.sqlite3 的 predicted_future_edges 表

CLI:
    python -m echelon.v14b.step5b_vgae --help
    python -m echelon.v14b.step5b_vgae
    python -m echelon.v14b.step5b_vgae --epochs 50  # 快速调试
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    VGAE_INPUT_DIM, VGAE_HIDDEN_DIM, VGAE_LATENT_DIM,
    VGAE_EPOCHS, VGAE_LR, VGAE_BETA, VGAE_DROPOUT,
    VGAE_TRAIN_RATIO, VGAE_VAL_RATIO, VGAE_TEST_RATIO,
    VGAE_EARLY_STOP_PATIENCE,
    VGAE_PREDICT_THRESHOLD, VGAE_PREDICT_TOP_K, VGAE_MIN_YEAR_GAP,
    VGAE_ABSTRACT_DIM, VGAE_FIELD_DIM,
    LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import (
    setup_logging, Checkpoint, add_common_args, make_progress, get_torch_device
)

logger = logging.getLogger("echelon.v14b.step5b_vgae")


@dataclass(frozen=True)
class EvolutionEdge:
    """A time-forward evolution edge: older/source paper -> newer/target paper."""
    src_idx: int
    dst_idx: int
    src_id: str
    dst_id: str
    src_year: int
    dst_year: int


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    prob: float
    support: int


def _field_index(field_id) -> Optional[int]:
    if field_id is None:
        return None
    m = re.search(r"\d+", str(field_id))
    if not m:
        return None
    return int(m.group(0)) % VGAE_FIELD_DIM


# ---------------------------------------------------------------------------
# VGAE 模型定义
# ---------------------------------------------------------------------------

def build_vgae_model(input_dim: int = VGAE_INPUT_DIM):
    """
    构建 VGAE 模型。

    Returns:
        (model, device) 或 None 如果 torch_geometric 不可用
    """
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torch_geometric.nn import VGAE, GCNConv

        device = get_torch_device()
        logger.info("VGAE 使用设备: %s", device)

        class VariationalGCNEncoder(nn.Module):
            def __init__(self, in_channels: int, hidden: int, latent: int, dropout: float):
                super().__init__()
                self.conv1 = GCNConv(in_channels, hidden, cached=False)
                self.conv_mu = GCNConv(hidden, latent, cached=False)
                self.conv_logstd = GCNConv(hidden, latent, cached=False)
                self.dropout = dropout

            def forward(self, x, edge_index):
                x = F.relu(self.conv1(x, edge_index))
                x = F.dropout(x, p=self.dropout, training=self.training)
                return self.conv_mu(x, edge_index), self.conv_logstd(x, edge_index)

        encoder = VariationalGCNEncoder(
            in_channels=input_dim,
            hidden=VGAE_HIDDEN_DIM,
            latent=VGAE_LATENT_DIM,
            dropout=VGAE_DROPOUT,
        )
        model = VGAE(encoder).to(device)
        return model, device

    except ImportError as exc:
        logger.error("torch_geometric 不可用: %s", exc)
        return None, None


# ---------------------------------------------------------------------------
# 特征工程
# ---------------------------------------------------------------------------

def build_node_features(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: list[int],
) -> np.ndarray:
    """
    构建节点特征矩阵 (N × 797)。

    特征拼接:
      - abstract_emb (768): 来自 sentence-transformers 或 DB 中已有的 embedding
      - year_norm (1): (year - 1991) / 35
      - cite_log (1): log(cited_by_count + 1) / log(max_cite + 1)
      - keystone (1): keystone_score_v14
      - field_onehot (26): primary_field_id one-hot

    Returns:
        np.ndarray shape (N, VGAE_INPUT_DIM)
    """
    n = len(node_ids)
    features = np.zeros((n, VGAE_INPUT_DIM), dtype=np.float32)

    # 读取论文元数据
    placeholders = ",".join("?" * n)
    rows = conn_main.execute(f"""
        SELECT id, publication_year, cited_by_count, keystone_score_v14, primary_field_id
        FROM papers
        WHERE id IN ({placeholders})
    """, node_ids).fetchall()
    paper_meta = {row[0]: dict(row) for row in rows}

    # 读取 abstract embeddings (如果有)
    emb_available = False
    try:
        rows_emb = conn_main.execute(f"""
            SELECT paper_id, embedding_blob
            FROM paper_embeddings
            WHERE paper_id IN ({placeholders})
        """, node_ids).fetchall()
        emb_dict = {row[0]: row[1] for row in rows_emb}
        emb_available = len(emb_dict) > 0
        if emb_available:
            logger.info("找到 %d 篇论文的 embedding", len(emb_dict))
    except Exception:
        emb_dict = {}

    # 计算 cite_log 归一化最大值
    max_cite = max(
        (p.get("cited_by_count") or 0) for p in paper_meta.values()
    ) if paper_meta else 1
    max_cite_log = math.log(max_cite + 1) or 1.0

    for i, nid in enumerate(node_ids):
        p = paper_meta.get(nid, {})

        # Abstract embedding (768d)
        if nid in emb_dict and emb_dict[nid]:
            try:
                emb = np.frombuffer(emb_dict[nid], dtype=np.float32)
                if len(emb) == VGAE_ABSTRACT_DIM:
                    features[i, :VGAE_ABSTRACT_DIM] = emb
                else:
                    # 截断或补零
                    min_len = min(len(emb), VGAE_ABSTRACT_DIM)
                    features[i, :min_len] = emb[:min_len]
            except Exception:
                pass  # 留零

        # Year norm (1d)
        year = p.get("publication_year") or 2000
        features[i, VGAE_ABSTRACT_DIM] = max(0.0, min(1.0, (year - 1991) / 35.0))

        # Cite log norm (1d)
        cite = p.get("cited_by_count") or 0
        features[i, VGAE_ABSTRACT_DIM + 1] = math.log(cite + 1) / max_cite_log

        # Keystone score (1d)
        ks = p.get("keystone_score_v14") or 0.5
        features[i, VGAE_ABSTRACT_DIM + 2] = ks

        # Field one-hot (26d)
        field_id = p.get("primary_field_id")
        field_idx = _field_index(field_id)
        if field_idx is not None:
            features[i, VGAE_ABSTRACT_DIM + 3 + field_idx] = 1.0

    return features


def _year_from_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_node_years_and_fields(
    conn_main: sqlite3.Connection,
    node_ids: list[str],
) -> dict[str, dict]:
    """Load temporal and field metadata for candidate generation/evaluation."""
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    rows = conn_main.execute(f"""
        SELECT id, publication_year, primary_field_id
        FROM papers WHERE id IN ({placeholders})
    """, node_ids).fetchall()
    return {
        row[0]: {
            "year": _year_from_value(row[1]),
            "field": row[2],
        }
        for row in rows
    }


def build_evolution_edge_records(
    conn_main: sqlite3.Connection,
    raw_edges: list[sqlite3.Row],
    node_id_map: dict[str, int],
) -> tuple[list[EvolutionEdge], dict]:
    """
    Convert raw citation edges into time-forward evolution edges.

    subgraph_edges stores real references as citing -> cited.  For future-growth
    modeling we train on the interpretive direction older -> newer, but only
    when the real citation is temporally consistent (citing paper newer than
    cited paper).  Same-year and clear time-inverted references are excluded
    from VGAE training because they do not provide reliable future direction.
    """
    ids = sorted({r[0] for r in raw_edges} | {r[1] for r in raw_edges})
    meta = load_node_years_and_fields(conn_main, ids)
    records: list[EvolutionEdge] = []
    skipped_same_year = 0
    skipped_unknown_year = 0
    skipped_time_inverted = 0
    skipped_missing_node = 0

    for row in raw_edges:
        citing_id = row[0]
        cited_id = row[1]
        citing_idx = node_id_map.get(citing_id)
        cited_idx = node_id_map.get(cited_id)
        if citing_idx is None or cited_idx is None or citing_idx == cited_idx:
            skipped_missing_node += 1
            continue
        citing_year = meta.get(citing_id, {}).get("year", 0)
        cited_year = meta.get(cited_id, {}).get("year", 0)
        if not citing_year or not cited_year:
            skipped_unknown_year += 1
            continue
        if citing_year == cited_year:
            skipped_same_year += 1
            continue
        if citing_year < cited_year:
            skipped_time_inverted += 1
            continue
        records.append(
            EvolutionEdge(
                src_idx=cited_idx,
                dst_idx=citing_idx,
                src_id=cited_id,
                dst_id=citing_id,
                src_year=cited_year,
                dst_year=citing_year,
            )
        )

    stats = {
        "raw_edges": len(raw_edges),
        "evolution_edges": len(records),
        "skipped_same_year": skipped_same_year,
        "skipped_unknown_year": skipped_unknown_year,
        "skipped_time_inverted": skipped_time_inverted,
        "skipped_missing_node": skipped_missing_node,
    }
    return records, stats


def split_edges_temporally(
    records: list[EvolutionEdge],
    val_ratio: float,
    test_ratio: float,
) -> tuple[list[EvolutionEdge], list[EvolutionEdge], list[EvolutionEdge]]:
    """Chronological holdout: train on earlier target-year edges, validate/test later."""
    if len(records) < 10:
        return records, [], []
    ordered = sorted(records, key=lambda e: (e.dst_year, e.src_year, e.src_id, e.dst_id))
    n = len(ordered)
    n_test = max(1, int(n * test_ratio))
    n_val = max(1, int(n * val_ratio))
    train_end = max(1, n - n_val - n_test)
    val_end = max(train_end + 1, n - n_test)
    return ordered[:train_end], ordered[train_end:val_end], ordered[val_end:]


def edge_index_from_records(records: list[EvolutionEdge], device):
    import torch
    if not records:
        return torch.empty((2, 0), dtype=torch.long, device=device)
    return torch.tensor(
        [[e.src_idx for e in records], [e.dst_idx for e in records]],
        dtype=torch.long,
        device=device,
    )


def sample_temporal_negative_edges(
    node_years: list[int],
    positive_pairs: set[tuple[int, int]],
    n_samples: int,
    device,
    seed: int = 42,
):
    """Sample older -> newer non-edges for temporal validation/test."""
    import torch

    if n_samples <= 0:
        return torch.empty((2, 0), dtype=torch.long, device=device)

    rng = np.random.default_rng(seed)
    n_nodes = len(node_years)
    samples: set[tuple[int, int]] = set()
    max_attempts = max(1000, n_samples * 300)
    attempts = 0
    while len(samples) < n_samples and attempts < max_attempts:
        attempts += 1
        a = int(rng.integers(0, n_nodes))
        b = int(rng.integers(0, n_nodes))
        if a == b:
            continue
        ya = node_years[a]
        yb = node_years[b]
        if not ya or not yb or ya == yb:
            continue
        src, dst = (a, b) if ya < yb else (b, a)
        if (src, dst) in positive_pairs or (src, dst) in samples:
            continue
        samples.add((src, dst))

    if not samples:
        return torch.empty((2, 0), dtype=torch.long, device=device)
    arr = np.array(sorted(samples), dtype=np.int64).T
    return torch.tensor(arr, dtype=torch.long, device=device)


def edge_scores_from_latent(z, edge_index) -> np.ndarray:
    """Return raw sigmoid dot-product scores for a set of directed edges."""
    import torch

    if edge_index is None or edge_index.numel() == 0:
        return np.array([], dtype=np.float32)
    with torch.no_grad():
        src = z[edge_index[0]]
        dst = z[edge_index[1]]
        scores = torch.sigmoid((src * dst).sum(dim=1))
    return scores.detach().cpu().numpy().astype(np.float32)


def fit_probability_calibrator(
    positive_scores: np.ndarray,
    negative_scores: np.ndarray,
    *,
    bins: int | None = None,
) -> dict:
    """
    Fit a probability calibrator from chronological holdout scores.

    Preferred calibrator is 1D Platt scaling (logistic regression on raw VGAE
    scores). We keep a histogram fallback if sklearn is unavailable.
    """
    positive_scores = np.asarray(positive_scores, dtype=np.float32)
    negative_scores = np.asarray(negative_scores, dtype=np.float32)
    if positive_scores.size == 0 or negative_scores.size == 0:
        return {
            "method": "uncalibrated_no_holdout",
            "bins": [],
            "support": 0,
            "base_rate": 0.5,
            "label": "uncalibrated",
        }

    scores = np.concatenate([positive_scores, negative_scores])
    labels = np.concatenate([
        np.ones_like(positive_scores, dtype=np.float32),
        np.zeros_like(negative_scores, dtype=np.float32),
    ])
    prior = float(labels.mean())
    support = int(len(scores))

    try:
        from sklearn.linear_model import LogisticRegression

        x = scores.reshape(-1, 1)
        y = labels.astype(np.int32)
        # Mild regularization keeps probabilities conservative on small holdouts.
        clf = LogisticRegression(
            solver="lbfgs",
            max_iter=800,
            C=6.0,
            class_weight="balanced",
            random_state=42,
        )
        clf.fit(x, y)
        coef = float(clf.coef_[0][0])
        intercept = float(clf.intercept_[0])
        return {
            "method": "temporal_platt_logistic",
            "coef": coef,
            "intercept": intercept,
            "support": support,
            "base_rate": prior,
            "label": "calibrated_temporal_holdout",
            "score_min": float(scores.min()),
            "score_max": float(scores.max()),
        }
    except Exception:
        pass

    # Fallback histogram calibration.
    order = np.argsort(scores)
    scores = scores[order]
    labels = labels[order]
    n = len(scores)
    desired_bins = int(bins) if bins is not None else (n // 40 if n >= 160 else n)
    n_bins = max(4, min(20, desired_bins))
    raw_bins: list[CalibrationBin] = []
    for idxs in np.array_split(np.arange(n), n_bins):
        if len(idxs) == 0:
            continue
        pos = float(labels[idxs].sum())
        bin_support = int(len(idxs))
        prob = (pos + prior * 4.0) / (bin_support + 4.0)
        raw_bins.append(
            CalibrationBin(
                low=float(scores[idxs[0]]),
                high=float(scores[idxs[-1]]),
                prob=float(prob),
                support=bin_support,
            )
        )

    calibrated_bins = []
    running = 0.0
    for b in raw_bins:
        running = max(running, b.prob)
        calibrated_bins.append(
            {
                "low": b.low,
                "high": b.high,
                "prob": min(0.995, float(running)),
                "support": b.support,
            }
        )

    return {
        "method": "temporal_quantile_histogram_laplace",
        "bins": calibrated_bins,
        "support": support,
        "base_rate": prior,
        "label": "calibrated_temporal_holdout",
    }


def apply_probability_calibration(raw_score: float, calibrator: dict) -> tuple[float, int, str]:
    """Map a raw VGAE score to calibrated product confidence."""
    method = calibrator.get("method")
    if method == "temporal_platt_logistic":
        coef = float(calibrator.get("coef") or 0.0)
        intercept = float(calibrator.get("intercept") or 0.0)
        base_rate = float(calibrator.get("base_rate") or 0.5)
        support = int(calibrator.get("support") or 0)
        score = float(raw_score)
        logit = coef * score + intercept
        calibrated = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit))))
        # Conservative shrinkage toward the empirical base rate for small
        # calibration support.
        shrink = min(1.0, support / 800.0)
        calibrated = base_rate + (calibrated - base_rate) * shrink
        calibrated = max(0.01, min(0.995, calibrated))
        return calibrated, support, calibrator.get("label", "calibrated")

    bins = calibrator.get("bins") or []
    if not bins:
        score = max(0.0, min(1.0, float(raw_score)))
        # No holdout means the score remains ranking evidence only.
        return min(0.65, score), 0, calibrator.get("label", "uncalibrated")

    score = float(raw_score)
    chosen = bins[-1]
    for b in bins:
        if score <= float(b["high"]):
            chosen = b
            break
    calibrated = max(0.0, min(1.0, float(chosen["prob"])))
    return calibrated, int(chosen.get("support") or 0), calibrator.get("label", "calibrated")


def calibration_summary(
    calibrator: dict,
    positive_scores: np.ndarray,
    negative_scores: np.ndarray,
) -> dict:
    """Summarise calibration quality for checkpoints and Step12."""
    pos = [apply_probability_calibration(float(s), calibrator)[0] for s in positive_scores]
    neg = [apply_probability_calibration(float(s), calibrator)[0] for s in negative_scores]
    return {
        "method": calibrator.get("method"),
        "label": calibrator.get("label"),
        "support": int(calibrator.get("support") or 0),
        "base_rate": float(calibrator.get("base_rate") or 0.0),
        "positive_calibrated_avg": float(np.mean(pos)) if pos else 0.0,
        "negative_calibrated_avg": float(np.mean(neg)) if neg else 0.0,
        "n_bins": len(calibrator.get("bins") or []),
    }


def sample_temporal_negative_edges_for_year(
    node_years: list[int],
    positive_pairs: set[tuple[int, int]],
    target_year: int,
    n_samples: int,
    device,
    seed: int = 42,
):
    """Sample temporal non-edges constrained to a specific destination year."""
    import torch

    older_nodes = [i for i, y in enumerate(node_years) if y and y < target_year]
    target_nodes = [i for i, y in enumerate(node_years) if y == target_year]
    if not older_nodes or not target_nodes or n_samples <= 0:
        return torch.empty((2, 0), dtype=torch.long, device=device)

    rng = np.random.default_rng(seed)
    samples: set[tuple[int, int]] = set()
    max_attempts = max(2000, n_samples * 300)
    attempts = 0
    while len(samples) < n_samples and attempts < max_attempts:
        attempts += 1
        src = older_nodes[int(rng.integers(0, len(older_nodes)))]
        dst = target_nodes[int(rng.integers(0, len(target_nodes)))]
        if src == dst:
            continue
        if (src, dst) in positive_pairs or (src, dst) in samples:
            continue
        samples.add((src, dst))

    if not samples:
        return torch.empty((2, 0), dtype=torch.long, device=device)
    arr = np.array(sorted(samples), dtype=np.int64).T
    return torch.tensor(arr, dtype=torch.long, device=device)


def rolling_year_backtest(
    *,
    z,
    holdout_records: list[EvolutionEdge],
    node_years: list[int],
    positive_pairs: set[tuple[int, int]],
    calibrator: dict,
    device,
    max_years: int = 6,
    min_positives: int = 20,
) -> dict:
    """
    Run rolling held-out-year temporal checks on validation/test holdout edges.
    """
    if not holdout_records:
        return {"years": [], "avg_raw_auc": 0.0, "avg_calibrated_auc": 0.0}

    by_year: dict[int, list[EvolutionEdge]] = {}
    for rec in holdout_records:
        by_year.setdefault(rec.dst_year, []).append(rec)
    candidate_years = sorted(by_year.keys())
    if len(candidate_years) > max_years:
        candidate_years = candidate_years[-max_years:]

    rows = []
    seed = 140
    for year in candidate_years:
        pos_records = by_year.get(year, [])
        if len(pos_records) < min_positives:
            continue
        pos_edge_index = edge_index_from_records(pos_records, device)
        neg_edge_index = sample_temporal_negative_edges_for_year(
            node_years=node_years,
            positive_pairs=positive_pairs,
            target_year=year,
            n_samples=len(pos_records),
            device=device,
            seed=seed,
        )
        seed += 1
        if neg_edge_index.numel() == 0:
            continue

        pos_raw = edge_scores_from_latent(z, pos_edge_index)
        neg_raw = edge_scores_from_latent(z, neg_edge_index)
        if pos_raw.size == 0 or neg_raw.size == 0:
            continue

        labels = np.concatenate([
            np.ones_like(pos_raw, dtype=np.float32),
            np.zeros_like(neg_raw, dtype=np.float32),
        ])
        raw_scores = np.concatenate([pos_raw, neg_raw])
        cal_scores = np.array(
            [apply_probability_calibration(float(s), calibrator)[0] for s in raw_scores],
            dtype=np.float32,
        )

        try:
            from sklearn.metrics import roc_auc_score

            raw_auc = float(roc_auc_score(labels, raw_scores))
            cal_auc = float(roc_auc_score(labels, cal_scores))
        except Exception:
            raw_auc = 0.0
            cal_auc = 0.0

        rows.append(
            {
                "year": int(year),
                "positives": int(len(pos_records)),
                "negatives": int(neg_raw.size),
                "raw_auc": raw_auc,
                "calibrated_auc": cal_auc,
                "raw_avg": float(np.mean(raw_scores)),
                "calibrated_avg": float(np.mean(cal_scores)),
            }
        )

    if not rows:
        return {"years": [], "avg_raw_auc": 0.0, "avg_calibrated_auc": 0.0}
    return {
        "years": rows,
        "avg_raw_auc": float(np.mean([r["raw_auc"] for r in rows])),
        "avg_calibrated_auc": float(np.mean([r["calibrated_auc"] for r in rows])),
    }


# ---------------------------------------------------------------------------
# 训练
# ---------------------------------------------------------------------------

def train_vgae(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    epochs: int = VGAE_EPOCHS,
    limit: Optional[int] = None,
) -> dict:
    """
    训练 VGAE 并执行 Link Prediction。

    Returns:
        训练统计字典
    """
    import torch
    from torch_geometric.utils import to_undirected
    from torch_geometric.data import Data

    # 读取子图节点
    rows = conn_v14.execute("SELECT paper_id FROM subgraph_nodes").fetchall()
    node_ids = [row[0] for row in rows]
    if limit:
        node_ids = node_ids[:limit]
    n_nodes = len(node_ids)
    logger.info("VGAE 训练节点: %d", n_nodes)

    node_id_map = {nid: i for i, nid in enumerate(node_ids)}

    # 读取子图边
    rows = conn_v14.execute("""
        SELECT citing_id, cited_id FROM subgraph_edges
    """).fetchall()
    edge_records, edge_stats = build_evolution_edge_records(conn_main, rows, node_id_map)
    logger.info("VGAE temporal evolution edges: %s", edge_stats)

    # 构建特征矩阵
    features = build_node_features(conn_main, conn_v14, node_ids)

    device = get_torch_device()
    model, _ = build_vgae_model(features.shape[1])
    if model is None:
        return {"error": "torch_geometric not available", "val_auc": 0.0}

    x = torch.tensor(features, dtype=torch.float).to(device)

    if not edge_records:
        logger.warning("无可靠时间方向演化边,跳过 VGAE 训练")
        return {"val_auc": 0.0, "test_auc": 0.0, "edge_stats": edge_stats}

    train_records, val_records, test_records = split_edges_temporally(
        edge_records, VGAE_VAL_RATIO, VGAE_TEST_RATIO
    )
    train_pos_edge_index = edge_index_from_records(train_records, device)
    encoder_edge_index = to_undirected(train_pos_edge_index, num_nodes=n_nodes)
    data = Data(x=x, edge_index=encoder_edge_index, num_nodes=n_nodes)

    all_positive_pairs = {(e.src_idx, e.dst_idx) for e in edge_records}
    node_meta = load_node_years_and_fields(conn_main, node_ids)
    node_years = [int(node_meta.get(nid, {}).get("year") or 0) for nid in node_ids]
    val_pos_edge_index = edge_index_from_records(val_records, device)
    test_pos_edge_index = edge_index_from_records(test_records, device)
    val_neg_edge_index = sample_temporal_negative_edges(
        node_years, all_positive_pairs, len(val_records), device, seed=43
    )
    test_neg_edge_index = sample_temporal_negative_edges(
        node_years, all_positive_pairs, len(test_records), device, seed=44
    )

    optimizer = torch.optim.Adam(model.parameters(), lr=VGAE_LR)

    best_val_auc = -1.0
    patience_counter = 0
    train_stats = []

    logger.info("开始训练 VGAE: epochs=%d lr=%.4f beta=%.2f", epochs, VGAE_LR, VGAE_BETA)

    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()

        z = model.encode(data.x, data.edge_index)
        loss = model.recon_loss(z, train_pos_edge_index)
        # KL loss (β-VAE)
        kl_loss = VGAE_BETA * (1 / n_nodes) * model.kl_loss()
        total_loss = loss + kl_loss
        total_loss.backward()
        optimizer.step()

        # 验证
        model.eval()
        with torch.no_grad():
            z = model.encode(data.x, data.edge_index)
            if val_pos_edge_index.numel() and val_neg_edge_index.numel():
                auc, ap = model.test(z, val_pos_edge_index, val_neg_edge_index)
            else:
                auc, ap = 0.0, 0.0

        train_stats.append({"epoch": epoch, "loss": float(total_loss), "val_auc": float(auc)})

        if epoch % 20 == 0 or epoch == 1:
            logger.info("Epoch %d/%d  loss=%.4f  val_auc=%.4f", epoch, epochs, total_loss, auc)

        # 早停
        if auc > best_val_auc:
            best_val_auc = auc
            patience_counter = 0
            # 保存最佳模型状态
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= VGAE_EARLY_STOP_PATIENCE:
                logger.info("早停 at epoch %d (patience=%d)", epoch, VGAE_EARLY_STOP_PATIENCE)
                break

    # 加载最佳模型
    if 'best_state' in dir():
        model.load_state_dict(best_state)

    # 测试集 AUC
    model.eval()
    with torch.no_grad():
        z = model.encode(data.x, data.edge_index)
        if test_pos_edge_index.numel() and test_neg_edge_index.numel():
            test_auc, test_ap = model.test(z, test_pos_edge_index, test_neg_edge_index)
        else:
            test_auc, test_ap = 0.0, 0.0

    logger.info("测试集 AUC=%.4f AP=%.4f", test_auc, test_ap)

    val_pos_scores = edge_scores_from_latent(z, val_pos_edge_index)
    val_neg_scores = edge_scores_from_latent(z, val_neg_edge_index)
    test_pos_scores = edge_scores_from_latent(z, test_pos_edge_index)
    test_neg_scores = edge_scores_from_latent(z, test_neg_edge_index)
    calibrator = fit_probability_calibrator(val_pos_scores, val_neg_scores)
    cal_summary = calibration_summary(
        calibrator,
        test_pos_scores if test_pos_scores.size else val_pos_scores,
        test_neg_scores if test_neg_scores.size else val_neg_scores,
    )
    logger.info("VGAE calibration: %s", cal_summary)
    rolling_backtest = rolling_year_backtest(
        z=z,
        holdout_records=val_records + test_records,
        node_years=node_years,
        positive_pairs=all_positive_pairs,
        calibrator=calibrator,
        device=device,
    )
    logger.info("VGAE rolling held-out-year backtest: %s", rolling_backtest)

    # Link Prediction
    predicted_edges = predict_future_links(
        model=model,
        z=z,
        node_ids=node_ids,
        conn_main=conn_main,
        existing_edges=all_positive_pairs,
        device=device,
        calibrator=calibrator,
        auc=float(test_auc),
    )

    return {
        "val_auc": float(best_val_auc),
        "test_auc": float(test_auc),
        "test_ap": float(test_ap),
        "predicted_edges": predicted_edges,
        "epochs_run": len(train_stats),
        "edge_stats": edge_stats,
        "train_edges": len(train_records),
        "val_edges": len(val_records),
        "test_edges": len(test_records),
        "calibration": cal_summary,
        "rolling_backtest": rolling_backtest,
    }


def predict_future_links(
    model,
    z,
    node_ids: list[int],
    conn_main: sqlite3.Connection,
    existing_edges: set,
    device,
    top_k: int = VGAE_PREDICT_TOP_K,
    threshold: float = VGAE_PREDICT_THRESHOLD,
    calibrator: Optional[dict] = None,
    auc: float = 0.0,
) -> list[dict]:
    """
    预测未来引用边。

    只保留:
      - 当前不存在的边
      - 时间间隔 >= 1 年
      - 预测概率 > threshold
    """
    import torch

    n = len(node_ids)

    meta = load_node_years_and_fields(conn_main, node_ids)

    predictions = []

    # 分批计算 (避免 N×N 矩阵太大)
    batch_size = 256
    with torch.no_grad():
        for i in range(0, n, batch_size):
            for j in range(0, n, batch_size):
                z_i = z[i: i + batch_size]
                z_j = z[j: j + batch_size]
                # 点积 sigmoid
                scores = torch.sigmoid(torch.mm(z_i, z_j.t()))
                scores_np = scores.cpu().numpy()

                for di, si in enumerate(range(i, min(i + batch_size, n))):
                    for dj, sj in enumerate(range(j, min(j + batch_size, n))):
                        if si == sj:
                            continue
                        raw_prob = float(scores_np[di, dj])
                        if raw_prob < threshold:
                            continue

                        src_id = node_ids[si]
                        dst_id = node_ids[sj]
                        src_year = int(meta.get(src_id, {}).get("year") or 0)
                        dst_year = int(meta.get(dst_id, {}).get("year") or 0)

                        # Future-edge semantics: source is the older/current
                        # anchor and destination is the newer potential branch.
                        if not src_year or not dst_year or dst_year <= src_year:
                            continue
                        if (dst_year - src_year) < VGAE_MIN_YEAR_GAP:
                            continue
                        # Dot-product VGAE scores are symmetric; exclude known
                        # citation/evolution pairs in either orientation so a
                        # reversed historical citation is not sold as future.
                        if (si, sj) in existing_edges or (sj, si) in existing_edges:
                            continue

                        src_field = meta.get(src_id, {}).get("field")
                        dst_field = meta.get(dst_id, {}).get("field")
                        is_cross = (src_field != dst_field and
                                    src_field is not None and dst_field is not None)
                        calibrated_prob, support, label = apply_probability_calibration(
                            raw_prob,
                            calibrator or {},
                        )
                        # Product confidence combines empirical calibration with
                        # temporal holdout ranking quality.  This keeps high raw
                        # VGAE scores useful without turning them into
                        # unsupported scientific certainty.
                        prediction_confidence = calibrated_prob * max(0.0, min(1.0, float(auc or 0.0)))

                        predictions.append({
                            "src_paper_id": src_id,
                            "dst_paper_id": dst_id,
                            "predicted_prob": calibrated_prob,
                            "raw_predicted_prob": raw_prob,
                            "calibrated_prob": calibrated_prob,
                            "calibration_method": (calibrator or {}).get("method", "uncalibrated"),
                            "calibration_support": support,
                            "prediction_confidence": prediction_confidence,
                            "calibration_label": label,
                            "src_year": src_year,
                            "dst_year": dst_year,
                            "is_cross_field": int(is_cross),
                        })

    # 排序取 top K
    predictions.sort(
        key=lambda x: (x.get("prediction_confidence") or 0.0, x.get("raw_predicted_prob") or 0.0),
        reverse=True,
    )
    return predictions[:top_k]


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_vgae(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    epochs: int = VGAE_EPOCHS,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    """执行 Step 5b: VGAE 训练 + Link Prediction"""
    step_name = "step5b_vgae"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step5b 已完成 (%d predicted),跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    train_result = train_vgae(conn_main, conn_v14, epochs=epochs, limit=limit)

    if "error" in train_result:
        logger.error("VGAE 训练失败: %s", train_result["error"])
        ck.mark_done(records_n=0, meta=train_result)
        return train_result

    # 写入预测结果
    predicted = train_result.get("predicted_edges", [])
    if predicted:
        conn_v14.execute("DELETE FROM predicted_future_edges")
        conn_v14.executemany("""
            INSERT OR REPLACE INTO predicted_future_edges
                (src_paper_id, dst_paper_id, predicted_prob,
                 raw_predicted_prob, calibrated_prob, calibration_method,
                 calibration_support, prediction_confidence, calibration_label,
                 src_year, dst_year, is_cross_field)
            VALUES
                (:src_paper_id, :dst_paper_id, :predicted_prob,
                 :raw_predicted_prob, :calibrated_prob, :calibration_method,
                 :calibration_support, :prediction_confidence, :calibration_label,
                 :src_year, :dst_year, :is_cross_field)
        """, predicted)
        conn_v14.commit()

    n_predicted = len(predicted)
    cross_field_n = sum(1 for e in predicted if e.get("is_cross_field"))

    stats = {
        "val_auc": train_result.get("val_auc", 0.0),
        "test_auc": train_result.get("test_auc", 0.0),
        "predicted_edges": n_predicted,
        "cross_field_edges": cross_field_n,
        "calibration": train_result.get("calibration", {}),
        "rolling_backtest": train_result.get("rolling_backtest", {}),
        "prediction_confidence_avg": (
            sum(float(e.get("prediction_confidence") or 0.0) for e in predicted) / max(1, n_predicted)
        ),
        "records_n": n_predicted,
    }

    upsert_step_meta(conn_v14, step_name, "done", records_n=n_predicted)
    conn_main.close()
    conn_v14.close()

    ck.mark_done(records_n=n_predicted, meta=stats)
    logger.info(
        "Step5b 完成: val_auc=%.4f test_auc=%.4f predicted=%d cross_field=%d",
        stats["val_auc"], stats["test_auc"], n_predicted, cross_field_n,
    )
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step5b_vgae",
        description="Step 5b: VGAE 训练 + Link Prediction",
    )
    add_common_args(parser)
    parser.add_argument("--epochs", type=int, default=VGAE_EPOCHS, help="训练轮数")
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step5b_vgae", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_vgae(
        db_main=db_main, db_v14=db_v14,
        epochs=args.epochs, limit=limit, resume=args.resume,
    )


if __name__ == "__main__":
    main()
