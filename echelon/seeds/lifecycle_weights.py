"""
V13: 9-signal lifecycle adaptive weights + keystone_score_v6.

Replaces pure geometric mean (susceptible to 0.5 placeholder pollution) with:
  1. Lifecycle-adaptive weights (fresh/growing/mature based on paper age)
  2. Weighted harmonic mean for positive signals (sensitive to very low values,
     insensitive to neutral 0.5 placeholders)
  3. Additive penalty for c_review_filter (negative weight)
  4. None-signal skipping (not 0.5 imputation)

Design rationale:
  - Geometric mean: 0.5 placeholder pulls score toward 0.5 even when real signals
    disagree. N4 problem: top-10 papers get similar scores ~0.55-0.65.
  - Harmonic mean: a single very low value (e.g. 0.05) will drag the result down
    significantly, but neutral 0.5 values don't dominate the aggregate.
  - None vs 0.5: signals not yet computable (new paper) are excluded from the
    average entirely, rather than counting as neutral placeholders.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Dict, Literal, Optional

# ---------------------------------------------------------------------------
# Lifecycle weight tables
# ---------------------------------------------------------------------------

LifecycleStage = Literal["fresh", "growing", "mature"]

LIFECYCLE_WEIGHTS: Dict[LifecycleStage, Dict[str, float]] = {
    "fresh": {  # < 6 months
        "c_recency": 0.20,
        "c_venue": 0.10,
        "c_team_disrupt": 0.15,
        "c_recent_burst": 0.00,      # no burst signal yet
        "c_review_filter": -0.10,    # penalty weight
        "c_bib_breadth": 0.15,
        "c_cocite_breadth": 0.00,    # no forward citations yet
        "c_bridging_centrality": 0.10,
        "c_cd_subdomain": 0.00,      # no CD index yet
        "c_semantic_outlier": 0.10,
        "c_breakthrough_lang": 0.15,
        "c_mechanism_novelty": 0.15,
    },
    "growing": {  # 6 months – 3 years
        "c_recency": 0.15,
        "c_venue": 0.10,
        "c_team_disrupt": 0.10,
        "c_recent_burst": 0.10,
        "c_review_filter": -0.10,
        "c_bib_breadth": 0.20,
        "c_cocite_breadth": 0.05,
        "c_bridging_centrality": 0.15,
        "c_cd_subdomain": 0.00,      # CD index needs 3 years
        "c_semantic_outlier": 0.15,
        "c_breakthrough_lang": 0.10,
        "c_mechanism_novelty": 0.10,
    },
    "mature": {  # > 3 years
        "c_recency": 0.05,
        "c_venue": 0.05,
        "c_team_disrupt": 0.05,
        "c_recent_burst": 0.05,
        "c_review_filter": -0.10,
        "c_bib_breadth": 0.10,
        "c_cocite_breadth": 0.15,
        "c_bridging_centrality": 0.15,
        "c_cd_subdomain": 0.20,      # CD index fully available
        "c_semantic_outlier": 0.10,
        "c_breakthrough_lang": 0.05,
        "c_mechanism_novelty": 0.05,
    },
}

# All 12 known signal names
ALL_SIGNALS = list(LIFECYCLE_WEIGHTS["fresh"].keys())


def determine_lifecycle(paper, today: Optional[date] = None) -> LifecycleStage:
    """
    Determine lifecycle stage based on paper age.

    Args:
        paper:  Object with ``publication_date`` attribute (datetime.date).
                Also accepts dict with "publication_date" key.
        today:  Reference date (default: date.today()).

    Returns:
        "fresh"   if age < 6 months
        "growing" if 6 months ≤ age < 3 years
        "mature"  if age ≥ 3 years

    Examples:
        >>> from datetime import date, timedelta
        >>> class P:
        ...     publication_date = date.today() - timedelta(days=30)
        >>> determine_lifecycle(P())
        'fresh'
    """
    if today is None:
        today = date.today()

    if isinstance(paper, dict):
        pub_date = paper.get("publication_date")
    else:
        pub_date = getattr(paper, "publication_date", None)

    if pub_date is None:
        return "growing"  # conservative default: no data → growing

    age_days = (today - pub_date).days
    age_months = age_days / 30.4375  # average days per month

    if age_months < 6:
        return "fresh"
    elif age_months < 36:
        return "growing"
    else:
        return "mature"


def _safe_clip_v6(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clip value to [lo, hi]. Used internally in v6."""
    return max(lo, min(hi, float(v)))


def keystone_score_v6(
    signals: Dict[str, Optional[float]],
    paper,
    today: Optional[date] = None,
) -> float:
    """
    V13: Lifecycle-adaptive weighted harmonic mean KeystoneScore.

    Key improvements over v5:
      1. None signals are SKIPPED (not imputed as 0.5 placeholders).
      2. Lifecycle-adaptive weights: fresh/growing/mature papers use
         different weight profiles reflecting what signals are meaningful.
      3. Weighted harmonic mean (positive signals):
         H_w = (Σ w_i) / (Σ w_i / (x_i + ε))
         where ε=0.5 prevents division issues and dampens 0.5 neutrality.
         Final score = H_w - ε + additive penalty for c_review_filter.
      4. Signals with weight=0 in current lifecycle are skipped.

    Formula for positive signals:
        H_w = W_total / Σ(w_i / (x_i + 0.5))

    where W_total = Σ w_i for non-None positive-weight signals.

    Final score:
        score = clip(H_w - 0.5 + neg_penalty)

    Args:
        signals: Dict mapping signal name → value (None = not computed yet).
                 Example: {"c_recency": 0.8, "c_cd_subdomain": None, ...}
        paper:   Paper object or dict with publication_date.
        today:   Reference date (default: date.today()).

    Returns:
        KeystoneScore ∈ [0.0, 1.0]

    Examples:
        >>> from datetime import date, timedelta
        >>> class P:
        ...     publication_date = date(2020, 1, 1)
        >>> sigs = {
        ...     "c_recency": 0.8, "c_venue": 0.7, "c_team_disrupt": 0.9,
        ...     "c_recent_burst": 0.6, "c_review_filter": 0.0,
        ...     "c_bib_breadth": 0.7, "c_cocite_breadth": None,
        ...     "c_bridging_centrality": 0.65, "c_cd_subdomain": None,
        ...     "c_semantic_outlier": 0.75, "c_breakthrough_lang": 0.8,
        ...     "c_mechanism_novelty": 0.85,
        ... }
        >>> score = keystone_score_v6(sigs, P())
        >>> 0.0 <= score <= 1.0
        True
    """
    if today is None:
        today = date.today()

    lifecycle = determine_lifecycle(paper, today=today)
    weights = LIFECYCLE_WEIGHTS[lifecycle]

    # Separate positive-weight signals from penalty signals
    # Skip: weight == 0 OR value is None
    pos_signals: Dict[str, float] = {}
    neg_penalty_total: float = 0.0

    for key, weight in weights.items():
        val = signals.get(key)
        if val is None:
            continue  # skip — not yet computable, not 0.5 placeholder
        if weight == 0.0:
            continue  # skip — not meaningful in this lifecycle stage

        val_clipped = _safe_clip_v6(float(val))

        if weight > 0:
            pos_signals[key] = val_clipped
        else:
            # Negative weight: additive penalty
            # c_review_filter=1.0 (is a review) → penalty = -0.10 * 1.0 = -0.10
            neg_penalty_total += weight * val_clipped  # weight < 0, so this subtracts

    # Edge case: no positive signals at all
    if not pos_signals:
        result = 0.5 + neg_penalty_total
        return _safe_clip_v6(result)

    # Weighted harmonic mean with ε=0.5 smoothing
    # H_w = W_total / Σ(w_i / (x_i + 0.5))
    EPSILON = 0.5
    pos_weights = {k: weights[k] for k in pos_signals}
    w_total = sum(pos_weights.values())

    denominator = sum(
        pos_weights[k] / (pos_signals[k] + EPSILON)
        for k in pos_signals
    )

    if denominator <= 0:
        return _safe_clip_v6(0.5 + neg_penalty_total)

    harmonic = w_total / denominator

    # Invert ε offset: harmonic ∈ (0, 1.5], subtract ε=0.5 to center around 0
    # When all signals = 0.5 (neutral): harmonic ≈ 0.5+ε=1.0, harmonic-ε=0.5 ✓
    # When all signals = 1.0 (best):    harmonic > 1.0, harmonic-ε > 0.5 ✓
    # When all signals = 0.0 (worst):   harmonic ≈ w_total/(w_total/0.5)=0.5, -ε=0.0 ✓
    score = harmonic - EPSILON + neg_penalty_total
    return _safe_clip_v6(score)


def keystone_score_v6_explain(
    signals: Dict[str, Optional[float]],
    paper,
    today: Optional[date] = None,
) -> Dict:
    """
    Same as keystone_score_v6 but returns an explanation dict.

    Returns:
        {
            "score": float,
            "lifecycle": str,
            "active_signals": dict,
            "skipped_none": list,
            "skipped_zero_weight": list,
            "neg_penalty": float,
        }
    """
    if today is None:
        today = date.today()

    lifecycle = determine_lifecycle(paper, today=today)
    weights = LIFECYCLE_WEIGHTS[lifecycle]

    skipped_none = []
    skipped_zero = []
    pos_signals: Dict[str, float] = {}
    neg_penalty_total: float = 0.0

    for key, weight in weights.items():
        val = signals.get(key)
        if val is None:
            skipped_none.append(key)
            continue
        if weight == 0.0:
            skipped_zero.append(key)
            continue

        val_clipped = _safe_clip_v6(float(val))

        if weight > 0:
            pos_signals[key] = val_clipped
        else:
            neg_penalty_total += weight * val_clipped

    score = keystone_score_v6(signals, paper, today=today)

    return {
        "score": score,
        "lifecycle": lifecycle,
        "active_signals": pos_signals,
        "skipped_none": skipped_none,
        "skipped_zero_weight": skipped_zero,
        "neg_penalty": neg_penalty_total,
    }
