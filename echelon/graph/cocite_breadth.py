"""
V13: c_cocite_breadth — forward citation cross-topic entropy.

Measures how broadly a paper is cited across different research topics.
High entropy = cited across many diverse topics = higher bridging impact.

Formula:
  H(topics) = -Σ p_i * log(p_i)    (Shannon entropy, natural log)
  H_max = log(n_total_topics)
  c_cocite_breadth = H / H_max      ∈ [0, 1]

Availability:
  - Only for publication_year <= now-2 (needs ≥2 years to accumulate citations)
  - Newer papers → return None (skip in weighted average)
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import date
from typing import Dict, List, Optional


def compute_cocite_breadth(
    focal_paper_id: str,
    citing_papers_topics: List[Dict],
    n_total_topics: Optional[int] = None,
    publication_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[float]:
    """
    Compute forward citation cross-topic normalized Shannon entropy.

    Args:
        focal_paper_id:       ID of the focal paper (for logging/dedup).
        citing_papers_topics: List of dicts, each with:
                                - "id":    citing paper ID
                                - "topic": topic label (str or int)
        n_total_topics:       Total number of known topics in the corpus.
                              If None, uses the number of unique topics observed.
        publication_year:     Publication year for the 2-year guard.
        today:                Reference date (default: date.today()).

    Returns:
        Normalized entropy ∈ [0.0, 1.0], or None if paper is too recent.
        0.0 = all citations from same topic (no breadth)
        1.0 = citations perfectly spread across all topics

    Examples:
        >>> papers = [
        ...     {"id": "C1", "topic": "physics"},
        ...     {"id": "C2", "topic": "chemistry"},
        ...     {"id": "C3", "topic": "biology"},
        ...     {"id": "C4", "topic": "physics"},
        ... ]
        >>> result = compute_cocite_breadth("F", papers, n_total_topics=4,
        ...                                 publication_year=2018)
        >>> 0.0 <= result <= 1.0
        True
    """
    if today is None:
        today = date.today()

    # 2-year guard
    if publication_year is not None:
        age_years = today.year - publication_year
        if age_years < 2:
            return None

    if not citing_papers_topics:
        return 0.0  # no forward citations → zero breadth

    # Count topic distribution (dedup by citing paper ID)
    seen_ids = set()
    topic_counts: Counter = Counter()
    for paper in citing_papers_topics:
        pid = paper.get("id", "")
        topic = paper.get("topic")
        if topic is None:
            continue
        if pid and pid in seen_ids:
            continue
        if pid:
            seen_ids.add(pid)
        topic_counts[str(topic)] += 1

    if not topic_counts:
        return 0.0

    total = sum(topic_counts.values())
    if total == 0:
        return 0.0

    # Shannon entropy H = -Σ p_i * log(p_i)
    entropy = 0.0
    for count in topic_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log(p)

    # Determine H_max
    if n_total_topics is not None and n_total_topics > 1:
        h_max = math.log(n_total_topics)
    else:
        # Use observed unique topics
        n_obs = len(topic_counts)
        if n_obs <= 1:
            return 0.0
        h_max = math.log(n_obs)

    if h_max <= 0:
        return 0.0

    return min(1.0, entropy / h_max)


def compute_cocite_breadth_from_raw(
    focal_paper_id: str,
    topic_distribution: Dict[str, int],
    n_total_topics: Optional[int] = None,
    publication_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[float]:
    """
    Compute cocite breadth directly from a pre-aggregated topic distribution.

    Convenience function when topic counts are already computed externally.

    Args:
        focal_paper_id:     ID of the focal paper.
        topic_distribution: Dict mapping topic_label → citation_count.
        n_total_topics:     Total topics in corpus (for H_max normalization).
        publication_year:   For the 2-year guard.
        today:              Reference date.

    Returns:
        Normalized entropy ∈ [0.0, 1.0], or None if too recent.

    Examples:
        >>> dist = {"ML": 10, "Physics": 5, "Chemistry": 5}
        >>> result = compute_cocite_breadth_from_raw("F", dist,
        ...     n_total_topics=10, publication_year=2018)
        >>> 0.0 <= result <= 1.0
        True
    """
    if today is None:
        today = date.today()

    if publication_year is not None:
        age_years = today.year - publication_year
        if age_years < 2:
            return None

    if not topic_distribution:
        return 0.0

    total = sum(topic_distribution.values())
    if total == 0:
        return 0.0

    entropy = 0.0
    for count in topic_distribution.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log(p)

    if n_total_topics is not None and n_total_topics > 1:
        h_max = math.log(n_total_topics)
    else:
        n_obs = len(topic_distribution)
        if n_obs <= 1:
            return 0.0
        h_max = math.log(n_obs)

    if h_max <= 0:
        return 0.0

    return min(1.0, entropy / h_max)
