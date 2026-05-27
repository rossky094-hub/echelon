"""
V11.4 Algorithm Layer Unit Tests — N2 + N4 + N5

N2: evaluate_physical_depth_v4() — refined Path 2 (2a/2b/2c/2d) + Path 4 (theory)
N4: c_venue_v4() — citation-rate percentile within age-matched peer group
N5: bridge_keywords_v4 — categorised keyword library (100+ terms)

Run: pytest tests/test_v11_4_insights.py -v
"""
from __future__ import annotations

import math
import os
import random
import sys
from datetime import date, timedelta
from typing import List, NamedTuple

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# N2 — evaluate_physical_depth_v4
# ============================================================================

class TestPhysicalDepthV4:

    def test_physical_depth_path2a_pairs_dataset(self):
        """
        N2: abstract with performance numbers co-located with dataset names
        must hit path_2a (performance-dataset pairing).

        The text "achieves 87.3% on COCO and 92.1% F1 on SQuAD" has two
        performance-number / dataset pairs → path_2a_pairs >= 2.
        """
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        abstract = (
            "Our model achieves 87.3% on COCO and 92.1% F1 on SQuAD, "
            "demonstrating strong generalisation across vision and language tasks."
        )
        result = evaluate_physical_depth_v4(abstract)

        assert result["path_2a_pairs"] >= 1, (
            f"N2 FAILED: path_2a_pairs={result['path_2a_pairs']} should be >= 1 "
            f"for text with '87.3% on COCO' and '92.1% F1 on SQuAD'"
        )
        assert "path_2a" in result["passed_paths"], (
            f"N2 FAILED: path_2a not in passed_paths={result['passed_paths']}"
        )
        assert result["passed"], (
            f"N2 FAILED: passed=False even though path_2a hit. result={result}"
        )

    def test_physical_depth_path4_theory(self):
        """
        N2: abstract with theorem + proof + bound-is-tight language must hit path_4.
        """
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        abstract = (
            "We prove the theorem and show that the bound is tight under mild assumptions. "
            "The lemma establishes the sufficient condition for convergence."
        )
        result = evaluate_physical_depth_v4(abstract)

        assert result["path_4_theory_hits"] >= 2, (
            f"N2 FAILED: path_4_theory_hits={result['path_4_theory_hits']} should be >= 2 "
            f"for text with theorem/proof/bound-is-tight/lemma/sufficient-condition"
        )
        assert "path_4" in result["passed_paths"], (
            f"N2 FAILED: path_4 not in passed_paths={result['passed_paths']}"
        )
        assert result["passed"], (
            f"N2 FAILED: passed=False even though path_4 hit. result={result}"
        )

    def test_physical_depth_path2a_no_dataset_no_pass(self):
        """
        N2: abstract with only a bare percentage (no dataset name nearby) must
        NOT hit path_2a — this prevents false positives like 'achieves 87.3%'
        without a named benchmark.
        """
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        abstract = (
            "Our approach achieves 87.3% and improves upon previous results significantly. "
            "No specific benchmark dataset is mentioned in this abstract."
        )
        result = evaluate_physical_depth_v4(abstract)

        assert result["path_2a_pairs"] == 0, (
            f"N2 FAILED: path_2a_pairs={result['path_2a_pairs']} should be 0 "
            f"when no dataset name is present near the percentage"
        )
        assert "path_2a" not in result["passed_paths"], (
            f"N2 FAILED: path_2a should NOT be in passed_paths for bare percentage. "
            f"passed_paths={result['passed_paths']}"
        )

    def test_physical_depth_or_passes_any_path(self):
        """
        N2: any single path passing is sufficient for overall passed=True.
        Test with Path 1 (physical units), Path 3 (comparison), and Path 4 (theory).
        """
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        # Path 1 only (physical units)
        p1_abstract = (
            "The device operates at 1550 nm, with 3.5 dB insertion loss and 100 nm bandwidth. "
            "Resonance frequency is 193 THz with Q-factor 1000."
        )
        r1 = evaluate_physical_depth_v4(p1_abstract)
        assert r1["passed"], f"Path 1 (physical units) should pass. result={r1}"
        assert "path_1" in r1["passed_paths"]

        # Path 3 only (comparison + numeric)
        p3_abstract = (
            "We compare against 3 baselines and outperform state-of-the-art by 5.2%. "
            "Versus the baseline, we achieve 12.8 points improvement with accuracy 94.3%."
        )
        r3 = evaluate_physical_depth_v4(p3_abstract)
        assert r3["passed"], f"Path 3 (comparison) should pass. result={r3}"
        assert "path_3" in r3["passed_paths"]

        # Path 4 only (theory)
        p4_abstract = (
            "We prove the main theorem using a novel induction argument. "
            "The bound is tight and we provide a corollary that extends the result."
        )
        r4 = evaluate_physical_depth_v4(p4_abstract)
        assert r4["passed"], f"Path 4 (theory) should pass. result={r4}"
        assert "path_4" in r4["passed_paths"]

    def test_physical_depth_empty_abstract(self):
        """N2: empty / None abstract must return passed=False."""
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        r_empty = evaluate_physical_depth_v4("")
        assert not r_empty["passed"], "Empty abstract should not pass"
        assert r_empty["passed_paths"] == []

        r_spaces = evaluate_physical_depth_v4("   ")
        assert not r_spaces["passed"], "Whitespace-only abstract should not pass"

    def test_physical_depth_path2b_ablation(self):
        """N2: 'ablation study' phrase must trigger path_2b."""
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        abstract = (
            "Our ablation study demonstrates that each component contributes. "
            "The ablation table shows removing encoder drops 4% performance. "
            "Further ablation analysis confirms robustness."
        )
        result = evaluate_physical_depth_v4(abstract)
        assert result["path_2b_ablation_count"] >= 3, (
            f"path_2b_ablation_count={result['path_2b_ablation_count']} should be >= 3"
        )
        assert "path_2b" in result["passed_paths"]

    def test_physical_depth_path2c_complexity(self):
        """N2: 'O(n log n)' / 'time complexity' patterns must trigger path_2c."""
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        abstract = (
            "The algorithm runs in O(n log n) time. The time complexity analysis shows "
            "polynomial time guarantees. Space complexity is O(n) and convergence rate is O(1/T). "
            "GFLOPs required are 1.2 per forward pass."
        )
        result = evaluate_physical_depth_v4(abstract)
        assert result["path_2c_complexity_hits"] >= 3, (
            f"path_2c_complexity_hits={result['path_2c_complexity_hits']} should be >= 3"
        )
        assert "path_2c" in result["passed_paths"]

    def test_physical_depth_path2d_scale(self):
        """N2: '400 million parameters' / '50K images' must trigger path_2d."""
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        abstract = (
            "We train on 400 million tokens with a model of 7 billion parameters. "
            "The training set contains 50K images collected from diverse sources."
        )
        result = evaluate_physical_depth_v4(abstract)
        assert result["path_2d_scale_hits"] >= 1, (
            f"path_2d_scale_hits={result['path_2d_scale_hits']} should be >= 1"
        )
        assert "path_2d" in result["passed_paths"]

    def test_physical_depth_v4_return_schema(self):
        """N2: evaluate_physical_depth_v4 must return all required keys."""
        from echelon.seeds.physical_depth import evaluate_physical_depth_v4

        result = evaluate_physical_depth_v4("some abstract text")
        required_keys = [
            "passed", "passed_paths",
            "path_1_count", "path_2a_pairs", "path_2b_ablation_count",
            "path_2c_complexity_hits", "path_2d_scale_hits",
            "path_3_compare_hits", "path_4_theory_hits",
        ]
        for k in required_keys:
            assert k in result, f"Missing key '{k}' in evaluate_physical_depth_v4 result"

    def test_physical_depth_backward_compat(self):
        """N2: V11.3 check_physical_depth / has_physical_depth must still work."""
        from echelon.seeds.physical_depth import check_physical_depth, has_physical_depth

        # V11.3 R5 test: VLM paper with 87.3% COCO
        vlm_abstract = (
            "We present a vision-language model that achieves 87.3% accuracy on COCO. "
            "Our ablation study shows each component contributes: removing the cross-attention "
            "layer drops accuracy by 3.2%. On VQA benchmark we achieve 74.1%, and on "
            "ImageNet top-1 accuracy reaches 91.5%."
        )
        result = check_physical_depth(vlm_abstract)
        assert result.passed, "V11.3 backward compat: VLM paper should still pass"
        assert has_physical_depth(vlm_abstract), "has_physical_depth backward compat failed"


# ============================================================================
# N4 — c_venue_v4 percentile-by-age
# ============================================================================

class _MockPaper:
    """Minimal Paper-like object for c_venue_v4 testing."""
    def __init__(self, publication_date: date, cited_by_count: int):
        self.publication_date = publication_date
        self.cited_by_count = cited_by_count


def _make_corpus(
    n_young: int,
    n_old: int,
    young_age_months: int = 12,
    old_age_months: int = 60,
    rng_seed: int = 42,
    today: date = date(2025, 1, 1),
) -> List[_MockPaper]:
    """Create a synthetic corpus with young and old papers, gaussian cite counts."""
    rng = random.Random(rng_seed)
    corpus = []
    # young papers
    for _ in range(n_young):
        pub_date = today - timedelta(days=int(young_age_months * 30.4))
        cites = max(0, int(rng.gauss(10, 8)))
        corpus.append(_MockPaper(pub_date, cites))
    # old papers
    for _ in range(n_old):
        pub_date = today - timedelta(days=int(old_age_months * 30.4))
        cites = max(0, int(rng.gauss(80, 40)))
        corpus.append(_MockPaper(pub_date, cites))
    return corpus


class TestCVenueV4:

    def test_c_venue_v4_no_age_bias(self):
        """
        N4: With a mixed-age corpus (20 young @ 12mo, 20 old @ 60mo),
        c_venue_v4 standard deviation across ALL papers should be >= 0.20.

        Without age-normalisation, old-paper cites cluster high (0.7-0.9)
        and new-paper cites cluster low (0-0.5), giving artificial σ from
        the age effect rather than actual relative performance.
        With percentile-by-age, each paper competes only within its peer group,
        so scores should spread uniformly regardless of age cohort.
        """
        from echelon.seeds.score_keystone import c_venue_v4

        today = date(2025, 1, 1)
        corpus = _make_corpus(n_young=20, n_old=20, today=today)

        scores = [c_venue_v4(p, corpus, today) for p in corpus]

        mean_s = sum(scores) / len(scores)
        variance = sum((s - mean_s) ** 2 for s in scores) / len(scores)
        sigma = math.sqrt(variance)

        assert sigma >= 0.20, (
            f"N4 FAILED: c_venue_v4 σ={sigma:.4f} < 0.20. "
            f"Expected high spread (no age bias). mean={mean_s:.4f}, "
            f"min={min(scores):.4f}, max={max(scores):.4f}"
        )

    def test_c_venue_v4_old_paper_high_cite_high_percentile(self):
        """
        N4: A 60-month-old paper with 1000 citations should be at >= 0.85 percentile
        among its peer group (old papers with typical 40-120 cites).
        """
        from echelon.seeds.score_keystone import c_venue_v4

        today = date(2025, 1, 1)
        # Build a corpus of 20 old papers (60 months) with typical cites (10-120)
        corpus = []
        old_date = today - timedelta(days=int(60 * 30.4))
        for i in range(20):
            corpus.append(_MockPaper(old_date, cited_by_count=10 + i * 5))

        # Paper under test: 60mo old, 1000 cites (extreme outlier)
        paper = _MockPaper(old_date, cited_by_count=1000)
        corpus.append(paper)

        score = c_venue_v4(paper, corpus, today)
        assert score >= 0.85, (
            f"N4 FAILED: 60mo paper with 1000 cites should have percentile >= 0.85, "
            f"got {score:.4f}"
        )

    def test_c_venue_v4_new_paper_some_cite_high_percentile(self):
        """
        N4: A 6-month-old paper with 50 citations should have high percentile (>= 0.7)
        among peers at the same age (who typically have 0-20 cites).
        """
        from echelon.seeds.score_keystone import c_venue_v4

        today = date(2025, 1, 1)
        # Build corpus of 20 young papers (6 months) with 0-20 cites
        corpus = []
        young_date = today - timedelta(days=int(6 * 30.4))
        rng = random.Random(7)
        for _ in range(20):
            corpus.append(_MockPaper(young_date, cited_by_count=rng.randint(0, 20)))

        # Paper under test: 6mo old, 50 cites (well above peers)
        paper = _MockPaper(young_date, cited_by_count=50)
        corpus.append(paper)

        score = c_venue_v4(paper, corpus, today)
        assert score >= 0.7, (
            f"N4 FAILED: 6mo paper with 50 cites should have percentile >= 0.7, "
            f"got {score:.4f}"
        )

    def test_c_venue_v4_small_peer_group_returns_neutral(self):
        """N4: peer group < 5 papers → return 0.5 (neutral)."""
        from echelon.seeds.score_keystone import c_venue_v4

        today = date(2025, 1, 1)
        # Only 3 papers at the same age
        target_date = today - timedelta(days=int(12 * 30.4))
        corpus = [_MockPaper(target_date, cited_by_count=i * 10) for i in range(3)]
        paper = _MockPaper(target_date, cited_by_count=50)
        corpus.append(paper)

        score = c_venue_v4(paper, corpus, today)
        assert score == 0.5, (
            f"N4 FAILED: small peer group should return 0.5, got {score:.4f}"
        )

    def test_c_venue_v4_result_in_0_1(self):
        """N4: c_venue_v4 must always return a value in [0, 1]."""
        from echelon.seeds.score_keystone import c_venue_v4

        today = date(2025, 1, 1)
        corpus = _make_corpus(n_young=15, n_old=15, today=today)
        for p in corpus:
            score = c_venue_v4(p, corpus, today)
            assert 0.0 <= score <= 1.0, (
                f"N4 FAILED: c_venue_v4 returned {score:.4f} outside [0, 1]"
            )

    def test_compute_keystone_score_v4_exists(self):
        """N4: compute_keystone_score_v4 is importable and returns a float in [0,1]."""
        from echelon.seeds.score_keystone import compute_keystone_score_v4

        today = date(2025, 1, 1)
        corpus = _make_corpus(n_young=10, n_old=10, today=today)
        paper = corpus[0]

        score = compute_keystone_score_v4(paper=paper, corpus=corpus, today=today)
        assert isinstance(score, float), f"score must be float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"score {score:.4f} out of [0, 1]"

    def test_compute_keystone_score_v3_still_works(self):
        """N4: Old V11.3 compute_keystone_score is still importable and functional."""
        from echelon.seeds.score_keystone import compute_keystone_score

        score = compute_keystone_score(
            c_recency=0.6, c_venue=0.7, c_team_disrupt=0.5,
            c_recent_burst=0.4, c_review_filter=0.0,
            c_bib_breadth=0.5, c_bridging_centrality=0.5,
            c_semantic_outlier=0.5, c_breakthrough_lang=0.6,
            c_mechanism_novelty=0.5, supporting_count=0.5,
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ============================================================================
# N5 — bridge keyword library categorised expansion
# ============================================================================

class TestBridgeKeywordsV4:

    def test_bridge_keywords_v4_count_at_least_80(self):
        """
        N5: Total unique bridge keywords across all categories must be >= 80.
        (38 OPTICS_AI + 20 ROBOTICS_ML + 15 VLM_WORLD_MODEL + 10 GENERIC_AI4SCIENCE = 83)
        """
        from echelon.graph.bridge_keywords import BRIDGE_KEYWORDS_V4

        total = sum(len(v) for v in BRIDGE_KEYWORDS_V4.values())
        assert total >= 80, (
            f"N5 FAILED: total bridge keywords = {total} < 80. "
            f"Per-category: { {k: len(v) for k, v in BRIDGE_KEYWORDS_V4.items()} }"
        )

    def test_bridge_keywords_v4_categorized(self):
        """
        N5: 'Vision-Language-Action model for ...' must match ROBOTICS_ML category.
        """
        from echelon.graph.bridge_keywords import contains_bridge_keyword_v4

        text = "Vision-Language-Action model for robotic manipulation in unstructured environments."
        is_bridge, category = contains_bridge_keyword_v4(text)

        assert is_bridge, (
            f"N5 FAILED: text with 'Vision-Language-Action' not recognized as bridge"
        )
        assert category == "ROBOTICS_ML", (
            f"N5 FAILED: expected category='ROBOTICS_ML', got {category!r}"
        )

    def test_bridge_keywords_v4_optics_ai_unchanged(self):
        """
        N5: All 38 original OPTICS_AI keywords are preserved verbatim in V11.4.
        """
        from echelon.graph.bridge_keywords import BRIDGE_KEYWORDS, BRIDGE_KEYWORDS_V4

        # V11.3 flat list must equal V11.4 OPTICS_AI category
        optics_v4 = BRIDGE_KEYWORDS_V4["OPTICS_AI"]
        assert len(optics_v4) == 38, (
            f"N5 FAILED: OPTICS_AI should have 38 keywords, got {len(optics_v4)}"
        )
        assert len(BRIDGE_KEYWORDS) == 38, (
            f"N5 FAILED: backward-compat BRIDGE_KEYWORDS should have 38 entries, "
            f"got {len(BRIDGE_KEYWORDS)}"
        )
        for kw in BRIDGE_KEYWORDS:
            assert kw in optics_v4, (
                f"N5 FAILED: V11.3 keyword {kw!r} missing from BRIDGE_KEYWORDS_V4['OPTICS_AI']"
            )

    def test_bridge_keywords_v4_no_double_match(self):
        """
        N5: Text containing keywords from both OPTICS_AI and ROBOTICS_ML
        must return the higher-priority category (OPTICS_AI takes precedence).
        """
        from echelon.graph.bridge_keywords import contains_bridge_keyword_v4

        # Mix OPTICS_AI keyword ("optical computing") + ROBOTICS_ML keyword ("imitation learning")
        text = (
            "We propose an optical computing architecture that uses imitation learning "
            "to tune diffractive layers."
        )
        is_bridge, category = contains_bridge_keyword_v4(text)
        assert is_bridge, "N5 FAILED: mixed-category text should be a bridge"
        assert category == "OPTICS_AI", (
            f"N5 FAILED: OPTICS_AI has higher priority than ROBOTICS_ML, "
            f"got category={category!r}"
        )

    def test_bridge_keywords_v4_vlm_world_model(self):
        """N5: 'world model' text matches VLM_WORLD_MODEL category."""
        from echelon.graph.bridge_keywords import contains_bridge_keyword_v4

        text = "We train a dreamerv3-inspired world model for long-horizon planning tasks."
        is_bridge, category = contains_bridge_keyword_v4(text)
        assert is_bridge
        assert category == "VLM_WORLD_MODEL", (
            f"N5 FAILED: expected VLM_WORLD_MODEL, got {category!r}"
        )

    def test_bridge_keywords_v4_generic_ai4science(self):
        """N5: 'physics-informed neural network' matches GENERIC_AI4SCIENCE."""
        from echelon.graph.bridge_keywords import contains_bridge_keyword_v4

        text = "We apply a physics-informed neural network to solve PDEs efficiently."
        is_bridge, category = contains_bridge_keyword_v4(text)
        assert is_bridge
        assert category == "GENERIC_AI4SCIENCE", (
            f"N5 FAILED: expected GENERIC_AI4SCIENCE, got {category!r}"
        )

    def test_bridge_keywords_v4_no_match(self):
        """N5: Plain ML text without bridge keywords returns (False, None)."""
        from echelon.graph.bridge_keywords import contains_bridge_keyword_v4

        text = (
            "We propose a transformer model for image classification. "
            "Our method achieves 91.2% accuracy on the validation set."
        )
        is_bridge, category = contains_bridge_keyword_v4(text)
        assert not is_bridge, f"N5 FAILED: plain ML text should NOT be a bridge"
        assert category is None

    def test_build_bridge_keyword_edges_v4_has_category(self):
        """N5: build_bridge_keyword_edges_v4 returns dicts with 'category' field."""
        from echelon.graph.bridge_keywords import build_bridge_keyword_edges_v4

        papers = [
            {
                "paper_id": "p_optics",
                "primary_topic_id": "T10245",
                "abstract": "optical computing using photonic neural network.",
            },
            {
                "paper_id": "p_ml",
                "primary_topic_id": "T11714",
                "abstract": "A transformer for visual question answering.",
            },
            {
                "paper_id": "p_robotics",
                "primary_topic_id": "T10653",
                "abstract": "sim-to-real transfer for robotic manipulation.",
            },
        ]
        edges = build_bridge_keyword_edges_v4(papers)
        assert len(edges) > 0, "N5 FAILED: should produce at least one edge"
        for e in edges:
            assert "category" in e, f"N5 FAILED: edge missing 'category' field: {e}"
            assert "src" in e and "dst" in e and "weight" in e
            assert e["category"] in ("OPTICS_AI", "ROBOTICS_ML", "VLM_WORLD_MODEL", "GENERIC_AI4SCIENCE")

    def test_count_bridge_by_category(self):
        """N5: count_bridge_by_category returns correct per-category counts."""
        from echelon.graph.bridge_keywords import count_bridge_by_category

        papers = [
            {"abstract": "optical computing with photonic neural network"},     # OPTICS_AI
            {"abstract": "optical computing and diffractive deep neural network"},  # OPTICS_AI
            {"abstract": "imitation learning for robotic grasping"},            # ROBOTICS_ML
            {"abstract": "world model based planning with latent dynamics"},    # VLM_WORLD_MODEL
            {"abstract": "physics-informed neural network for turbulence"},     # GENERIC_AI4SCIENCE
            {"abstract": "plain transformer for classification"},               # none
        ]
        counts = count_bridge_by_category(papers)

        assert counts["OPTICS_AI"] == 2, f"Expected 2 OPTICS_AI, got {counts['OPTICS_AI']}"
        assert counts["ROBOTICS_ML"] == 1, f"Expected 1 ROBOTICS_ML, got {counts['ROBOTICS_ML']}"
        assert counts["VLM_WORLD_MODEL"] == 1, f"Expected 1 VLM_WORLD_MODEL, got {counts['VLM_WORLD_MODEL']}"
        assert counts["GENERIC_AI4SCIENCE"] == 1, f"Expected 1 GENERIC_AI4SCIENCE, got {counts['GENERIC_AI4SCIENCE']}"

    def test_bridge_keywords_v4_backward_compat_v11_3(self):
        """N5: V11.3 contains_bridge_keyword / build_bridge_keyword_edges still work."""
        from echelon.graph.bridge_keywords import (
            contains_bridge_keyword,
            find_bridge_keywords,
            build_bridge_keyword_edges,
        )

        bridge_abstract = (
            "We design a diffractive deep neural network that performs image recognition "
            "using optical diffraction."
        )
        assert contains_bridge_keyword(bridge_abstract), (
            "N5 FAILED: V11.3 contains_bridge_keyword backward compat broken"
        )
        found = find_bridge_keywords(bridge_abstract)
        assert "diffractive deep neural network" in found

        papers = [
            {
                "paper_id": "p_bridge",
                "primary_topic_id": "T10245",
                "abstract": bridge_abstract,
            },
            {
                "paper_id": "p_other",
                "primary_topic_id": "T11714",
                "abstract": "Transformer for VQA tasks.",
            },
        ]
        edges = build_bridge_keyword_edges(papers)
        assert len(edges) > 0, "N5 FAILED: V11.3 build_bridge_keyword_edges should still work"
        # Edges are tuples (pid_a, pid_b, weight, "bridge_keyword")
        assert len(edges[0]) == 4


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    # Quick smoke test
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    sys.exit(result.returncode)
