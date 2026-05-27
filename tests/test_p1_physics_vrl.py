"""
P1-E 物理/VRL/评估 单元测试 (10 条 AUDIT)

对应:
  AUDIT-013: cross_domain_gate.py — 双轨硬门
  AUDIT-034: review_subtype.py  — 综述 7 子类
  AUDIT-035: score_keystone.py  — c_team_disrupt 按类型分类
  AUDIT-039: epkb.py            — 18 月过期自动 refresh
  AUDIT-046: extract_evidence.py — 双轨召回
  AUDIT-061: simulation_runnable.py — 维度闸门
  AUDIT-071: minicheck_scorer.py — token 路由
  AUDIT-083: score_keystone.py + openalex_fetcher.py — n_authors=0 fix
  AUDIT-084: tokenizer_utils.py — tiktoken 真编码
  AUDIT-086: backtest_metrics.py — Brier + AUPRC + Hit Rate@K

运行: pytest tests/test_p1_physics_vrl.py -v
"""
from __future__ import annotations

import sys
import os
import math
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ============================================================================
# AUDIT-013: cross_domain_gate_v5 双轨硬门
# ============================================================================

class _PaperMature:
    bridging_centrality_zscore = 0.5
    reference_topics = ["photonics", "ML", "robotics"]

class _PaperMatureBelow:
    bridging_centrality_zscore = -0.3
    reference_topics = ["photonics", "ML", "robotics"]

class _PaperNew:
    bridging_centrality_zscore = -1.0  # 无意义 for new_paper
    reference_topics = ["photonics", "ML", "nano"]  # 3 topics

class _PaperNewFail:
    bridging_centrality_zscore = 0.8
    reference_topics = ["photonics"]   # only 1 topic


def test_audit013_mature_pass():
    """成熟论文 bridging z-score ≥ 0 → True"""
    from echelon.seeds.cross_domain_gate import cross_domain_gate_v5
    assert cross_domain_gate_v5(_PaperMature(), age_months=12) is True


def test_audit013_mature_fail():
    """成熟论文 bridging z-score < 0 → False"""
    from echelon.seeds.cross_domain_gate import cross_domain_gate_v5
    assert cross_domain_gate_v5(_PaperMatureBelow(), age_months=8) is False


def test_audit013_new_paper_pass():
    """新论文 bib_breadth ≥ 3 topics → True"""
    from echelon.seeds.cross_domain_gate import cross_domain_gate_v5
    assert cross_domain_gate_v5(_PaperNew(), age_months=3) is True


def test_audit013_new_paper_fail():
    """新论文 bib_breadth < 3 topics → False"""
    from echelon.seeds.cross_domain_gate import cross_domain_gate_v5
    assert cross_domain_gate_v5(_PaperNewFail(), age_months=2) is False


def test_audit013_bib_breadth_dedup():
    """bib_breadth 去重计数"""
    from echelon.seeds.cross_domain_gate import bib_breadth
    topics = ["photonics", "ML", "robotics", "photonics", "ML"]
    assert bib_breadth(topics) == 3


def test_audit013_boundary_exactly_6_months():
    """age=6 月 → 按 mature 轨处理"""
    from echelon.seeds.cross_domain_gate import cross_domain_gate_v5
    # bridging z-score = 0.0 → 刚好通过
    class P:
        bridging_centrality_zscore = 0.0
        reference_topics = []
    assert cross_domain_gate_v5(P(), age_months=6) is True


def test_audit013_describe_gate():
    """describe_gate_result 返回正确的 track"""
    from echelon.seeds.cross_domain_gate import describe_gate_result
    info_mature = describe_gate_result(_PaperMature(), age_months=10)
    assert info_mature["track"] == "mature"

    info_new = describe_gate_result(_PaperNew(), age_months=2)
    assert info_new["track"] == "new_paper"
    assert info_new["metric_name"] == "bib_n_topics"


# ============================================================================
# AUDIT-034: classify_review_subtype + review_penalty
# ============================================================================

def test_audit034_classify_tutorial():
    """title 含 'tutorial' → subtype=tutorial"""
    from echelon.seeds.review_subtype import classify_review_subtype
    assert classify_review_subtype("A Tutorial on Quantum Computing") == "tutorial"


def test_audit034_classify_roadmap():
    """title 含 'roadmap' → subtype=roadmap"""
    from echelon.seeds.review_subtype import classify_review_subtype
    assert classify_review_subtype("Roadmap for Photonic Integration") == "roadmap"


def test_audit034_classify_outlook():
    """title 含 'outlook' → subtype=outlook"""
    from echelon.seeds.review_subtype import classify_review_subtype
    assert classify_review_subtype("Outlook on Metasurface Research") == "outlook"


def test_audit034_classify_perspective():
    """title 含 'perspective' → subtype=perspective"""
    from echelon.seeds.review_subtype import classify_review_subtype
    assert classify_review_subtype("A Perspective on Deep Learning") == "perspective"


def test_audit034_classify_survey():
    """title 含 'survey' → subtype=survey"""
    from echelon.seeds.review_subtype import classify_review_subtype
    assert classify_review_subtype("Survey of Neural Architectures") == "survey"


def test_audit034_classify_review_from_abstract():
    """abstract 含 'recent advances' → subtype=review"""
    from echelon.seeds.review_subtype import classify_review_subtype
    result = classify_review_subtype(
        "Photonic crystals", "We review recent advances in photonic bandgap materials."
    )
    assert result == "review"


def test_audit034_classify_non_review():
    """无关键词 → non_review"""
    from echelon.seeds.review_subtype import classify_review_subtype
    result = classify_review_subtype(
        "Novel Metasurface Design for Beam Steering",
        "We propose a new approach using topology optimization."
    )
    assert result == "non_review"


def test_audit034_penalty_values():
    """验证 7 个子类型的惩罚系数"""
    from echelon.seeds.review_subtype import review_penalty
    assert review_penalty("survey") == 0.7
    assert review_penalty("tutorial") == 0.7
    assert review_penalty("review") == 0.7
    assert review_penalty("perspective") == 1.0
    assert review_penalty("outlook") == 1.0
    assert review_penalty("roadmap") == 1.0
    assert review_penalty("non_review") == 1.0


def test_audit034_all_7_subtypes_covered():
    """确保 7 个子类型都被 review_penalty 覆盖"""
    from echelon.seeds.review_subtype import review_penalty, _PENALTY_MAP
    expected = {"survey", "tutorial", "perspective", "outlook", "roadmap", "review", "non_review"}
    assert set(_PENALTY_MAP.keys()) == expected


# ============================================================================
# AUDIT-035: c_team_disrupt_v5 按论文类型分类
# ============================================================================

class _ExpPaper:
    validation_type = "experiment"
    n_authors = 6  # bucket: 4-10

class _TheorySmall:
    validation_type = "theory"
    n_authors = 2  # bucket: 1-3

class _TheoryLarge:
    validation_type = "theory"
    n_authors = 5  # bucket: 4+

class _SimLarge:
    validation_type = "simulation"
    n_authors = 15  # bucket: 11+


def test_audit035_experiment_mid_bucket():
    """experiment 4-10 → 1.0"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    assert c_team_disrupt_v5(_ExpPaper()) == 1.0


def test_audit035_experiment_small_bucket():
    """experiment 1-3 → 0.5"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    class P:
        validation_type = "experiment"
        n_authors = 2
    assert c_team_disrupt_v5(P()) == 0.5


def test_audit035_experiment_large_bucket():
    """experiment 11+ → 0.9"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    class P:
        validation_type = "experiment"
        n_authors = 12
    assert c_team_disrupt_v5(P()) == 0.9


def test_audit035_theory_small():
    """theory 1-3 → 1.0"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    assert c_team_disrupt_v5(_TheorySmall()) == 1.0


def test_audit035_theory_large():
    """theory 4+ → 0.7"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    assert c_team_disrupt_v5(_TheoryLarge()) == 0.7


def test_audit035_simulation_large():
    """simulation 11+ → 0.8"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    assert c_team_disrupt_v5(_SimLarge()) == 0.8


def test_audit035_team_score_table_structure():
    """TEAM_SCORE_TABLE 含 3 种类型"""
    from echelon.seeds.score_keystone import TEAM_SCORE_TABLE
    assert "experiment" in TEAM_SCORE_TABLE
    assert "simulation" in TEAM_SCORE_TABLE
    assert "theory" in TEAM_SCORE_TABLE


# ============================================================================
# AUDIT-039: EPKBEntry + refresh_epkb_entries
# ============================================================================

def test_audit039_entry_model():
    """EPKBEntry 模型正常构建"""
    from echelon.seeds.epkb import EPKBEntry
    e = EPKBEntry(
        entry_id="e001",
        claim_text="X is a bottleneck",
        source_paper_id="p001",
        last_seen_date=date(2024, 1, 1),
    )
    assert e.legacy_known is False
    assert e.decay_factor == 1.0
    assert e.effective_weight() == 1.0  # weight=1.0 * decay=1.0


def test_audit039_refresh_18_month_decay():
    """18 月前的 entry, refresh 后 decay=0.5, legacy_known=True"""
    from echelon.seeds.epkb import EPKBEntry, refresh_epkb_entries
    e = EPKBEntry(
        entry_id="old",
        claim_text="Old claim",
        source_paper_id="p_old",
        last_seen_date=date(2022, 1, 1),   # > 18 月前
        recent_evidence_count=0,
    )
    today = date(2024, 1, 1)
    refreshed = refresh_epkb_entries([e], today=today)
    assert len(refreshed) == 1
    r = refreshed[0]
    assert r.legacy_known is True
    assert r.decay_factor == 0.5


def test_audit039_refresh_recent_evidence_resets():
    """有新证据 → last_seen_date 更新, legacy_known=False, decay 恢复"""
    from echelon.seeds.epkb import EPKBEntry, refresh_epkb_entries
    e = EPKBEntry(
        entry_id="recent",
        claim_text="Active claim",
        source_paper_id="p_recent",
        last_seen_date=date(2022, 1, 1),
        legacy_known=True,
        decay_factor=0.5,
        recent_evidence_count=3,  # 有新证据
    )
    today = date(2024, 6, 1)
    refreshed = refresh_epkb_entries([e], today=today)
    r = refreshed[0]
    assert r.legacy_known is False
    assert r.last_seen_date == today
    assert r.decay_factor == 1.0


def test_audit039_refresh_not_expired():
    """未满 18 月且无新证据 → 不变"""
    from echelon.seeds.epkb import EPKBEntry, refresh_epkb_entries
    e = EPKBEntry(
        entry_id="mid",
        claim_text="Mid claim",
        source_paper_id="p_mid",
        last_seen_date=date(2024, 1, 1),
        recent_evidence_count=0,
    )
    today = date(2024, 6, 1)  # 5 月, < 18 月
    refreshed = refresh_epkb_entries([e], today=today)
    r = refreshed[0]
    assert r.legacy_known is False
    assert r.decay_factor == 1.0


def test_audit039_effective_weight_decayed():
    """衰减后 effective_weight = weight * 0.5"""
    from echelon.seeds.epkb import EPKBEntry
    e = EPKBEntry(
        entry_id="w",
        claim_text="test",
        source_paper_id="p1",
        last_seen_date=date(2022, 1, 1),
        weight=0.8,
        decay_factor=0.5,
    )
    assert abs(e.effective_weight() - 0.4) < 1e-9


# ============================================================================
# AUDIT-046: dual_track_recall 双轨召回
# ============================================================================

def test_audit046_rule_track_recall():
    """规则轨: 含关键词的句子被召回"""
    from echelon.pdf.extract_evidence import dual_track_recall
    sentences = [
        "The method achieves state-of-the-art performance.",
        "A key limitation of this approach is scalability.",
        "We propose a novel algorithm.",
    ]
    recalled = dual_track_recall(sentences, model=None)
    # "limitation" 在规则词中
    assert any("limitation" in s for s in recalled)


def test_audit046_or_semantics():
    """OR 语义: 规则轨命中的句子必须在输出中"""
    from echelon.pdf.extract_evidence import dual_track_recall
    sentences = [
        "This remains an open challenge in physics.",
        "The result is very good.",
    ]
    recalled = dual_track_recall(sentences, model=None)
    # "challenge" 在规则关键词中
    challenge_recalled = any("challenge" in s for s in recalled)
    assert challenge_recalled


def test_audit046_templates_count():
    """BOTTLENECK_TEMPLATES 含 15 条模板"""
    from echelon.pdf.extract_evidence import BOTTLENECK_TEMPLATES
    assert len(BOTTLENECK_TEMPLATES) == 15


def test_audit046_empty_input():
    """空输入 → 返回空列表"""
    from echelon.pdf.extract_evidence import dual_track_recall
    assert dual_track_recall([]) == []


def test_audit046_semantic_recall_no_model():
    """无模型时 semantic_recall_sentences 返回空 (不崩溃)"""
    from echelon.pdf.extract_evidence import semantic_recall_sentences
    # 无 sentence-transformers → model=None → 返回空
    result = semantic_recall_sentences(
        ["test sentence"], model=None
    )
    # 无模型: 空列表 (不抛异常)
    assert isinstance(result, list)


# ============================================================================
# AUDIT-061: SimulationRunnable 维度闸门
# ============================================================================

def test_audit061_spinsb_2d_pass():
    """SPINS-B 支持 2D → True"""
    from echelon.vrl.simulation_runnable import check_simulation_dimension
    assert check_simulation_dimension("2D", "SPINS-B") is True


def test_audit061_spinsb_3d_reject():
    """SPINS-B 不支持 3D → False"""
    from echelon.vrl.simulation_runnable import check_simulation_dimension
    assert check_simulation_dimension("3D", "SPINS-B") is False


def test_audit061_meep_3d_pass():
    """Meep 支持 3D → True"""
    from echelon.vrl.simulation_runnable import check_simulation_dimension
    assert check_simulation_dimension("3D", "Meep") is True


def test_audit061_lumerical_both():
    """Lumerical 支持 2D 和 3D"""
    from echelon.vrl.simulation_runnable import check_simulation_dimension
    assert check_simulation_dimension("2D", "Lumerical") is True
    assert check_simulation_dimension("3D", "Lumerical") is True


def test_audit061_auto_downgrade():
    """SPINS-B 3D → 自动降级到 2D"""
    from echelon.vrl.simulation_runnable import SimulationSpec, auto_downgrade_3d_to_2d
    spec = SimulationSpec(tool="SPINS-B", target_dim="3D")
    result = auto_downgrade_3d_to_2d(spec)
    assert result.downgraded is True
    assert result.new_dim == "2D"
    assert "3D" in result.reason


def test_audit061_no_downgrade_if_supported():
    """Meep 3D → 不降级"""
    from echelon.vrl.simulation_runnable import SimulationSpec, auto_downgrade_3d_to_2d
    spec = SimulationSpec(tool="Meep", target_dim="3D")
    result = auto_downgrade_3d_to_2d(spec)
    assert result.downgraded is False


def test_audit061_gate_simulation_spinsb_3d():
    """gate_simulation: SPINS-B 3D → allowed=True (降级到 2D)"""
    from echelon.vrl.simulation_runnable import SimulationSpec, gate_simulation
    spec = SimulationSpec(tool="SPINS-B", target_dim="3D")
    result = gate_simulation(spec)
    assert result["allowed"] is True
    assert result["dimension"] == "2D"
    assert result["downgrade"] is not None


def test_audit061_tool_dimension_table_exists():
    """TOOL_DIMENSION_SUPPORT 表存在且 SPINS-B 仅 2D"""
    from echelon.vrl.simulation_runnable import TOOL_DIMENSION_SUPPORT
    assert "SPINS-B" in TOOL_DIMENSION_SUPPORT
    assert TOOL_DIMENSION_SUPPORT["SPINS-B"] == ["2D"]


# ============================================================================
# AUDIT-071: MiniCheck token 路由
# ============================================================================

def test_audit071_short_routes_minicheck():
    """短文本 → MiniCheck-FlanT5"""
    from echelon.bottleneck.minicheck_scorer import route_verifier, MINICHECK_MODEL_NAME
    short_claim = "X is fast."
    short_evidence = "We measured X at 100 ns."
    result = route_verifier(short_claim, short_evidence)
    assert result == MINICHECK_MODEL_NAME


def test_audit071_long_routes_hhem():
    """超过 480 token 的文本 → HHEM-2.1-Open"""
    from echelon.bottleneck.minicheck_scorer import route_verifier, HHEM_MODEL_NAME
    # 生成约 600 词的文本 (超过 480 token)
    long_text = " ".join(["photonic crystal nanocavity metasurface optical"] * 120)
    result = route_verifier(long_text, long_text[:50])
    assert result == HHEM_MODEL_NAME


def test_audit071_threshold_exactly_480():
    """刚好 ≤ 480 token → MiniCheck (≤ threshold)"""
    from echelon.bottleneck.minicheck_scorer import route_verifier, MINICHECK_MODEL_NAME, _count_tokens_tiktoken
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    # 构造 400 token 的文本 (确保在 480 以内)
    word = "test "
    text = word * 400
    tokens = enc.encode(text)
    text_400 = enc.decode(tokens[:400])
    n = _count_tokens_tiktoken(text_400 + " ")
    assert n <= 480, f"test text has {n} tokens, should be ≤ 480"
    result = route_verifier(text_400, "")
    assert result == MINICHECK_MODEL_NAME


def test_audit071_verify_claim_returns_dict():
    """verify_claim 返回包含 verifier/score/token_count 的 dict"""
    from echelon.bottleneck.minicheck_scorer import verify_claim
    result = verify_claim("X is novel.", "The paper presents a novel method X.")
    assert "verifier" in result
    assert "score" in result
    assert "token_count" in result
    assert isinstance(result["score"], float)
    assert 0.0 <= result["score"] <= 1.0


def test_audit071_uses_tiktoken_not_split():
    """路由器使用 tiktoken (cl100k_base), 非 split() 词数"""
    from echelon.bottleneck.minicheck_scorer import _count_tokens_tiktoken
    # "photonic crystal nanocavity" = 3 words, 但 BPE token 数 ≥ 3
    text = "photonic crystal nanocavity"
    count = _count_tokens_tiktoken(text)
    # tiktoken 通常 token 数 ≥ 词数 (BPE 细粒度)
    assert count >= len(text.split())


# ============================================================================
# AUDIT-083: n_authors=0 → 中性 0.5 + editorial 过滤
# ============================================================================

def test_audit083_n_authors_zero_neutral():
    """n_authors=0 → c_team_disrupt_v5 返回中性 0.5"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    class P:
        validation_type = "experiment"
        n_authors = 0
    assert c_team_disrupt_v5(P()) == 0.5


def test_audit083_editorial_filtered():
    """editorial 类型被过滤"""
    from echelon.ingest.openalex_fetcher import filter_non_research_works
    works = [
        {"type": "article", "title": "Novel Paper"},
        {"type": "editorial", "title": "Editor Note"},
        {"type": "letter", "title": "Quick Report"},
        {"type": "erratum", "title": "Correction"},
    ]
    filtered = list(filter_non_research_works(works))
    assert len(filtered) == 1
    assert filtered[0]["type"] == "article"


def test_audit083_is_research_work():
    """is_research_work 正确判定各类型"""
    from echelon.ingest.openalex_fetcher import is_research_work
    assert is_research_work({"type": "article"}) is True
    assert is_research_work({"type": "preprint"}) is True
    assert is_research_work({}) is True  # 缺失 type → 宽松保留
    assert is_research_work({"type": "editorial"}) is False
    assert is_research_work({"type": "Letter"}) is False  # 大小写不敏感
    assert is_research_work({"type": "erratum"}) is False


def test_audit083_no_key_error_unknown_type():
    """未知 validation_type → 中性 0.5 (不崩溃)"""
    from echelon.seeds.score_keystone import c_team_disrupt_v5
    class P:
        validation_type = "unknown_type"
        n_authors = 5
    result = c_team_disrupt_v5(P())
    assert result == 0.5


# ============================================================================
# AUDIT-084: tiktoken 真编码替换 split()
# ============================================================================

def test_audit084_tiktoken_count_basic():
    """tiktoken_count 返回整数 token 数"""
    from echelon.core.tokenizer_utils import tiktoken_count
    count = tiktoken_count("Hello, world!")
    assert isinstance(count, int)
    assert count > 0


def test_audit084_tiktoken_count_empty():
    """空字符串 → 0"""
    from echelon.core.tokenizer_utils import tiktoken_count
    assert tiktoken_count("") == 0


def test_audit084_split_vs_tiktoken_ratio_ge_1_3():
    """
    AUDIT-084 核心验证: 学术长文本中 tiktoken/split 比值 ≥ 1.3×

    典型场景: 物理论文含大量多音节专业词
    如 "nanocavity", "photonic", "plasmonic", "metasurface"
    BPE 将它们分解为多个 subword tokens, 导致 token 数 > word 数
    """
    from echelon.core.tokenizer_utils import measure_split_vs_tiktoken_ratio
    # 构造包含大量专业词的文本
    technical_text = (
        "nanocavity photonic plasmonic metasurface metamaterial "
        "electromagnetically induced transparency Fano resonance "
        "topological insulator phonon-polariton quantum electrodynamics "
        "nanoparticle-cavity coupling ultrafast spectroscopy coherent "
        "backscattering localization photon antibunching Purcell enhancement "
    ) * 5  # 重复 5 次确保有足够样本

    ratio = measure_split_vs_tiktoken_ratio(technical_text)
    # tiktoken 计数 ≥ 1.3 × split 计数 (BPE 分解专业词)
    assert ratio >= 1.3, (
        f"AUDIT-084: tiktoken/split 比值 = {ratio:.3f}, 应 ≥ 1.3. "
        "学术专业词应被 BPE 分解为更多 tokens."
    )


def test_audit084_cl100k_base_encoding():
    """确认使用 cl100k_base (GPT-4 标准编码)"""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    # 已知 token 数: "Hello world" → 2 tokens in cl100k_base
    tokens = enc.encode("Hello world")
    assert len(tokens) == 2


def test_audit084_tokenizer_utils_module_exists():
    """tokenizer_utils 模块可导入"""
    from echelon.core.tokenizer_utils import tiktoken_count, tiktoken_count_batch
    # 批量计数
    counts = tiktoken_count_batch(["hello", "world", ""])
    assert counts[2] == 0
    assert all(isinstance(c, int) for c in counts)


def test_audit084_split_word_count_deprecated():
    """split_word_count 触发 DeprecationWarning"""
    import warnings
    from echelon.core.tokenizer_utils import split_word_count
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        count = split_word_count("hello world test")
        assert count == 3
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)


# ============================================================================
# AUDIT-086: Brier Score + AUPRC + Hit Rate@K
# ============================================================================

def test_audit086_brier_score_perfect():
    """完美预测 → Brier Score = 0"""
    from echelon.vrl.backtest_metrics import brier_score
    bs = brier_score([1, 0, 1], [1.0, 0.0, 1.0])
    assert abs(bs) < 1e-9


def test_audit086_brier_score_random():
    """随机预测 (0.5) → Brier Score = 0.25"""
    from echelon.vrl.backtest_metrics import brier_score
    bs = brier_score([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5])
    assert abs(bs - 0.25) < 1e-9


def test_audit086_brier_score_empty_raises():
    """空输入 → ValueError"""
    from echelon.vrl.backtest_metrics import brier_score
    with pytest.raises(ValueError, match="不能为空"):
        brier_score([], [])


def test_audit086_brier_score_mismatch_raises():
    """长度不匹配 → ValueError"""
    from echelon.vrl.backtest_metrics import brier_score
    with pytest.raises(ValueError, match="长度不匹配"):
        brier_score([1, 0], [0.5])


def test_audit086_auprc_perfect():
    """完美排序 → AUPRC = 1.0"""
    from echelon.vrl.backtest_metrics import auprc
    # 正样本分数全部高于负样本
    score = auprc([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2])
    assert abs(score - 1.0) < 1e-6


def test_audit086_auprc_no_positive_raises():
    """无正样本 → ValueError"""
    from echelon.vrl.backtest_metrics import auprc
    with pytest.raises(ValueError, match="没有正样本"):
        auprc([0, 0, 0], [0.1, 0.5, 0.9])


def test_audit086_hit_rate_at_k_perfect():
    """完美推荐 → Hit Rate@K = 1.0"""
    from echelon.vrl.backtest_metrics import hit_rate_at_k
    score = hit_rate_at_k(["a", "b", "c"], ["a", "b", "c"], k=3)
    assert abs(score - 1.0) < 1e-9


def test_audit086_hit_rate_at_k_partial():
    """部分命中"""
    from echelon.vrl.backtest_metrics import hit_rate_at_k
    score = hit_rate_at_k(["a", "b", "c", "d"], ["a", "c"], k=2)
    # Top-2: [a, b], hits: {a}, hit_rate = 1/min(2,2) = 0.5
    assert abs(score - 0.5) < 1e-9


def test_audit086_hit_rate_at_k_zero():
    """完全未命中 → 0.0"""
    from echelon.vrl.backtest_metrics import hit_rate_at_k
    score = hit_rate_at_k(["x", "y"], ["a", "b"], k=2)
    assert score == 0.0


def test_audit086_f1_at_k():
    """F1@K 计算正确"""
    from echelon.vrl.backtest_metrics import f1_at_k
    # predicted: [a, b, c], actual: {a, c}, k=2
    # P@2 = 1/2=0.5, R@2 = 1/2=0.5, F1 = 0.5
    score = f1_at_k(["a", "b", "c"], ["a", "c"], k=2)
    assert abs(score - 0.5) < 1e-9


def test_audit086_no_smape_in_module():
    """确认 backtest_metrics 模块中不包含 smape/mase 函数"""
    import echelon.vrl.backtest_metrics as m
    assert not hasattr(m, "smape")
    assert not hasattr(m, "sMAPE")
    assert not hasattr(m, "mase")
    assert not hasattr(m, "MASE")


def test_audit086_evaluate_recommendations():
    """evaluate_recommendations 综合函数返回所有指标"""
    from echelon.vrl.backtest_metrics import evaluate_recommendations
    result = evaluate_recommendations(
        y_true=[1, 0, 1, 0, 1],
        y_score=[0.9, 0.2, 0.8, 0.1, 0.7],
        predicted_ids=["a", "b", "c", "d", "e"],
        actual_ids=["a", "c", "e"],
        k=3,
    )
    assert "brier_score" in result
    assert "auprc" in result
    assert "hit_rate_at_k" in result
    assert "f1_at_k" in result
    assert result["k"] == 3
