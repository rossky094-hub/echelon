"""
V11.4-N3: Co-citation edge builder with adaptive quantile threshold.

V11.3-R7 introduced a fixed min_weight=2 threshold. V11.4-N3 replaces it
with a distribution-based adaptive threshold:

  threshold = max(min_floor, P50(weight_distribution))

Rationale:
- 新语料(sparse distribution): P50=1 → threshold = max(2,1) = 2
- 老语料(heavy-tail distribution): P50=2-3 → threshold = max(2,3) = 3
- Adaptive threshold matches corpus age without manual tuning

AUDIT-075 compliance: all co_citation edges still carry the weight field
(= co-citation count), enabling betweenness_centrality(weight="weight").
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple

import numpy as np


# V11.3-R7 / V11.4-N3: Minimum co-citation count floor
MIN_COCITE_WEIGHT: int = 2


def build_cocitation_edges(
    papers: List[Dict],
    paper_id_field: str = "paper_id",
    referenced_works_field: str = "referenced_work_ids",
    min_weight: int = MIN_COCITE_WEIGHT,
) -> List[Tuple[str, str, int]]:
    """
    [V11.3-R7] Build co-citation edges with minimum co-citation threshold.

    Two papers A and B are co-cited if a third paper C (within our corpus)
    cites both A and B in its reference list. The co-citation weight is the
    number of such third papers C.

    V11.3-R7: Only build an edge if co-citation weight >= min_weight (default 2).
    This removes noisy singleton pairs while preserving meaningful relationships.

    Args:
        papers:                   List of paper dicts.
        paper_id_field:           Key for paper ID in each dict.
        referenced_works_field:   Key for list of referenced work IDs.
        min_weight:               Minimum co-citation count (default 2).

    Returns:
        List of (paper_id_a, paper_id_b, co_citation_weight) tuples,
        where co_citation_weight >= min_weight.
        paper_id_a < paper_id_b (lexicographic, for deduplication).
    """
    if not papers:
        return []

    # Build reverse index: cited_ref_oa -> [paper_ids that cite it]
    cited_by: Dict[str, List[str]] = defaultdict(list)
    for p in papers:
        pid = p.get(paper_id_field, "")
        if not pid:
            continue
        for ref_oa in (p.get(referenced_works_field, []) or []):
            if ref_oa:
                cited_by[ref_oa].append(pid)

    # Count co-citation pairs
    cocite_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for ref_oa, citing_papers in cited_by.items():
        if len(citing_papers) < 2:
            continue
        # All pairs within the citing_papers list share this reference
        for i in range(len(citing_papers)):
            for j in range(i + 1, len(citing_papers)):
                pid_a = citing_papers[i]
                pid_b = citing_papers[j]
                if pid_a == pid_b:
                    continue
                pair = (min(pid_a, pid_b), max(pid_a, pid_b))
                cocite_counts[pair] += 1

    # Filter by minimum weight (V11.3-R7)
    edges = [
        (pair[0], pair[1], weight)
        for pair, weight in cocite_counts.items()
        if weight >= min_weight
    ]

    return edges


def cocite_stats(edges: List[Tuple[str, str, int]]) -> Dict:
    """
    Return summary statistics for co-citation edges.

    Args:
        edges: List of (paper_id_a, paper_id_b, weight) tuples.

    Returns:
        Dict with keys: total_edges, min_weight, max_weight, mean_weight.
    """
    if not edges:
        return {"total_edges": 0, "min_weight": 0, "max_weight": 0, "mean_weight": 0.0}

    weights = [e[2] for e in edges]
    return {
        "total_edges": len(edges),
        "min_weight": min(weights),
        "max_weight": max(weights),
        "mean_weight": sum(weights) / len(weights),
    }


# ─────────────────────────────────────────────────────────────────────────────
# V11.4-N3: Adaptive quantile threshold
# ─────────────────────────────────────────────────────────────────────────────

def compute_adaptive_cocite_threshold(
    weight_distribution: List[int],
    min_floor: int = 2,
) -> int:
    """
    [V11.4-N3] Compute adaptive co-citation threshold based on weight distribution.

    Uses P50 (median) of the raw weight distribution as the threshold,
    but never goes below min_floor (default 2).

    Behaviour by corpus type:
    - 新语料 (sparse): P50=1 → threshold = max(2, 1) = 2
    - 老语料 (heavy-tail): P50=2-3 → threshold = max(2, 3) = 3

    Args:
        weight_distribution: List of raw co-citation weight values (all pairs
                             before filtering), e.g. [1, 1, 1, 2, 3, ...].
        min_floor:           Hard minimum threshold (default 2, per V11.3-R7).

    Returns:
        int: adaptive threshold ≥ min_floor
    """
    if not weight_distribution:
        return min_floor
    p50 = int(np.percentile(weight_distribution, 50))
    return max(min_floor, p50)


def build_cocitation_edges_adaptive(
    papers_refs: Dict[str, List[str]],
    min_floor: int = 2,
) -> Tuple[List[Dict], Dict]:
    """
    [V11.4-N3] Build co-citation edges with adaptive quantile threshold.

    Unlike the fixed-threshold `build_cocitation_edges`, this function:
    1. Computes ALL co-citation pair weights first
    2. Derives an adaptive threshold via compute_adaptive_cocite_threshold()
    3. Filters edges at that threshold

    Args:
        papers_refs: Mapping of paper_id → list of referenced work IDs.
                     Each key is a paper in our corpus; each value is its
                     reference list (OA IDs, already normalised).
        min_floor:   Hard minimum for the threshold (default 2).

    Returns:
        (edges, stats) where:
        - edges: list of dicts with keys
            "src", "dst", "weight", "edge_type"="co_citation"
        - stats: dict with keys
            "threshold_used"            – the adaptive threshold
            "raw_pair_count"            – total pairs before filtering
            "filtered_edge_count"       – edges after threshold filter
            "weight_distribution_summary" – dict with p25/p50/p75/max
    """
    if not papers_refs:
        return [], {
            "threshold_used": min_floor,
            "raw_pair_count": 0,
            "filtered_edge_count": 0,
            "weight_distribution_summary": {},
        }

    # Build reverse index: ref → [paper_ids that cite it]
    cited_by: Dict[str, List[str]] = defaultdict(list)
    for pid, refs in papers_refs.items():
        for ref in (refs or []):
            if ref:
                cited_by[ref].append(pid)

    # Count co-citation pairs
    cocite_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for ref, citing_papers in cited_by.items():
        if len(citing_papers) < 2:
            continue
        for i in range(len(citing_papers)):
            for j in range(i + 1, len(citing_papers)):
                pid_a = citing_papers[i]
                pid_b = citing_papers[j]
                if pid_a == pid_b:
                    continue
                pair = (min(pid_a, pid_b), max(pid_a, pid_b))
                cocite_counts[pair] += 1

    # Collect ALL weights for distribution analysis
    all_weights = list(cocite_counts.values())

    # Compute adaptive threshold
    threshold = compute_adaptive_cocite_threshold(all_weights, min_floor=min_floor)

    # Filter edges
    edges = [
        {
            "src": pair[0],
            "dst": pair[1],
            "weight": weight,
            "edge_type": "co_citation",
        }
        for pair, weight in cocite_counts.items()
        if weight >= threshold
    ]

    # Distribution summary
    dist_summary: Dict = {}
    if all_weights:
        dist_summary = {
            "p25": int(np.percentile(all_weights, 25)),
            "p50": int(np.percentile(all_weights, 50)),
            "p75": int(np.percentile(all_weights, 75)),
            "max": int(max(all_weights)),
            "total_pairs": len(all_weights),
        }

    stats = {
        "threshold_used": threshold,
        "raw_pair_count": len(all_weights),
        "filtered_edge_count": len(edges),
        "weight_distribution_summary": dist_summary,
    }

    return edges, stats
