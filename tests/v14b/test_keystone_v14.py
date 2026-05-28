"""
tests/v14b/test_keystone_v14.py

V14 调权 KeystoneScore 测试 — 6 个 case: 3 lifecycle × 高/低分
"""
from datetime import date, timedelta

import pytest

from echelon.v14b.step3_keystone_v14 import keystone_score_v14, quality_adjusted_keystone_score
from echelon.v14b.config import LIFECYCLE_WEIGHTS_V14


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

class FreshPaper:
    publication_date = date.today() - timedelta(days=30)  # 1 month old


class GrowingPaper:
    publication_date = date.today() - timedelta(days=365)  # 1 year old


class MaturePaper:
    publication_date = date.today() - timedelta(days=365 * 5)  # 5 years old


ALL_HIGH_SIGNALS = {
    "c_recency": 0.9,
    "c_venue": 0.9,
    "c_team_disrupt": 0.9,
    "c_recent_burst": 0.9,
    "c_review_filter": 0.0,  # not a review
    "c_bib_breadth": 0.9,
    "c_cocite_breadth": 0.9,
    "c_bridging_centrality": 0.9,
    "c_cd_subdomain": 0.9,
    "c_semantic_outlier": 0.9,
    "c_breakthrough_lang": 0.9,
    "c_mechanism_novelty": 0.9,
}

ALL_LOW_SIGNALS = {
    "c_recency": 0.1,
    "c_venue": 0.1,
    "c_team_disrupt": 0.1,
    "c_recent_burst": 0.1,
    "c_review_filter": 1.0,  # is a review
    "c_bib_breadth": 0.1,
    "c_cocite_breadth": 0.1,
    "c_bridging_centrality": 0.1,
    "c_cd_subdomain": 0.1,
    "c_semantic_outlier": 0.1,
    "c_breakthrough_lang": 0.1,
    "c_mechanism_novelty": 0.1,
}


# ---------------------------------------------------------------------------
# 生命周期权重表验证
# ---------------------------------------------------------------------------

class TestLifecycleWeightsV14:
    def test_all_lifecycles_present(self):
        assert set(LIFECYCLE_WEIGHTS_V14.keys()) == {"fresh", "growing", "mature"}

    def test_all_signals_present(self):
        expected_signals = {
            "c_recency", "c_venue", "c_team_disrupt", "c_recent_burst",
            "c_review_filter", "c_bib_breadth", "c_cocite_breadth",
            "c_bridging_centrality", "c_cd_subdomain", "c_semantic_outlier",
            "c_breakthrough_lang", "c_mechanism_novelty",
        }
        for lc in LIFECYCLE_WEIGHTS_V14:
            assert set(LIFECYCLE_WEIGHTS_V14[lc].keys()) == expected_signals

    def test_fresh_mechanism_novelty_weight_high(self):
        """Fresh 论文 mechanism_novelty 权重应 >= 0.15"""
        assert LIFECYCLE_WEIGHTS_V14["fresh"]["c_mechanism_novelty"] >= 0.15

    def test_fresh_breakthrough_lang_weight_high(self):
        """Fresh 论文 breakthrough_lang 权重应 >= 0.15"""
        assert LIFECYCLE_WEIGHTS_V14["fresh"]["c_breakthrough_lang"] >= 0.15

    def test_mature_cd_subdomain_weight_high(self):
        """Mature 论文 cd_subdomain 权重应 >= 0.20"""
        assert LIFECYCLE_WEIGHTS_V14["mature"]["c_cd_subdomain"] >= 0.20

    def test_mature_bridging_high(self):
        """所有 lifecycle 的 bridging_centrality >= 0.20"""
        for lc in LIFECYCLE_WEIGHTS_V14:
            assert LIFECYCLE_WEIGHTS_V14[lc]["c_bridging_centrality"] >= 0.20

    def test_review_filter_negative(self):
        """c_review_filter 权重必须为负数(惩罚项)"""
        for lc in LIFECYCLE_WEIGHTS_V14:
            assert LIFECYCLE_WEIGHTS_V14[lc]["c_review_filter"] < 0


# ---------------------------------------------------------------------------
# 6 个 case: 3 lifecycle × 高/低分
# ---------------------------------------------------------------------------

class TestKeystoneScoreV14Cases:
    """Case 1: Fresh + 高分"""
    def test_case1_fresh_high(self):
        score, lifecycle = keystone_score_v14(ALL_HIGH_SIGNALS, FreshPaper())
        assert lifecycle == "fresh"
        assert score > 0.5, f"Fresh high signals should score > 0.5, got {score}"
        assert 0.0 <= score <= 1.0

    """Case 2: Fresh + 低分"""
    def test_case2_fresh_low(self):
        score, lifecycle = keystone_score_v14(ALL_LOW_SIGNALS, FreshPaper())
        assert lifecycle == "fresh"
        assert score < 0.5, f"Fresh low signals should score < 0.5, got {score}"
        assert 0.0 <= score <= 1.0

    """Case 3: Growing + 高分"""
    def test_case3_growing_high(self):
        score, lifecycle = keystone_score_v14(ALL_HIGH_SIGNALS, GrowingPaper())
        assert lifecycle == "growing"
        assert score > 0.5
        assert 0.0 <= score <= 1.0

    """Case 4: Growing + 低分"""
    def test_case4_growing_low(self):
        score, lifecycle = keystone_score_v14(ALL_LOW_SIGNALS, GrowingPaper())
        assert lifecycle == "growing"
        assert score < 0.5
        assert 0.0 <= score <= 1.0

    """Case 5: Mature + 高分"""
    def test_case5_mature_high(self):
        score, lifecycle = keystone_score_v14(ALL_HIGH_SIGNALS, MaturePaper())
        assert lifecycle == "mature"
        assert score > 0.5
        assert 0.0 <= score <= 1.0

    """Case 6: Mature + 低分"""
    def test_case6_mature_low(self):
        score, lifecycle = keystone_score_v14(ALL_LOW_SIGNALS, MaturePaper())
        assert lifecycle == "mature"
        assert score < 0.5
        assert 0.0 <= score <= 1.0

    def test_high_vs_low_ordering(self):
        """高信号分数应高于低信号分数"""
        for paper_cls in [FreshPaper, GrowingPaper, MaturePaper]:
            paper = paper_cls()
            high_score, _ = keystone_score_v14(ALL_HIGH_SIGNALS, paper)
            low_score, _ = keystone_score_v14(ALL_LOW_SIGNALS, paper)
            assert high_score > low_score, f"{paper_cls.__name__}: high={high_score} should > low={low_score}"

    def test_none_signals_skipped(self):
        """None 信号应被跳过,不影响分数"""
        signals_with_none = {**ALL_HIGH_SIGNALS, "c_cd_subdomain": None, "c_cocite_breadth": None}
        score, _ = keystone_score_v14(signals_with_none, MaturePaper())
        assert 0.0 <= score <= 1.0

    def test_score_range(self):
        """所有情况下分数应在 [0, 1]"""
        import random
        rng = random.Random(42)
        for _ in range(20):
            signals = {
                k: rng.random() if rng.random() > 0.2 else None
                for k in ALL_HIGH_SIGNALS
            }
            for paper in [FreshPaper(), GrowingPaper(), MaturePaper()]:
                score, _ = keystone_score_v14(signals, paper)
                assert 0.0 <= score <= 1.0

    def test_low_signal_quality_dampens_extreme_scores(self):
        raw_high = 0.9
        raw_low = 0.1
        assert quality_adjusted_keystone_score(raw_high, 0.25) == pytest.approx(0.6)
        assert quality_adjusted_keystone_score(raw_low, 0.25) == pytest.approx(0.4)
        assert quality_adjusted_keystone_score(raw_high, 1.0) == pytest.approx(raw_high)
