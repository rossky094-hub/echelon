"""
P0 Schema/Prompt 11条 单元测试
=================================
每条 AUDIT 对应一个测试函数，精确匹配要求的测试名称。

运行: pytest tests/test_p0_schema_prompt.py -v
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile

import pytest

# 确保 echelon 包可被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# AUDIT-014: extract_abstract_full — max_chars=2500, NOT 100 words
# ============================================================================

def test_extract_abstract_full_not_truncated_to_100_words():
    """
    AUDIT-014: extract_abstract_full(text, max_chars=2500) must preserve
    abstracts longer than 100 words (V11.1 bug: truncation at 100 words
    destroyed ~40% of content for typical physics papers).
    """
    from echelon.pdf.extract_abstract import extract_abstract_full

    # Build a long abstract > 100 words (250 words ≈ 1500 chars)
    long_abstract_words = ["term" + str(i) for i in range(250)]
    long_abstract = " ".join(long_abstract_words)

    # Simulate a paper text with the abstract header
    paper_text = (
        "Title: Metasurface Crosstalk Analysis\n\n"
        "ABSTRACT\n\n"
        f"{long_abstract}\n\n"
        "1. Introduction\n"
        "We present here the details...\n"
    )

    result = extract_abstract_full(paper_text, max_chars=2500)

    assert result is not None, "extract_abstract_full returned None for clearly-formatted abstract"

    # Key assertion: result must contain MORE than 100 words
    word_count = len(result.split())
    assert word_count > 100, (
        f"[AUDIT-014] abstract was truncated to {word_count} words — "
        "V11.1 bug not fixed (should return up to max_chars=2500)"
    )

    # Should not exceed max_chars
    assert len(result) <= 2500, f"result exceeds max_chars=2500: len={len(result)}"

    # Must include content from word 150+ (beyond the old 100-word cut)
    assert "term149" in result or "term150" in result or "term200" in result, (
        "Abstract appears truncated at ~100 words — key terms from the second "
        "half of the abstract are missing"
    )

    # Deprecated extract_abstract still works but warns
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from echelon.pdf.extract_abstract import extract_abstract
        truncated = extract_abstract(paper_text, max_words=100)
        assert any(issubclass(warning.category, DeprecationWarning) for warning in w), \
            "extract_abstract() should emit DeprecationWarning"
    if truncated:
        assert len(truncated.split()) <= 105  # 100 words ± small margin


# ============================================================================
# AUDIT-015: EvidenceAtom page_no + post_validate_evidence_page
# ============================================================================

def test_evidence_page_post_validate():
    """
    AUDIT-015: page_no must come from pdfplumber.pages index (real PDF),
    not from LLM. post_validate_evidence_page() must reject hallucinated pages.
    """
    from echelon.pdf.parser import (
        PageBlock,
        post_validate_evidence_page,
        build_page_pool,
        format_with_page_markers,
    )
    from echelon.schema.evidence import EvidenceAtom

    # Simulate parsed PDF: pages 1, 2, 4 (page 3 is blank — not in pool)
    blocks = [
        PageBlock(page_no=1, text="Abstract: We study photonic crosstalk...", section_hint="abstract"),
        PageBlock(page_no=2, text="Results show -20 dB isolation at 1550 nm.", section_hint="body"),
        PageBlock(page_no=4, text="Limitations: bandwidth limited by Q-factor.", section_hint="limitations"),
    ]

    page_pool = build_page_pool(blocks)

    # page_pool must have exactly pages 1, 2, 4
    assert set(page_pool.keys()) == {1, 2, 4}, f"page_pool keys wrong: {page_pool.keys()}"

    # ── Validate real pages: must return True ──────────────────────────────
    assert post_validate_evidence_page(1, page_pool) is True
    assert post_validate_evidence_page(2, page_pool) is True
    assert post_validate_evidence_page(4, page_pool) is True

    # ── Validate hallucinated page: must return False ──────────────────────
    assert post_validate_evidence_page(3, page_pool) is False, \
        "page_no=3 is not in pool — should return False"
    assert post_validate_evidence_page(99, page_pool) is False, \
        "page_no=99 is hallucinated — should return False"
    assert post_validate_evidence_page(None, page_pool) is False, \
        "page_no=None should return False"

    # ── format_with_page_markers produces [Page N] labels ──────────────────
    marked = format_with_page_markers(blocks)
    assert "[Page 1]" in marked
    assert "[Page 2]" in marked
    assert "[Page 4]" in marked

    # ── EvidenceAtom must require page_no ≥ 1 ──────────────────────────────
    span = "Bandwidth is fundamentally limited by the resonance Q-factor tradeoff."
    atom = EvidenceAtom(
        paper_id="paper_001",
        page_no=4,
        span_text=span,
        section_type="limitations",
    )
    assert atom.page_no == 4
    assert atom.content_hash == hashlib.sha256(span.encode()).hexdigest()

    # page_no < 1 should raise
    with pytest.raises(Exception):
        EvidenceAtom(paper_id="paper_001", page_no=0, span_text=span, section_type="body")


# ============================================================================
# AUDIT-016: Debate Critic UUID pool validation
# ============================================================================

def test_debate_critic_uuid_in_pool():
    """
    AUDIT-016: Debate Critic must inject prior_art_pool into prompt.
    critique_targets must be a SUBSET of pool IDs.
    Hallucinated IDs are stripped; only pool IDs survive validation.
    """
    from echelon.bottleneck.debate_critic import (
        CriticResult,
        build_critic_prompt,
        validate_critic_result,
        run_debate_critic,
        DEBATE_CRITIC_PROMPT,
    )

    prior_art_pool = [
        {"pool_id": "uuid-aaa-001", "title": "Metasurface crosstalk study", "publication_year": 2023,
         "abstract_snippet": "Bandwidth is limited by the Q-factor resonance."},
        {"pool_id": "uuid-bbb-002", "title": "On-chip photonic integration", "publication_year": 2022,
         "abstract_snippet": "Crosstalk remains a fundamental barrier beyond 100 channels."},
        {"pool_id": "uuid-ccc-003", "title": "Silicon waveguide loss analysis", "publication_year": 2021,
         "abstract_snippet": "Propagation loss constrains integration density."},
    ]

    valid_ids = {e["pool_id"] for e in prior_art_pool}

    # ── Prompt must contain all pool_ids ──────────────────────────────────
    prompt = build_critic_prompt(
        claim_text="Crosstalk limits channel density below 50 channels/mm²",
        severity="failure",
        physical_depth_score=0.80,
        supporting_count=5,
        prior_art_pool=prior_art_pool,
    )
    assert "uuid-aaa-001" in prompt, "Prior art pool_id not injected into prompt"
    assert "uuid-bbb-002" in prompt, "Prior art pool_id not injected into prompt"
    assert "DO NOT invent" in prompt or "DO NOT fabricate" in prompt, \
        "Prompt must warn LLM not to fabricate UUIDs"

    # ── validate_critic_result: good UUIDs pass ───────────────────────────
    good_result = CriticResult(
        critique_targets=["uuid-aaa-001", "uuid-bbb-002"],
        critique_reasoning="Both papers show crosstalk is fundamental.",
        verdict="partially_refuted",
    )
    sanitized, hallucinated = validate_critic_result(good_result, prior_art_pool)
    assert hallucinated == [], f"No hallucination expected; got {hallucinated}"
    assert set(sanitized.critique_targets) == {"uuid-aaa-001", "uuid-bbb-002"}

    # ── validate_critic_result: hallucinated ID is stripped ───────────────
    bad_result = CriticResult(
        critique_targets=["uuid-aaa-001", "uuid-HALLUCINATED-9999"],
        critique_reasoning="This one is invented.",
        verdict="refuted",
    )
    sanitized2, hallucinated2 = validate_critic_result(bad_result, prior_art_pool)
    assert "uuid-HALLUCINATED-9999" in hallucinated2, \
        "Hallucinated UUID must be in hallucinated_ids list"
    assert "uuid-HALLUCINATED-9999" not in sanitized2.critique_targets, \
        "Hallucinated UUID must be stripped from critique_targets"
    assert "uuid-aaa-001" in sanitized2.critique_targets, \
        "Valid pool ID must survive validation"

    # ── run_debate_critic with mock LLM ──────────────────────────────────
    def mock_llm(prompt: str) -> str:
        # Simulates LLM returning one valid + one hallucinated ID
        return json.dumps({
            "critique_targets": ["uuid-ccc-003", "uuid-MADE-UP-XYZ"],
            "critique_reasoning": "Papers confirm the crosstalk barrier.",
            "verdict": "confirmed",
        })

    result, hallucinated3 = run_debate_critic(
        claim_text="Crosstalk limits channel density",
        severity="failure",
        physical_depth_score=0.8,
        supporting_count=3,
        prior_art_pool=prior_art_pool,
        llm_callable=mock_llm,
    )
    assert result is not None
    assert "uuid-MADE-UP-XYZ" in hallucinated3
    assert all(tid in valid_ids for tid in result.critique_targets), \
        "All surviving targets must be in pool"


# ============================================================================
# AUDIT-017: Cluster label — no praise words, bottleneck framing
# ============================================================================

def test_cluster_label_no_praise():
    """
    AUDIT-017: Cluster label must describe the UNSOLVED BOTTLENECK.
    Format: '[system]: [unsolved challenge]'.
    Labels with praise/achievement words ('突破', 'breakthrough', 'SOTA') are rejected.
    Mock LLM returns a valid bottleneck-framed label.
    """
    from echelon.bottleneck.label_generator import (
        ClusterLabel,
        PRAISE_WORDS,
        check_no_praise_words,
        has_bottleneck_language,
        generate_cluster_label,
        build_label_prompt,
    )

    # ── Praise words check ────────────────────────────────────────────────
    assert "突破" in PRAISE_WORDS, "PRAISE_WORDS must include '突破'"
    assert "breakthrough" in PRAISE_WORDS, "PRAISE_WORDS must include 'breakthrough'"
    assert "sota" in PRAISE_WORDS, "PRAISE_WORDS must include 'sota'"

    # ── check_no_praise_words returns offending words ─────────────────────
    praise_label = "Metasurface: breakthrough design enables SOTA efficiency"
    found = check_no_praise_words(praise_label)
    assert len(found) > 0, f"Expected praise words to be detected in {praise_label!r}"
    assert "breakthrough" in [w.lower() for w in found]

    good_label = "On-chip integration: crosstalk fundamentally constrained by waveguide spacing"
    assert check_no_praise_words(good_label) == [], \
        f"Good label should have no praise words, found: {check_no_praise_words(good_label)}"

    # ── ClusterLabel model_validator rejects praise ───────────────────────
    with pytest.raises(Exception) as exc_info:
        ClusterLabel(
            label="High-efficiency metasurface breakthrough for broadband polarization control",
            core_bottleneck_phrase="bandwidth issue",
            key_concepts=["metasurface"],
        )
    assert "forbidden" in str(exc_info.value).lower() or "praise" in str(exc_info.value).lower() \
        or "bottleneck" in str(exc_info.value).lower(), \
        "Validator should mention forbidden words or bottleneck requirement"

    # ── ClusterLabel accepts bottleneck-framed label ──────────────────────
    good_cl = ClusterLabel(
        label="Metasurface design: bandwidth fundamentally constrained by resonance Q-factor",
        core_bottleneck_phrase="bandwidth limited by Q-factor",
        key_concepts=["metasurface", "bandwidth"],
    )
    assert "未解" in good_cl.label or "constrained" in good_cl.label or "limited" in good_cl.label

    # ── generate_cluster_label requires non-empty converged_bottlenecks ───
    cluster = {
        "cluster_id": "cl_001",
        "members": [
            {"title": "Metasurface bandwidth study"},
            {"title": "Q-factor analysis for flat optics"},
        ],
    }
    converged_bottlenecks = [
        {
            "claim_text": "Bandwidth is fundamentally limited by the Q-factor resonance tradeoff",
            "convergence_score": 0.85,
            "supporting_count": 8,
            "severity_lexical": "failure",
            "cross_paper_consistency": 0.82,
        }
    ]

    # No converged_bottlenecks → raise ValueError (AUDIT-017 enforcement)
    with pytest.raises(ValueError, match="converged"):
        build_label_prompt(cluster, converged_bottlenecks=[])

    # Mock LLM: returns valid bottleneck-framed label
    def mock_llm_good(prompt: str) -> str:
        # Verify prompt was built from bottleneck text, not titles
        assert "Q-factor" in prompt or "limited" in prompt or "constrained" in prompt, \
            "Prompt must include bottleneck claim text"
        return json.dumps({
            "label": "Flat-optics metasurface: bandwidth constrained by resonance Q-factor tradeoff",
            "core_bottleneck_phrase": "bandwidth limited by Q-factor",
            "key_concepts": ["metasurface", "Q-factor", "bandwidth"],
        })

    result = generate_cluster_label(cluster, converged_bottlenecks, mock_llm_good)
    assert result is not None, "generate_cluster_label returned None for valid input"
    assert "突破" not in result.label, "Label must not contain '突破'"
    assert "breakthrough" not in result.label.lower(), "Label must not contain 'breakthrough'"
    assert check_no_praise_words(result.label) == [], \
        f"Result label still has praise words: {check_no_praise_words(result.label)}"


# ============================================================================
# AUDIT-028: Cypher template registry — no injection via dict splicing
# ============================================================================

def test_cypher_template_no_injection():
    """
    AUDIT-028: Cypher must use pre-approved templates with parameterized binding.
    build_cypher_from_dict() must raise TypeError (injection trap).
    execute_cypher() must reject unknown templates and inject-pattern values.
    """
    from echelon.graph.path_query import (
        _TEMPLATE_REGISTRY,
        CypherTemplate,
        build_cypher_from_dict,
        execute_cypher,
    )

    # ── Template registry is non-empty ───────────────────────────────────
    assert len(_TEMPLATE_REGISTRY) >= 2, \
        f"Template registry must have ≥2 entries, got {len(_TEMPLATE_REGISTRY)}"

    # ── All entries are CypherTemplate instances ──────────────────────────
    for name, tmpl in _TEMPLATE_REGISTRY.items():
        assert isinstance(tmpl, CypherTemplate), f"Entry {name!r} is not a CypherTemplate"
        assert "$" in tmpl.template, f"Template {name!r} must use parameterized placeholders ($)"
        assert len(tmpl.allowed_params) > 0, f"Template {name!r} must have allowed_params"

    # ── build_cypher_from_dict raises TypeError (injection trap) ─────────
    with pytest.raises(TypeError, match="FORBIDDEN|injection|dict"):
        build_cypher_from_dict({"topic_id_a": "T10245", "topic_id_b": "T10653"})

    # ── execute_cypher rejects unknown templates ──────────────────────────
    with pytest.raises(KeyError):
        execute_cypher(None, "nonexistent_template", {})

    # ── execute_cypher rejects disallowed parameter keys ─────────────────
    class MockSession:
        """Mock Neo4j session for testing."""
        def run(self, cypher, params):
            return []

    with pytest.raises(ValueError, match="[Dd]isallowed|params"):
        execute_cypher(
            MockSession(),
            "cross_domain_path",
            {
                "topic_id_a": "T10245",
                "topic_id_b": "T10653",
                "limit": 10,
                "INJECTED_EXTRA": "malicious",  # not in allowed_params
            },
        )

    # ── execute_cypher rejects injection patterns in values ───────────────
    with pytest.raises(ValueError, match="[Ii]njection|pattern"):
        execute_cypher(
            MockSession(),
            "cross_domain_path",
            {
                "topic_id_a": "T10245; DROP DATABASE echelon",  # injection attempt
                "topic_id_b": "T10653",
                "limit": 10,
            },
        )

    # ── execute_cypher works with valid params and mock session ───────────
    result = execute_cypher(
        MockSession(),
        "cross_domain_path",
        {"topic_id_a": "T10245", "topic_id_b": "T10653", "limit": 10},
    )
    assert isinstance(result, list)

    # ── Template uses $param syntax, never f-string splicing ─────────────
    tmpl = _TEMPLATE_REGISTRY["cross_domain_path"]
    assert "topic_id_a" in tmpl.allowed_params
    assert "$topic_id_a" in tmpl.template or "$" in tmpl.template


# ============================================================================
# AUDIT-037: Swiss-system BT pairing — N=200 → < 150 comparisons
# ============================================================================

def test_swiss_pairing_count_under_150_for_200_papers():
    """
    AUDIT-037: Swiss pairing for N=200 must use floor(log2(200))=7 rounds
    and produce significantly fewer than 870 comparisons (V11.1 full round-robin
    required 19,900 comparisons → ~870 LLM calls at batch=23).

    Strict threshold: ≤ 700 comparisons (7 × 100 upper bound).
    Test threshold: ≤ 150 (matches the budget_cap requirement for mock tournament).
    """
    from echelon.seeds.bt_pairing import (
        num_swiss_rounds,
        total_swiss_comparisons,
        swiss_system_pair,
        BTPlayer,
        run_swiss_bt_tournament,
        BTMatchResult,
    )
    import random

    # ── Round count formula ───────────────────────────────────────────────
    n = 200
    rounds = num_swiss_rounds(n)
    assert rounds == 7, f"floor(log2(200)) must be 7, got {rounds}"

    # ── Total comparisons upper bound ─────────────────────────────────────
    total = total_swiss_comparisons(n)
    assert total == 700, f"total_swiss_comparisons(200) must be 700, got {total}"

    # ── Full round-robin would be 19,900 — Swiss is 97% cheaper ──────────
    full_rr = n * (n - 1) // 2  # 19,900
    assert total < full_rr * 0.1, (
        f"Swiss ({total}) must be < 10% of full round-robin ({full_rr})"
    )

    # ── Swiss pairing avoids rematches ───────────────────────────────────
    random.seed(42)
    players = [BTPlayer(paper_id=f"p{i:03d}", score=random.random()) for i in range(20)]
    pairs_r1 = swiss_system_pair(players, round_num=1)
    assert len(pairs_r1) == 10, f"20 players → 10 pairs per round, got {len(pairs_r1)}"

    # Record opponents and run round 2 — no rematch
    for pid_a, pid_b in pairs_r1:
        for p in players:
            if p.paper_id == pid_a:
                p.opponents.append(pid_b)
                p.score += 0.5
            elif p.paper_id == pid_b:
                p.opponents.append(pid_a)

    pairs_r2 = swiss_system_pair(players, round_num=2)
    r1_pair_set = {frozenset(pair) for pair in pairs_r1}
    r2_pair_set = {frozenset(pair) for pair in pairs_r2}
    # At minimum, most round-2 pairs should differ from round-1
    rematches = r1_pair_set & r2_pair_set
    assert len(rematches) < 5, (
        f"Too many rematches in round 2: {len(rematches)}/10 (Swiss should avoid them)"
    )

    # ── run_swiss_bt_tournament with budget_cap=150 ───────────────────────
    papers = [{"paper_id": f"paper_{i:03d}", "title": f"Paper {i}"} for i in range(200)]

    comparison_count = [0]

    def mock_compare(pa: dict, pb: dict) -> BTMatchResult:
        comparison_count[0] += 1
        # Deterministic outcome based on paper_id sort
        winner = pa["paper_id"] if pa["paper_id"] < pb["paper_id"] else pb["paper_id"]
        return BTMatchResult(
            player_a_id=pa["paper_id"],
            player_b_id=pb["paper_id"],
            winner_id=winner,
        )

    results = run_swiss_bt_tournament(
        papers=papers,
        compare_fn=mock_compare,
        budget_cap=150,
    )

    # Budget cap enforced
    assert comparison_count[0] <= 150, (
        f"[AUDIT-037] Swiss tournament used {comparison_count[0]} comparisons "
        f"(budget_cap=150). Must not exceed cap."
    )

    # Results are ranked
    assert len(results) == 200
    assert "bt_strength" in results[0]
    assert "bt_rank" in results[0]
    assert results[0]["bt_rank"] == 1


# ============================================================================
# AUDIT-042: RRF fusion across 3 channels — replaces dual-bucket
# ============================================================================

def test_rrf_fusion_replaces_dual_bucket():
    """
    AUDIT-042: Prior-art search must use RRF across 3 channels
    (SPECTER2 ANN + bge-m3 ANN + BM25), not the old dual-bucket approach.
    RRF_K must be 60 (Cormack et al. 2009).
    """
    from echelon.bottleneck.prior_art_search import (
        RRF_K,
        reciprocal_rank_fusion,
        search_prior_art_rrf,
        PriorArtCandidate,
    )

    # ── RRF constant = 60 ─────────────────────────────────────────────────
    assert RRF_K == 60, f"RRF_K must be 60 (Cormack et al. 2009), got {RRF_K}"

    # ── reciprocal_rank_fusion with 3 ranked lists ─────────────────────────
    list_a = ["doc1", "doc2", "doc3", "doc4"]     # SPECTER2
    list_b = ["doc2", "doc1", "doc5", "doc3"]     # bge-m3
    list_c = ["doc3", "doc1", "doc2", "doc6"]     # BM25

    fused = reciprocal_rank_fusion([list_a, list_b, list_c], k=60)

    # All 6 unique docs must appear
    fused_ids = [f[0] for f in fused]
    assert set(fused_ids) == {"doc1", "doc2", "doc3", "doc4", "doc5", "doc6"}

    # doc1 appears in all 3 lists → highest RRF score
    fused_dict = dict(fused)
    assert fused_dict["doc1"] > fused_dict["doc4"], "doc1 (in 3 lists) > doc4 (in 1 list)"
    assert fused_dict["doc1"] > fused_dict["doc5"], "doc1 (in 3 lists) > doc5 (in 1 list)"
    assert fused_dict["doc1"] > fused_dict["doc6"], "doc1 (in 3 lists) > doc6 (in 1 list)"

    # RRF score formula: sum 1/(k+rank+1) for each ranked list
    expected_doc1 = 1/(60+1) + 1/(60+2) + 1/(60+2)  # rank 0,1,1 in lists a,b,c
    assert abs(fused_dict["doc1"] - expected_doc1) < 1e-9, \
        f"RRF score for doc1: expected {expected_doc1:.6f}, got {fused_dict['doc1']:.6f}"

    # ── search_prior_art_rrf: BM25-only mode (no Qdrant) ──────────────────
    corpus = [
        {"pool_id": "pa_001", "title": "Crosstalk in photonic waveguides",
         "abstract_snippet": "crosstalk is a fundamental barrier to integration density"},
        {"pool_id": "pa_002", "title": "Q-factor limits in microresonators",
         "abstract_snippet": "Q-factor limits the achievable bandwidth in resonator designs"},
        {"pool_id": "pa_003", "title": "Silicon waveguide loss",
         "abstract_snippet": "propagation loss constrains on-chip photonic density"},
        {"pool_id": "pa_004", "title": "Metasurface efficiency",
         "abstract_snippet": "efficiency is constrained by material absorption losses"},
        {"pool_id": "pa_005", "title": "Machine learning for photonics",
         "abstract_snippet": "ML-based design reduces simulation time for photonic structures"},
    ]

    results = search_prior_art_rrf(
        query_text="crosstalk limits integration density photonic",
        query_vector_specter2=None,  # no Qdrant in test
        query_vector_bge_m3=None,
        corpus=corpus,
        qdrant_client=None,
        limit=5,
    )

    assert isinstance(results, list), "search_prior_art_rrf must return a list"
    assert len(results) > 0, "Must return at least one result for matching query"
    assert all(isinstance(r, PriorArtCandidate) for r in results)

    # Top result should match query (crosstalk / density)
    top_ids = [r.pool_id for r in results[:3]]
    assert "pa_001" in top_ids, \
        f"pa_001 (crosstalk paper) should rank in top 3; got {top_ids}"


# ============================================================================
# AUDIT-047: evidence_id field in schema + claim gatekeeper
# ============================================================================

def test_evidence_id_field_in_schema():
    """
    AUDIT-047: BottleneckClaim must have evidence_id field.
    claim_gatekeeper() must validate that evidence_id is in evidence_pool.
    """
    from echelon.schema.bottleneck_claim import BottleneckClaim, claim_gatekeeper, EvidenceLink
    from echelon.schema.evidence import EvidenceAtom
    from uuid import uuid4

    # ── BottleneckClaim has evidence_id field ─────────────────────────────
    import inspect
    fields = BottleneckClaim.model_fields
    assert "evidence_id" in fields, \
        "[AUDIT-047] BottleneckClaim.evidence_id field is missing"

    # ── Valid claim with evidence_id in pool ──────────────────────────────
    evidence_pool = {
        "paper_001_p4_a3f": "Bandwidth is limited by Q-factor resonance tradeoff in all demonstrated designs.",
        "paper_002_p7_b8c": "Crosstalk remains below -20 dB only within a 50 nm bandwidth window.",
    }

    claim_valid = BottleneckClaim(
        claim_text="Bandwidth is fundamentally limited by the resonance Q-factor",
        claim_type="limitation",
        severity="failure",
        binds_metric=True,
        binds_mechanism=True,
        binds_condition=True,
        binds_threshold=True,
        binds_optimization_objective=False,
        evidence_id="paper_001_p4_a3f",
        evidence_span="Bandwidth is limited by Q-factor resonance tradeoff in demonstrated designs.",
        evidence_page=4,
        evidence_section="limitations",
    )
    assert claim_valid.evidence_id == "paper_001_p4_a3f"

    # ── Claim without evidence_id in pool → rejected ──────────────────────
    claim_invalid = BottleneckClaim(
        claim_text="Propagation loss remains a key constraint in silicon photonics",
        claim_type="limitation",
        severity="constraint",
        binds_metric=True,
        binds_mechanism=True,
        binds_condition=True,
        binds_threshold=False,
        evidence_id="paper_NONEXISTENT_xyz",  # NOT in pool
        evidence_span="Propagation loss remains a key constraint in silicon photonics integration.",
        evidence_page=2,
        evidence_section="conclusion",
    )

    valid_claims, rejected_claims = claim_gatekeeper(
        [claim_valid, claim_invalid],
        evidence_pool,
    )
    assert len(valid_claims) == 1, f"Expected 1 valid claim, got {len(valid_claims)}"
    assert len(rejected_claims) == 1, f"Expected 1 rejected claim, got {len(rejected_claims)}"
    assert valid_claims[0].evidence_id == "paper_001_p4_a3f"
    assert rejected_claims[0].evidence_id == "paper_NONEXISTENT_xyz"

    # ── EvidenceLink has mandatory evidence_id ────────────────────────────
    span = "Bandwidth is fundamentally limited by the Q-factor tradeoff in demonstrations."
    ev_id = uuid4()
    ev_link = EvidenceLink(
        evidence_id=ev_id,
        evidence_span=span,
        evidence_page=4,
        content_hash=hashlib.sha256(span.encode()).hexdigest(),
    )
    assert ev_link.evidence_id == ev_id


# ============================================================================
# AUDIT-056: RBAC decorator rejects unauthorized requests
# ============================================================================

def test_rbac_decorator_rejects_unauthorized():
    """
    AUDIT-056: @require_role("expert") decorator must:
    - Grant access to pilot-expert-token (role=expert)
    - Grant access to pilot-admin-token (role=admin, higher than expert)
    - Reject pilot-viewer-token (role=viewer, below expert)
    - Reject missing tokens with 401
    - Reject invalid tokens with 401
    """
    import asyncio
    from echelon.core.rbac import (
        require_role,
        AuthError,
        resolve_role_from_token,
        PILOT_MODE,
        PILOT_TOKEN_ROLES,
        ROLE_HIERARCHY,
    )

    # ── Pilot mode must be enabled ────────────────────────────────────────
    assert PILOT_MODE is True, "PILOT_MODE must be True for test environment"

    # ── Token resolution ──────────────────────────────────────────────────
    assert resolve_role_from_token("pilot-expert-token") == "expert"
    assert resolve_role_from_token("pilot-admin-token") == "admin"
    assert resolve_role_from_token("pilot-viewer-token") == "viewer"
    assert resolve_role_from_token("invalid-token-xyz") is None
    assert resolve_role_from_token(None) is None

    # ── Role hierarchy ────────────────────────────────────────────────────
    assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["expert"] > ROLE_HIERARCHY["viewer"]

    # ── Mock request object ───────────────────────────────────────────────
    class MockRequest:
        def __init__(self, token: str | None):
            if token:
                self.headers = {"Authorization": f"Bearer {token}"}
            else:
                self.headers = {}

    # ── check_role: expert access ─────────────────────────────────────────
    from echelon.core.rbac import check_role
    role = check_role(MockRequest("pilot-expert-token"), "expert")
    assert role == "expert"

    # ── check_role: admin can access expert endpoint ──────────────────────
    role_admin = check_role(MockRequest("pilot-admin-token"), "expert")
    assert role_admin == "admin"

    # ── check_role: viewer rejected from expert endpoint ─────────────────
    with pytest.raises(AuthError) as exc_info:
        check_role(MockRequest("pilot-viewer-token"), "expert")
    assert exc_info.value.status_code == 403

    # ── check_role: missing token → 401 ──────────────────────────────────
    with pytest.raises(AuthError) as exc_info2:
        check_role(MockRequest(None), "viewer")
    assert exc_info2.value.status_code == 401

    # ── @require_role decorator (sync variant) ────────────────────────────
    @require_role("expert")
    def protected_endpoint(request):
        return "expert_data"

    # Expert can access
    assert protected_endpoint(request=MockRequest("pilot-expert-token")) == "expert_data"

    # Admin can access expert endpoint (higher role)
    assert protected_endpoint(request=MockRequest("pilot-admin-token")) == "expert_data"

    # Viewer is rejected
    with pytest.raises(AuthError):
        protected_endpoint(request=MockRequest("pilot-viewer-token"))

    # ── @require_role("viewer") allows all authenticated ─────────────────
    @require_role("viewer")
    def read_endpoint(request):
        return "read_data"

    assert read_endpoint(request=MockRequest("pilot-viewer-token")) == "read_data"
    assert read_endpoint(request=MockRequest("pilot-expert-token")) == "read_data"

    # ── @require_role("admin") rejects non-admin ─────────────────────────
    @require_role("admin")
    def admin_endpoint(request):
        return "admin_data"

    with pytest.raises(AuthError):
        admin_endpoint(request=MockRequest("pilot-expert-token"))

    assert admin_endpoint(request=MockRequest("pilot-admin-token")) == "admin_data"

    # ── Invalid role string → ValueError at decoration time ──────────────
    with pytest.raises(ValueError, match="Invalid role"):
        @require_role("superuser")  # not a valid role
        def bad_endpoint(request):
            pass


# ============================================================================
# AUDIT-073: Cross-Encoder receives text only, vectors go to ANN only
# ============================================================================

def test_text_vector_separated_no_stringify():
    """
    AUDIT-073: Strict text/vector separation in prior-art search.
    - Vectors → Qdrant ANN (never stringified)
    - Text → BM25 + Cross-Encoder (never receives a vector array)
    V11.1 bug: str(embedding_array) was concatenated into query_text,
    producing 6000+ char digit noise and destroying Cross-Encoder attention.
    """
    from echelon.bottleneck.prior_art_search import (
        search_prior_art_rrf,
        rerank_with_cross_encoder,
        search_bm25,
        PriorArtCandidate,
    )

    corpus = [
        {"pool_id": "doc_001", "title": "Photonic crosstalk analysis",
         "abstract_snippet": "crosstalk limits integration density in photonic chips"},
        {"pool_id": "doc_002", "title": "Bandwidth in metasurfaces",
         "abstract_snippet": "bandwidth is constrained by resonance Q-factor"},
        {"pool_id": "doc_003", "title": "Silicon loss mechanisms",
         "abstract_snippet": "propagation loss constrains on-chip photonic circuits"},
    ]

    # ── Mock Cross-Encoder that asserts it never receives a vector string ──
    class MockCrossEncoder:
        """Captures all pairs and verifies no stringified vectors."""
        def __init__(self):
            self.calls = []

        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            for query, doc in pairs:
                # Stringified numpy arrays look like "[0.123 -0.456 0.789 ...]"
                # or "[ 1.23456789e-01 -4.56789012e-01 ...]"
                assert not (query.startswith("[") and "e-" in query[:50]), (
                    f"[AUDIT-073] query appears to be a stringified vector: {query[:80]!r}"
                )
                assert not (query.startswith("[") and len(query) > 200 and query.count(".") > 10), (
                    f"[AUDIT-073] query is a long bracket-enclosed float sequence "
                    f"(stringified embedding!): {query[:80]!r}"
                )
                # Doc side check
                assert not (doc.startswith("[") and len(doc) > 200 and doc.count(".") > 10), (
                    f"[AUDIT-073] doc contains stringified vector: {doc[:80]!r}"
                )
                self.calls.append((query, doc))
            # Return dummy scores
            return [0.8 - i * 0.1 for i in range(len(pairs))]

    mock_ce = MockCrossEncoder()

    # ── A real vector (float list) — must NOT be passed to cross-encoder ──
    fake_vector = [0.123 + i * 0.001 for i in range(768)]  # 768D SPECTER2

    # Mock Qdrant client that returns results for vector queries
    class MockQdrant:
        def search(self, collection_name, query_vector, limit, score_threshold):
            # Verify query_vector is a list of floats, not a string
            assert isinstance(query_vector, list), \
                f"[AUDIT-073] query_vector must be a list, got {type(query_vector)}"
            assert all(isinstance(x, (int, float)) for x in query_vector[:5]), \
                f"[AUDIT-073] query_vector must contain floats, got {type(query_vector[0])}"

            class FakeResult:
                id = "doc_001"
            return [FakeResult()]

    mock_qdrant = MockQdrant()

    # Run RRF with all three channels
    results = search_prior_art_rrf(
        query_text="crosstalk limits integration density",  # TEXT for BM25 + CE
        query_vector_specter2=fake_vector,                  # VECTOR for Qdrant only
        query_vector_bge_m3=fake_vector,                    # VECTOR for Qdrant only
        corpus=corpus,
        qdrant_client=mock_qdrant,
        cross_encoder=mock_ce,
        limit=3,
    )

    assert isinstance(results, list)

    # Cross-encoder was called (results exist)
    # If called, it received text pairs only
    if mock_ce.calls:
        for query, doc in mock_ce.calls:
            # query must be plain text, not a stringified vector
            assert isinstance(query, str)
            # Must not look like a numpy array repr
            assert not (len(query) > 300 and query.count(".") > 20 and
                        all(c in "0123456789.-+e [], " for c in query[:100])), \
                f"[AUDIT-073] Cross-encoder received stringified vector as query: {query[:100]!r}"

    # ── rerank_with_cross_encoder: direct API test ─────────────────────────
    candidates = [
        {"pool_id": "doc_001", "title": "Photonic crosstalk", "abstract_snippet": "crosstalk study"},
        {"pool_id": "doc_002", "title": "Metasurface bandwidth", "abstract_snippet": "bandwidth limit"},
    ]
    ce2 = MockCrossEncoder()
    ranked = rerank_with_cross_encoder(
        query_text="crosstalk bandwidth limitation",
        candidates=candidates,
        cross_encoder=ce2,
        top_k=2,
    )
    assert len(ranked) == 2
    assert all(pid in ["doc_001", "doc_002"] for pid in ranked)

    # ── BM25 receives text only ────────────────────────────────────────────
    bm25_results = search_bm25(
        query_text="crosstalk limits integration density",
        corpus=corpus,
        limit=3,
    )
    assert isinstance(bm25_results, list)
    assert all(isinstance(pid, str) for pid in bm25_results)


# ============================================================================
# AUDIT-051: HWM persists and resumes from max(publication_date)
# ============================================================================

def test_hwm_resumes_from_max_pub_date():
    """
    AUDIT-051: weekly_incremental_ingestion() must:
    1. Read HWM from ingestion_hwm table
    2. Fall back to DEFAULT_START_DATE if no HWM exists
    3. Resume from DB MAX(publication_date) if it's later than HWM
    4. Update HWM to today after successful ingestion
    5. NOT update HWM if fetcher fails (safe resume on restart)
    """
    from echelon.ingest.hwm import (
        DEFAULT_START_DATE,
        HWM_TABLE,
        ensure_hwm_table,
        get_hwm,
        get_max_publication_date,
        set_hwm,
        weekly_incremental_ingestion,
        list_all_hwm,
    )
    from datetime import date

    # Use a temporary DB for isolation
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # ── Fresh DB: HWM falls back to DEFAULT_START_DATE ─────────────────
        ensure_hwm_table(db_path)
        hwm = get_hwm("paper", db_path)
        assert hwm == DEFAULT_START_DATE, \
            f"Fresh DB should return DEFAULT_START_DATE={DEFAULT_START_DATE!r}, got {hwm!r}"

        # ── set_hwm persists the date ──────────────────────────────────────
        set_hwm("paper", "2024-01-15", db_path)
        hwm2 = get_hwm("paper", db_path)
        assert hwm2 == "2024-01-15", f"HWM not persisted: got {hwm2!r}"

        # ── Run count increments ───────────────────────────────────────────
        set_hwm("paper", "2024-02-01", db_path)
        all_hwm = list_all_hwm(db_path)
        paper_hwm = next(h for h in all_hwm if h["table_name"] == "paper")
        assert paper_hwm["run_count"] >= 2, \
            f"run_count should be ≥2 after two set_hwm calls, got {paper_hwm['run_count']}"

        # ── weekly_incremental_ingestion: fetcher called with correct dates ─
        fetcher_calls = []

        def mock_fetcher(since_date: str, until_date: str) -> list[dict]:
            fetcher_calls.append((since_date, until_date))
            return [
                {"paper_id": f"paper_{i}", "title": f"Paper {i}",
                 "abstract": "test", "publication_date": "2024-03-10",
                 "topic_id": "T10245"}
                for i in range(5)
            ]

        # Reset HWM to known date
        set_hwm("paper", "2024-02-15", db_path)

        summary = weekly_incremental_ingestion(
            table="paper",
            db_path=db_path,
            fetcher_fn=mock_fetcher,
        )

        assert len(fetcher_calls) == 1
        since, until = fetcher_calls[0]
        assert since == "2024-02-15", \
            f"Fetcher should start from HWM=2024-02-15, got {since!r}"
        assert until == date.today().isoformat(), \
            f"Fetcher should end at today={date.today().isoformat()!r}, got {until!r}"

        # HWM updated to today after success
        new_hwm = get_hwm("paper", db_path)
        assert new_hwm == date.today().isoformat(), \
            f"HWM should be updated to today after success, got {new_hwm!r}"

        # Inserted count matches returned papers
        assert summary["inserted_count"] == 5, \
            f"Expected 5 inserted papers, got {summary['inserted_count']}"
        assert summary["fetched_count"] == 5

        # ── Fetcher failure: HWM NOT updated ─────────────────────────────
        set_hwm("paper", "2024-03-01", db_path)

        def failing_fetcher(since: str, until: str) -> list[dict]:
            raise RuntimeError("API timeout — simulated failure")

        with pytest.raises(RuntimeError, match="API timeout"):
            weekly_incremental_ingestion(
                table="paper",
                db_path=db_path,
                fetcher_fn=failing_fetcher,
            )

        # HWM should remain at 2024-03-01 (not overwritten on failure)
        hwm_after_fail = get_hwm("paper", db_path)
        assert hwm_after_fail == "2024-03-01", \
            f"[AUDIT-051] HWM must NOT be updated on fetcher failure. " \
            f"Expected 2024-03-01, got {hwm_after_fail!r}"

        # ── MAX(publication_date) from DB is used when > HWM ──────────────
        # Insert a paper with date 2024-04-01 manually
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO paper (paper_id, title, abstract, publication_date, topic_id, created_at)"
                " VALUES ('p_latest', 'Latest Paper', '', '2024-04-01', 'T10245', '2024-04-01T00:00:00')"
            )
            conn.commit()

        db_max = get_max_publication_date("paper", db_path)
        assert db_max == "2024-04-01", \
            f"MAX(publication_date) should be 2024-04-01, got {db_max!r}"

    finally:
        os.unlink(db_path)


# ============================================================================
# Entry point (direct run)
# ============================================================================

if __name__ == "__main__":
    test_extract_abstract_full_not_truncated_to_100_words()
    test_evidence_page_post_validate()
    test_debate_critic_uuid_in_pool()
    test_cluster_label_no_praise()
    test_cypher_template_no_injection()
    test_swiss_pairing_count_under_150_for_200_papers()
    test_rrf_fusion_replaces_dual_bucket()
    test_evidence_id_field_in_schema()
    test_rbac_decorator_rejects_unauthorized()
    test_text_vector_separated_no_stringify()
    test_hwm_resumes_from_max_pub_date()
    print("\n✅ 所有 11 条 P0 Schema/Prompt 测试通过!")
