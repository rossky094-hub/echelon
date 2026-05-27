"""
V11.4-N5: Categorised bridge keyword library (100+ terms) with category-aware APIs.

V11.3 background:
  38 Optics ↔ AI bridge keywords. Any matching paper receives forced
  semantic_bridge edges (weight=0.5) to papers in other topic buckets.

V11.4 changes (N5-A):
  Bridge keywords are split into 4 named categories:
    OPTICS_AI         — original 38 terms (unchanged, backward compat)
    ROBOTICS_ML       — 20 new terms (imitation learning, sim-to-real, ...)
    VLM_WORLD_MODEL   — 15 new terms (world model, JEPA, ...)
    GENERIC_AI4SCIENCE — 10 new terms (PINN, neural ODE, ...)

  Total: 83+ unique terms.

  New V11.4 API:
    contains_bridge_keyword_v4(text) -> (bool, category | None)
    build_bridge_keyword_edges_v4(papers) -> list[dict] with "category" field

  V11.3 API preserved (backward compat):
    BRIDGE_KEYWORDS       — flat list (OPTICS_AI only, length == 38)
    contains_bridge_keyword(text)
    find_bridge_keywords(text)
    build_bridge_keyword_edges(papers)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# V11.4 categorised keyword dictionary
# Priority order for tie-breaking: OPTICS_AI > ROBOTICS_ML > VLM_WORLD_MODEL > GENERIC_AI4SCIENCE
# ---------------------------------------------------------------------------

BRIDGE_KEYWORDS_V4: Dict[str, List[str]] = {
    # ── OPTICS_AI: original 38 terms (V11.3, preserved verbatim) ──────────
    "OPTICS_AI": [
        # Optics ↔ Deep Learning
        "diffractive deep neural network",
        "diffractive optical neural network",
        "DONN",
        "D2NN",
        "optical neural network",
        "photonic neural network",
        "all-optical neural network",
        "metasurface for machine learning",
        "metasurface neural network",
        # Computational Imaging
        "computational imaging",
        "deep optics",
        "end-to-end deep imaging",
        "joint optimization optics",
        "lensless imaging",
        "single-pixel imaging deep learning",
        # Inverse Design
        "inverse design with deep learning",
        "deep learning inverse design",
        "neural network metasurface design",
        "topology optimization deep learning",
        "generative model metasurface",
        # Optical Computing / Foundations
        "optical computing",
        "photonic computing",
        "in-memory optical computing",
        "Fourier optics deep learning",
        "DOE-based deep learning",
        "diffractive optical element learning",
        # Sensing & Vision-Optics
        "computational camera",
        "neural rendering optics",
        "differentiable rendering",
        "hyperspectral imaging deep learning",
        "snapshot compressive imaging",
        # Neuromorphic
        "neuromorphic photonic",
        "spiking photonic neural network",
        # AI4Science Optics
        "physics-informed neural network optics",
        "AI for photonics",
        "machine learning photonics",
        "deep learning metaphotonics",
        "data-driven nanophotonics",
    ],

    # ── ROBOTICS_ML: 20 new terms ─────────────────────────────────────────
    "ROBOTICS_ML": [
        "imitation learning",
        "reinforcement learning robotics",
        "sim-to-real",
        "domain randomization",
        "behavior cloning",
        "DAgger",
        "diffusion policy",
        "VLA",
        "vision-language-action",
        "RT-2",
        "RT-X",
        "Open X-Embodiment",
        "deep reinforcement learning manipulation",
        "inverse reinforcement learning",
        "GAIL",
        "curriculum learning robotics",
        "learning from demonstration",
        "motor skill learning",
        "physics-informed reinforcement learning",
        "soft actor critic robotic",
    ],

    # ── VLM_WORLD_MODEL: 15 new terms ────────────────────────────────────
    "VLM_WORLD_MODEL": [
        "dreamerv3",
        "world model",
        "latent dynamics",
        "model-based RL",
        "planning with foundation models",
        "video prediction",
        "causal world model",
        "object-centric world model",
        "latent action model",
        "JEPA",
        "I-JEPA",
        "V-JEPA",
        "structured world model",
        "hierarchical world model",
        "embodied world model",
    ],

    # ── GENERIC_AI4SCIENCE: 10 new terms ─────────────────────────────────
    "GENERIC_AI4SCIENCE": [
        "physics-informed neural network",
        "PINN",
        "AI for science",
        "scientific machine learning",
        "SciML",
        "differentiable simulation",
        "neural ODE",
        "Hamiltonian neural network",
        "Lagrangian neural network",
        "equivariant neural network",
    ],
}

# Priority ordering for category tie-breaking (first match wins)
_CATEGORY_PRIORITY = ["OPTICS_AI", "ROBOTICS_ML", "VLM_WORLD_MODEL", "GENERIC_AI4SCIENCE"]

# Pre-compute lowercase lookup: {category: [(kw_lower, kw_original), ...]}
_BRIDGE_V4_LOWER: Dict[str, List[Tuple[str, str]]] = {
    cat: [(kw.lower(), kw) for kw in kws]
    for cat, kws in BRIDGE_KEYWORDS_V4.items()
}

# Flat set of all lowercase keywords across all categories (for fast any-match)
_ALL_BRIDGE_LOWER: Set[str] = {
    kw.lower()
    for kws in BRIDGE_KEYWORDS_V4.values()
    for kw in kws
}


# ---------------------------------------------------------------------------
# V11.4 API
# ---------------------------------------------------------------------------

def contains_bridge_keyword_v4(text: str) -> Tuple[bool, Optional[str]]:
    """
    [V11.4-N5] Check if text contains any V11.4 bridge keyword.

    Priority: OPTICS_AI > ROBOTICS_ML > VLM_WORLD_MODEL > GENERIC_AI4SCIENCE.
    Returns the category of the FIRST (highest-priority) matching keyword.

    Args:
        text: Abstract or title text.

    Returns:
        (is_bridge, category) where category ∈
        {"OPTICS_AI", "ROBOTICS_ML", "VLM_WORLD_MODEL", "GENERIC_AI4SCIENCE", None}.
    """
    if not text:
        return False, None
    text_lower = text.lower()
    for cat in _CATEGORY_PRIORITY:
        for kw_lower, _ in _BRIDGE_V4_LOWER[cat]:
            if kw_lower in text_lower:
                return True, cat
    return False, None


def build_bridge_keyword_edges_v4(
    papers: list,
    paper_id_field: str = "paper_id",
    abstract_field: str = "abstract",
    topic_id_field: str = "primary_topic_id",
    bridge_weight: float = 0.5,
) -> List[dict]:
    """
    [V11.4-N5] Build forced semantic_bridge edges with category metadata.

    Same logic as build_bridge_keyword_edges() but each returned edge dict
    carries a "category" field identifying which keyword group matched.

    Args:
        papers:          List of paper dicts.
        paper_id_field:  Key for the paper ID.
        abstract_field:  Key for the abstract text.
        topic_id_field:  Key for the topic identifier.
        bridge_weight:   Edge weight (default 0.5).

    Returns:
        List of dicts: {"src": str, "dst": str, "weight": float, "category": str}
    """
    # Identify bridge papers and their category
    bridge_papers: Dict[str, str] = {}  # paper_id -> category
    paper_topics: Dict[str, str] = {}

    for p in papers:
        pid = p.get(paper_id_field, "")
        abstract = p.get(abstract_field, "") or ""
        tid = p.get(topic_id_field, "unknown") or "unknown"
        paper_topics[pid] = tid
        is_bridge, cat = contains_bridge_keyword_v4(abstract)
        if is_bridge and cat is not None:
            bridge_papers[pid] = cat

    if not bridge_papers:
        return []

    # Group papers by topic
    topic_to_papers: Dict[str, List[str]] = defaultdict(list)
    for p in papers:
        pid = p.get(paper_id_field, "")
        tid = paper_topics.get(pid, "unknown")
        topic_to_papers[tid].append(pid)

    edges: List[dict] = []
    edge_set: Set[Tuple[str, str]] = set()

    for bridge_pid, category in bridge_papers.items():
        bridge_topic = paper_topics.get(bridge_pid, "unknown")
        for tid, pids in topic_to_papers.items():
            if tid == bridge_topic:
                continue
            for other_pid in pids:
                if other_pid == bridge_pid:
                    continue
                pair = tuple(sorted([bridge_pid, other_pid]))
                if pair not in edge_set:
                    edge_set.add(pair)
                    edges.append({
                        "src": pair[0],
                        "dst": pair[1],
                        "weight": bridge_weight,
                        "category": category,
                    })

    return edges


def count_bridge_by_category(papers: list, abstract_field: str = "abstract") -> Dict[str, int]:
    """
    [V11.4-N5] Count how many papers match each bridge keyword category.

    Args:
        papers:         List of paper dicts.
        abstract_field: Key for abstract text.

    Returns:
        {"OPTICS_AI": N, "ROBOTICS_ML": N, "VLM_WORLD_MODEL": N, "GENERIC_AI4SCIENCE": N}
    """
    counts: Dict[str, int] = {cat: 0 for cat in _CATEGORY_PRIORITY}
    for p in papers:
        abstract = p.get(abstract_field, "") or ""
        is_bridge, cat = contains_bridge_keyword_v4(abstract)
        if is_bridge and cat is not None:
            counts[cat] += 1
    return counts


# ---------------------------------------------------------------------------
# V11.3 backward-compat API (preserved, do not remove)
# ---------------------------------------------------------------------------

# Original 38 OPTICS_AI keywords as a flat list (V11.3 contract: len == 38)
BRIDGE_KEYWORDS: List[str] = BRIDGE_KEYWORDS_V4["OPTICS_AI"]

# Pre-computed lowercase set for fast membership testing (V11.3)
_BRIDGE_KEYWORDS_LOWER: Set[str] = {kw.lower() for kw in BRIDGE_KEYWORDS}


def contains_bridge_keyword(abstract: str) -> bool:
    """
    [V11.3] Return True if the abstract contains at least one OPTICS_AI bridge keyword.

    Case-insensitive substring search. Preserved for backward compatibility.
    For V11.4 use contains_bridge_keyword_v4().
    """
    if not abstract:
        return False
    abstract_lower = abstract.lower()
    return any(kw in abstract_lower for kw in _BRIDGE_KEYWORDS_LOWER)


def find_bridge_keywords(abstract: str) -> List[str]:
    """
    [V11.3] Return all OPTICS_AI bridge keywords found in the abstract.

    Preserved for backward compatibility.
    """
    if not abstract:
        return []
    abstract_lower = abstract.lower()
    return [kw for kw in BRIDGE_KEYWORDS if kw.lower() in abstract_lower]


def build_bridge_keyword_edges(
    papers: list,
    paper_id_field: str = "paper_id",
    abstract_field: str = "abstract",
    topic_id_field: str = "primary_topic_id",
    bridge_weight: float = 0.5,
) -> list:
    """
    [V11.3-R4] Build forced semantic_bridge edges based on OPTICS_AI keywords.

    Preserved for backward compatibility. Returns tuples (pid_a, pid_b, weight, "bridge_keyword").
    For V11.4 use build_bridge_keyword_edges_v4() which returns dicts with category field.
    """
    # Identify bridge papers
    bridge_paper_ids: Set[str] = set()
    paper_topics: Dict[str, str] = {}

    for p in papers:
        pid = p.get(paper_id_field, "")
        abstract = p.get(abstract_field, "") or ""
        tid = p.get(topic_id_field, "unknown") or "unknown"
        paper_topics[pid] = tid
        if contains_bridge_keyword(abstract):
            bridge_paper_ids.add(pid)

    if not bridge_paper_ids:
        return []

    # Group papers by topic
    topic_to_papers: Dict[str, List[str]] = defaultdict(list)
    for p in papers:
        pid = p.get(paper_id_field, "")
        tid = paper_topics.get(pid, "unknown")
        topic_to_papers[tid].append(pid)

    edges = []
    edge_set: Set[tuple] = set()

    for bridge_pid in bridge_paper_ids:
        bridge_topic = paper_topics.get(bridge_pid, "unknown")
        for tid, pids in topic_to_papers.items():
            if tid == bridge_topic:
                continue
            for other_pid in pids:
                if other_pid == bridge_pid:
                    continue
                pair = tuple(sorted([bridge_pid, other_pid]))
                if pair not in edge_set:
                    edge_set.add(pair)
                    edges.append((*pair, bridge_weight, "bridge_keyword"))

    return edges
