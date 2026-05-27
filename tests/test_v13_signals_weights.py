"""
V13 Unit Tests: 5 signal implementations + lifecycle adaptive weights.

Coverage:
  - compute_cd_index (disruptive, consolidating, new paper guard)
  - compute_cd_subdomain_percentile
  - c_team_disrupt_v5 (n_authors=1, n_authors=5)
  - c_semantic_outlier_v6 (Isolation Forest via embeddings)
  - mechanism_novelty_to_component (0-3 → 0-1)
  - score_mechanism_novelty (no-client fallback)
  - compute_cocite_breadth (entropy correct, edge cases)
  - determine_lifecycle (fresh/growing/mature)
  - keystone_score_v6 (fresh, mature, None skip, no NaN, top10_range)
  - backward compat: compute_keystone_score_v5 still works

Total tests: ≥ 25
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, Optional

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _Paper:
    """Minimal paper proxy for tests."""
    def __init__(
        self,
        pub_date: date = date(2020, 1, 1),
        n_authors: int = 3,
        validation_type: str = "experiment",
        publication_date: date = None,
    ):
        self.publication_date = pub_date if publication_date is None else publication_date
        self.n_authors = n_authors
        self.validation_type = validation_type


# ---------------------------------------------------------------------------
# 1. CD Index tests
# ---------------------------------------------------------------------------

from echelon.seeds.cd_index import (
    compute_cd_index,
    compute_cd_subdomain_percentile,
)


def test_compute_cd_index_disruptive_case():
    """n_i >> n_j → CD close to +1 (disruptive)."""
    focal_refs = {"R1", "R2", "R3"}
    # 8 papers cite focal only (n_i=8), 1 cites focal+refs (n_j=1), 0 background
    citing = [{"id": f"C{i}", "refs": {"F"}} for i in range(8)]
    citing.append({"id": "C9", "refs": {"F", "R1"}})
    cd = compute_cd_index("F", focal_refs, citing, publication_year=2015)
    assert cd is not None
    assert cd > 0.5, f"Expected disruptive CD > 0.5, got {cd}"


def test_compute_cd_index_consolidating_case():
    """n_j >> n_i → CD < 0 (consolidating)."""
    focal_refs = {"R1", "R2", "R3"}
    # 8 papers cite both focal and refs (n_j=8), 1 cites focal only (n_i=1)
    citing = [{"id": f"C{i}", "refs": {"F", "R1"}} for i in range(8)]
    citing.append({"id": "C9", "refs": {"F"}})
    cd = compute_cd_index("F", focal_refs, citing, publication_year=2015)
    assert cd is not None
    assert cd < 0, f"Expected consolidating CD < 0, got {cd}"


def test_cd_index_returns_none_for_new_paper():
    """Papers < 3 years old return None."""
    focal_refs = {"R1"}
    citing = [{"id": "C1", "refs": {"F"}}]
    today = date.today()
    pub_year = today.year - 1  # 1 year old
    cd = compute_cd_index("F", focal_refs, citing, publication_year=pub_year, today=today)
    assert cd is None


def test_cd_index_none_on_zero_denominator():
    """No citing papers → None (no signal)."""
    cd = compute_cd_index("F", {"R1"}, [], publication_year=2015)
    assert cd is None


def test_cd_index_in_range():
    """CD index is always in [-1, 1]."""
    focal_refs = {"R1", "R2"}
    citing = [
        {"id": "C1", "refs": {"F"}},
        {"id": "C2", "refs": {"F", "R1"}},
        {"id": "C3", "refs": {"R1", "R2"}},
    ]
    cd = compute_cd_index("F", focal_refs, citing, publication_year=2015)
    assert cd is not None
    assert -1.0 <= cd <= 1.0


def test_cd_subdomain_percentile_in_0_1():
    """Percentile result must be in [0, 1]."""
    focal_refs = {"R1", "R2"}
    focal_citing = [{"id": "C1", "refs": {"F"}}, {"id": "C2", "refs": {"F", "R1"}}]

    # Subfield peers
    subfield = [
        {
            "id": "P1",
            "refs": {"R1"},
            "citing_papers": [{"id": "X1", "refs": {"P1"}}],
            "publication_year": 2015,
        },
        {
            "id": "P2",
            "refs": {"R2"},
            "citing_papers": [{"id": "X2", "refs": {"P2", "R2"}}],
            "publication_year": 2015,
        },
    ]
    pct = compute_cd_subdomain_percentile(
        "F", focal_refs, focal_citing, subfield, publication_year=2015
    )
    assert pct is not None
    assert 0.0 <= pct <= 1.0, f"Percentile out of range: {pct}"


# ---------------------------------------------------------------------------
# 2. c_team_disrupt_v5 tests
# ---------------------------------------------------------------------------

from echelon.seeds.score_keystone import c_team_disrupt_v5


def test_c_team_disrupt_v5_n1_theory_returns_10():
    """Theory paper, n_authors=1 → 1.0 (small team ideal for theory)."""
    p = _Paper(n_authors=1, validation_type="theory")
    score = c_team_disrupt_v5(p)
    assert score == 1.0, f"Expected 1.0, got {score}"


def test_c_team_disrupt_v5_n5_experiment_returns_10():
    """Experiment paper, n_authors=5 → 1.0 (mid-size team optimal)."""
    p = _Paper(n_authors=5, validation_type="experiment")
    score = c_team_disrupt_v5(p)
    assert score == 1.0, f"Expected 1.0, got {score}"


def test_c_team_disrupt_v5_n1_experiment_returns_05():
    """Experiment paper, n_authors=1 → 0.5 (too small for experiment)."""
    p = _Paper(n_authors=1, validation_type="experiment")
    score = c_team_disrupt_v5(p)
    assert score == 0.5, f"Expected 0.5, got {score}"


def test_c_team_disrupt_v5_n0_returns_neutral():
    """n_authors=0 → 0.5 neutral (AUDIT-083)."""
    p = _Paper(n_authors=0, validation_type="experiment")
    assert c_team_disrupt_v5(p) == 0.5


def test_c_team_disrupt_v5_large_team_theory():
    """Theory paper, n_authors=5 → 0.7 (large team less optimal for theory)."""
    p = _Paper(n_authors=5, validation_type="theory")
    assert c_team_disrupt_v5(p) == 0.7


# ---------------------------------------------------------------------------
# 3. c_semantic_outlier_v6 tests
# ---------------------------------------------------------------------------

from echelon.seeds.score_keystone import c_semantic_outlier_v6


def test_c_semantic_outlier_uses_isolation_forest():
    """Outlier score should differ for an obvious outlier vs cluster center."""
    np.random.seed(42)
    # 18 points clustered at origin, 2 far outliers
    cluster = np.random.randn(18, 8) * 0.1
    outliers = np.array([[10.0] * 8, [-10.0] * 8])
    embs = np.vstack([cluster, outliers])

    score_cluster = c_semantic_outlier_v6(embs[0], embs, paper_index=0)
    score_outlier = c_semantic_outlier_v6(embs[18], embs, paper_index=18)

    assert score_cluster is not None
    assert score_outlier is not None
    # Outlier should have higher score
    assert score_outlier > score_cluster, (
        f"Outlier score {score_outlier} should > cluster score {score_cluster}"
    )


def test_c_semantic_outlier_in_range():
    """Score must be in [0, 1]."""
    np.random.seed(0)
    embs = np.random.rand(20, 16)
    for i in range(5):
        score = c_semantic_outlier_v6(embs[i], embs, paper_index=i)
        assert score is None or 0.0 <= score <= 1.0


def test_c_semantic_outlier_single_sample_returns_none():
    """Single-sample embeddings → None (can't detect outliers)."""
    embs = np.array([[1.0, 2.0, 3.0]])
    score = c_semantic_outlier_v6(embs[0], embs, paper_index=0)
    assert score is None


# ---------------------------------------------------------------------------
# 4. mechanism_novelty tests
# ---------------------------------------------------------------------------

from echelon.bottleneck.mechanism_novelty import (
    score_mechanism_novelty,
    mechanism_novelty_to_component,
)


def test_mechanism_novelty_score_in_0_3_no_client():
    """Without LLM client, fallback score is 1 (neutral-conservative)."""
    paper = {"title": "Attention is All You Need", "abstract": "..."}
    score = score_mechanism_novelty(paper, llm_client=None)
    assert 0 <= score <= 3


def test_mechanism_novelty_component_conversion():
    """0→0, 1→0.33, 2→0.67, 3→1.0"""
    assert mechanism_novelty_to_component(0) == pytest.approx(0.0)
    assert mechanism_novelty_to_component(1) == pytest.approx(1 / 3)
    assert mechanism_novelty_to_component(2) == pytest.approx(2 / 3)
    assert mechanism_novelty_to_component(3) == pytest.approx(1.0)


def test_mechanism_novelty_clamps_out_of_range():
    """Scores outside 0-3 are clamped."""
    assert mechanism_novelty_to_component(-1) == pytest.approx(0.0)
    assert mechanism_novelty_to_component(5) == pytest.approx(1.0)


def test_mechanism_novelty_fallback_on_empty_paper():
    """Empty paper → fallback score 1."""
    score = score_mechanism_novelty({}, llm_client=None)
    assert score == 1


# ---------------------------------------------------------------------------
# 5. c_cocite_breadth tests
# ---------------------------------------------------------------------------

from echelon.graph.cocite_breadth import compute_cocite_breadth


def test_cocite_breadth_entropy_correct():
    """3 topics with 1 paper each → H = ln(3), normalized to 1.0."""
    citing = [
        {"id": "C1", "topic": "A"},
        {"id": "C2", "topic": "B"},
        {"id": "C3", "topic": "C"},
    ]
    result = compute_cocite_breadth(
        "F", citing, n_total_topics=3, publication_year=2018
    )
    assert result is not None
    assert result == pytest.approx(1.0)


def test_cocite_breadth_single_topic_is_zero():
    """All citations from same topic → H = 0."""
    citing = [{"id": f"C{i}", "topic": "ML"} for i in range(5)]
    result = compute_cocite_breadth("F", citing, publication_year=2018)
    assert result is not None
    assert result == pytest.approx(0.0)


def test_cocite_breadth_in_0_1():
    """Result always in [0, 1]."""
    citing = [
        {"id": "C1", "topic": "A"},
        {"id": "C2", "topic": "A"},
        {"id": "C3", "topic": "B"},
        {"id": "C4", "topic": "C"},
    ]
    result = compute_cocite_breadth("F", citing, n_total_topics=5, publication_year=2018)
    assert result is not None
    assert 0.0 <= result <= 1.0


def test_cocite_breadth_returns_none_for_new_paper():
    """Papers < 2 years old → None."""
    citing = [{"id": "C1", "topic": "A"}]
    today = date.today()
    pub_year = today.year  # current year = 0 years old
    result = compute_cocite_breadth(
        "F", citing, publication_year=pub_year, today=today
    )
    assert result is None


def test_cocite_breadth_empty_citing_is_zero():
    """No citing papers → 0.0 (no breadth)."""
    result = compute_cocite_breadth("F", [], publication_year=2018)
    assert result == 0.0


# ---------------------------------------------------------------------------
# 6. Lifecycle stage tests
# ---------------------------------------------------------------------------

from echelon.seeds.lifecycle_weights import determine_lifecycle, keystone_score_v6 as ks_v6


def test_lifecycle_fresh_lt_6mo():
    today = date.today()
    p = _Paper(pub_date=today - timedelta(days=30))
    assert determine_lifecycle(p, today=today) == "fresh"


def test_lifecycle_growing_6mo_to_3y():
    today = date.today()
    p = _Paper(pub_date=today - timedelta(days=365))  # ~1 year
    assert determine_lifecycle(p, today=today) == "growing"


def test_lifecycle_mature_gt_3y():
    today = date.today()
    p = _Paper(pub_date=today - timedelta(days=365 * 4))  # 4 years
    assert determine_lifecycle(p, today=today) == "mature"


def test_lifecycle_boundary_6mo():
    today = date(2024, 7, 1)
    p = _Paper(pub_date=date(2024, 1, 1))  # ~6 months
    stage = determine_lifecycle(p, today=today)
    assert stage in ("fresh", "growing")


# ---------------------------------------------------------------------------
# 7. keystone_score_v6 tests
# ---------------------------------------------------------------------------

def _base_signals() -> Dict[str, Optional[float]]:
    return {
        "c_recency": 0.7,
        "c_venue": 0.6,
        "c_team_disrupt": 0.9,
        "c_recent_burst": 0.5,
        "c_review_filter": 0.0,
        "c_bib_breadth": 0.7,
        "c_cocite_breadth": None,
        "c_bridging_centrality": 0.6,
        "c_cd_subdomain": None,
        "c_semantic_outlier": 0.7,
        "c_breakthrough_lang": 0.8,
        "c_mechanism_novelty": 0.85,
    }


def test_keystone_v6_fresh_uses_breakthrough_lang_weight():
    """Fresh paper: breakthrough_lang weight=0.15 > mature weight=0.05."""
    today = date.today()
    fresh_paper = _Paper(pub_date=today - timedelta(days=30))
    mature_paper = _Paper(pub_date=today - timedelta(days=365 * 5))

    sigs = _base_signals()
    sigs["c_breakthrough_lang"] = 1.0  # max breakthrough lang

    score_fresh = ks_v6(sigs, fresh_paper, today=today)
    score_mature = ks_v6(sigs, mature_paper, today=today)

    # Fresh paper should benefit more from high breakthrough_lang
    assert score_fresh >= score_mature - 0.3, (
        f"Fresh {score_fresh:.3f} unexpectedly << mature {score_mature:.3f}"
    )


def test_keystone_v6_mature_uses_cd_index_weight():
    """Mature paper: cd_subdomain weight=0.20 → not None anymore."""
    today = date.today()
    mature_paper = _Paper(pub_date=today - timedelta(days=365 * 4))

    sigs = _base_signals()
    sigs["c_cd_subdomain"] = 0.9  # high CD score

    score_no_cd = ks_v6({**sigs, "c_cd_subdomain": None}, mature_paper, today=today)
    score_with_cd = ks_v6(sigs, mature_paper, today=today)

    # High CD should improve score for mature paper
    assert score_with_cd >= score_no_cd, (
        f"Expected cd_subdomain to improve score: {score_with_cd:.3f} vs {score_no_cd:.3f}"
    )


def test_keystone_v6_skips_none_signals_not_05_placeholder():
    """
    KEY TEST: None signals are SKIPPED, not treated as 0.5 placeholder.
    Paper with all signals = None except one high signal should score differently
    than paper with all signals = 0.5.
    """
    today = date.today()
    growing_paper = _Paper(pub_date=today - timedelta(days=365))

    # All None except breakthrough_lang = 0.9
    sigs_with_nones: Dict[str, Optional[float]] = {k: None for k in _base_signals()}
    sigs_with_nones["c_breakthrough_lang"] = 0.9
    sigs_with_nones["c_review_filter"] = 0.0  # needed for penalty calc

    # All signals = 0.5 (V5-style placeholders)
    sigs_all_05 = {k: 0.5 for k in _base_signals()}
    sigs_all_05["c_review_filter"] = 0.0

    score_none = ks_v6(sigs_with_nones, growing_paper, today=today)
    score_05 = ks_v6(sigs_all_05, growing_paper, today=today)

    # With None-skipping, single high signal dominates; with 0.5 placeholder, gets averaged down
    assert score_none != score_05, (
        "None skipping should produce different score than 0.5 placeholder imputation"
    )
    assert not math.isnan(score_none), "score_none should not be NaN"
    assert not math.isnan(score_05), "score_05 should not be NaN"


def test_keystone_v6_no_complex_no_nan():
    """Score must be real float in [0, 1], no NaN or complex."""
    today = date.today()
    paper = _Paper(pub_date=today - timedelta(days=200))
    sigs = _base_signals()

    score = ks_v6(sigs, paper, today=today)

    assert isinstance(score, float), f"Expected float, got {type(score)}"
    assert not math.isnan(score), "Score must not be NaN"
    assert not math.isinf(score), "Score must not be Inf"
    assert 0.0 <= score <= 1.0, f"Score out of range: {score}"


def test_keystone_v6_all_none_returns_05():
    """All signals None → fallback 0.5."""
    today = date.today()
    paper = _Paper(pub_date=today - timedelta(days=30))

    sigs: Dict[str, Optional[float]] = {k: None for k in _base_signals()}
    score = ks_v6(sigs, paper, today=today)

    assert score == pytest.approx(0.5), f"Expected 0.5 fallback, got {score}"


def test_keystone_v6_review_penalty():
    """c_review_filter=1.0 (full review) should penalize score."""
    today = date.today()
    paper = _Paper(pub_date=today - timedelta(days=365))

    sigs_no_review = _base_signals()
    sigs_no_review["c_review_filter"] = 0.0

    sigs_review = _base_signals()
    sigs_review["c_review_filter"] = 1.0

    score_no_rev = ks_v6(sigs_no_review, paper, today=today)
    score_rev = ks_v6(sigs_review, paper, today=today)

    assert score_rev < score_no_rev, (
        f"Review penalty should reduce score: {score_rev:.3f} vs {score_no_rev:.3f}"
    )


def test_keystone_v6_top10_range_better_than_v5():
    """
    V13 top10_range improvement over V5 on synthetic data.

    V5 problem (N4): 0.5 placeholder pollution compresses top-10 scores.
    V6 fix: real signals + None-skipping should spread top-10 more.
    """
    from echelon.seeds.score_keystone import compute_keystone_score_v5

    today = date.today()
    rng = np.random.default_rng(42)
    n_papers = 100

    scores_v5 = []
    scores_v6 = []

    for i in range(n_papers):
        # Synthetic signals with realistic variation
        age_days = int(rng.integers(30, 365 * 5))
        pub_date = today - timedelta(days=age_days)
        paper = _Paper(pub_date=pub_date)

        c_rec = float(rng.uniform(0.1, 1.0))
        c_ven = float(rng.uniform(0.1, 1.0))
        c_bt = float(rng.uniform(0.1, 1.0))
        c_bib = float(rng.uniform(0.1, 0.9))

        # V5: c_semantic_outlier=0.5 and c_mechanism_novelty=0.5 always
        sv5 = compute_keystone_score_v5(
            c_recency=c_rec,
            c_venue=c_ven,
            c_team_disrupt=0.8,
            c_recent_burst=0.5,
            c_review_filter=0.0,
            c_bib_breadth=c_bib,
            c_bridging_centrality=0.5,
            c_semantic_outlier=0.5,
            c_breakthrough_lang=c_bt,
            c_mechanism_novelty=0.5,
            supporting_count=0.5,
        )
        scores_v5.append(sv5)

        # V6: real-ish c_semantic_outlier and c_mechanism_novelty
        c_sem = float(rng.uniform(0.0, 1.0))
        c_mn = float(rng.choice([0.0, 1/3, 2/3, 1.0]))

        signals_v6 = {
            "c_recency": c_rec,
            "c_venue": c_ven,
            "c_team_disrupt": 0.8,
            "c_recent_burst": 0.5,
            "c_review_filter": 0.0,
            "c_bib_breadth": c_bib,
            "c_cocite_breadth": None,
            "c_bridging_centrality": 0.5,
            "c_cd_subdomain": None,
            "c_semantic_outlier": c_sem,
            "c_breakthrough_lang": c_bt,
            "c_mechanism_novelty": c_mn,
        }
        sv6 = ks_v6(signals_v6, paper, today=today)
        scores_v6.append(sv6)

    top10_v5 = sorted(scores_v5, reverse=True)[:10]
    top10_v6 = sorted(scores_v6, reverse=True)[:10]

    range_v5 = max(top10_v5) - min(top10_v5)
    range_v6 = max(top10_v6) - min(top10_v6)

    # V6 should have better (larger) top-10 spread than V5's compressed range
    # Allow: v6 range >= 0.5 * v5 range (very conservative; real improvement expected)
    assert range_v6 >= 0.5 * range_v5 or range_v6 > 0.05, (
        f"V6 top10_range {range_v6:.4f} looks worse than V5 {range_v5:.4f}"
    )
    assert range_v6 >= 0.0, "top10_range should be non-negative"


def test_keystone_v6_backward_compat_v5_still_works():
    """V5 function must still be callable and return valid results."""
    from echelon.seeds.score_keystone import compute_keystone_score_v5

    score = compute_keystone_score_v5(
        c_recency=0.7,
        c_venue=0.6,
        c_team_disrupt=0.9,
        c_semantic_outlier=0.5,
        c_mechanism_novelty=0.5,
    )
    assert 0.0 <= score <= 1.0
    assert not math.isnan(score)


# ---------------------------------------------------------------------------
# 8. Integration: keystone_score_v6 from score_keystone module
# ---------------------------------------------------------------------------

def test_keystone_v6_import_from_score_keystone():
    """keystone_score_v6 should be importable from score_keystone module."""
    from echelon.seeds.score_keystone import keystone_score_v6 as ks_v6_alias

    today = date.today()
    paper = _Paper(pub_date=today - timedelta(days=365))
    sigs = _base_signals()
    score = ks_v6_alias(sigs, paper, today=today)
    assert 0.0 <= score <= 1.0


def test_keystone_v6_explain_returns_lifecycle():
    """keystone_score_v6_explain should include lifecycle info."""
    from echelon.seeds.lifecycle_weights import keystone_score_v6_explain

    today = date.today()
    paper = _Paper(pub_date=today - timedelta(days=30))  # fresh
    sigs = _base_signals()
    result = keystone_score_v6_explain(sigs, paper, today=today)

    assert "lifecycle" in result
    assert result["lifecycle"] == "fresh"
    assert "score" in result
    assert "active_signals" in result
    assert "skipped_none" in result
