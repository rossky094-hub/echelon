"""
P1 Schema/Prompt 6条 单元测试
=================================
每条 AUDIT 对应测试函数。涵盖 AUDIT-018, 021, 044, 057, 058, 085。

运行: pytest tests/test_p1_schema_prompt.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import warnings

import pytest

# 确保 echelon 包可被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# AUDIT-018: constraint_inversion → attempted_circumvention + claimed_resolution
# ============================================================================

def test_audit_018_schema_fields():
    """
    AUDIT-018: BottleneckClaim must have attempted_circumvention and
    claimed_resolution as list[EvidenceLink], not the old constraint_inversion str.

    attempted_circumvention = small positive signal (workaround attempt)
    claimed_resolution      = negative signal (full fix claim)
    """
    from echelon.schema.bottleneck_claim import BottleneckClaim

    fields = BottleneckClaim.model_fields

    # Old field must NOT exist
    assert "constraint_inversion" not in fields, (
        "[AUDIT-018] constraint_inversion field still exists — should be removed"
    )

    # New fields must exist
    assert "attempted_circumvention" in fields, (
        "[AUDIT-018] attempted_circumvention field missing from BottleneckClaim"
    )
    assert "claimed_resolution" in fields, (
        "[AUDIT-018] claimed_resolution field missing from BottleneckClaim"
    )

    # resolution_verified must remain
    assert "resolution_verified" in fields, (
        "[AUDIT-018] resolution_verified field missing"
    )

    # Both new fields must be Optional (nullable)
    circ_info = fields["attempted_circumvention"]
    res_info = fields["claimed_resolution"]
    # Pydantic default should be None (Optional)
    assert circ_info.default is None or circ_info.is_required() is False, (
        "[AUDIT-018] attempted_circumvention should be Optional with default None"
    )


def test_audit_018_claim_with_circumvention():
    """
    AUDIT-018: BottleneckClaim can be created with attempted_circumvention as list.
    """
    from uuid import uuid4
    from echelon.schema.bottleneck_claim import BottleneckClaim, EvidenceLink

    span = "The paper attempts to bypass Q-factor limits via coupled resonances."
    ev = EvidenceLink(
        evidence_id=uuid4(),
        evidence_span=span,
        evidence_page=3,
        content_hash=hashlib.sha256(span.encode()).hexdigest(),
    )

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        claim = BottleneckClaim(
            claim_text="Bandwidth fundamentally limited by Q-factor resonance",
            claim_type="limitation",
            severity="failure",
            binds_metric=True,
            binds_mechanism=True,
            binds_condition=True,
            binds_threshold=True,
            binds_optimization_objective=False,
            evidence_id="paper_001_p3_abc",
            evidence_span="Bandwidth fundamentally limited by Q-factor resonance.",
            evidence_page=3,
            evidence_section="limitations",
            attempted_circumvention=[ev],    # small positive signal
            claimed_resolution=None,         # no resolution claimed
        )

    assert claim.attempted_circumvention is not None
    assert len(claim.attempted_circumvention) == 1
    assert claim.attempted_circumvention[0].evidence_span == span
    assert claim.claimed_resolution is None
    assert claim.resolution_verified is False


def test_audit_018_claimed_resolution_negative_signal():
    """
    AUDIT-018: claimed_resolution carries the negative signal; if non-empty,
    the claim may not be a genuine open bottleneck (needs verification).
    """
    from uuid import uuid4
    from echelon.schema.bottleneck_claim import BottleneckClaim, EvidenceLink

    span_res = "Our method completely eliminates crosstalk below -60 dB."
    ev_res = EvidenceLink(
        evidence_id=uuid4(),
        evidence_span=span_res,
        evidence_page=5,
        content_hash=hashlib.sha256(span_res.encode()).hexdigest(),
    )

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        claim = BottleneckClaim(
            claim_text="Crosstalk limits channel density in photonic chips",
            claim_type="limitation",
            severity="failure",
            binds_metric=True,
            binds_mechanism=True,
            binds_condition=True,
            binds_threshold=False,
            evidence_id="paper_002_p5_def",
            evidence_span="Crosstalk limits channel density in photonic chip designs.",
            evidence_page=5,
            evidence_section="discussion",
            attempted_circumvention=None,
            claimed_resolution=[ev_res],  # negative signal
        )

    assert claim.claimed_resolution is not None
    assert len(claim.claimed_resolution) == 1
    assert "eliminates" in claim.claimed_resolution[0].evidence_span


# ============================================================================
# AUDIT-021: Prompt 6-property explicit listing + Pydantic empty warning
# ============================================================================

def test_audit_021_prompt_has_6_properties():
    """
    AUDIT-021: CLAIM_EXTRACTION_PROMPT_V2 must explicitly list all 6 property groups.
    """
    from echelon.bottleneck.extract_claim import (
        CLAIM_EXTRACTION_PROMPT_V2,
        build_claim_extraction_prompt,
    )

    # Check prompt template contains key terms for all 6 properties
    # 1. claim_text
    assert "claim_text" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing claim_text"
    # 2. claim_type / severity
    assert "claim_type" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing claim_type"
    assert "severity" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing severity"
    # 3. physical depth binds_*
    assert "binds_metric" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing binds_metric"
    assert "binds_mechanism" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing binds_mechanism"
    assert "binds_condition" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing binds_condition"
    assert "binds_threshold" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing binds_threshold"
    assert "binds_optimization_objective" in CLAIM_EXTRACTION_PROMPT_V2, \
        "Prompt missing binds_optimization_objective"
    # 4. evidence fields
    assert "evidence_id" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing evidence_id"
    assert "evidence_span" in CLAIM_EXTRACTION_PROMPT_V2, "Prompt missing evidence_span"
    # 5. attempted_circumvention (AUDIT-018 property)
    assert "attempted_circumvention" in CLAIM_EXTRACTION_PROMPT_V2, \
        "[AUDIT-021] Prompt missing attempted_circumvention"
    # 6. claimed_resolution (AUDIT-018 property)
    assert "claimed_resolution" in CLAIM_EXTRACTION_PROMPT_V2, \
        "[AUDIT-021] Prompt missing claimed_resolution"

    # The prompt distinguishes the two semantics
    assert "small positive" in CLAIM_EXTRACTION_PROMPT_V2 or \
           "AUDIT-018" in CLAIM_EXTRACTION_PROMPT_V2, \
        "Prompt should distinguish attempted_circumvention from claimed_resolution semantics"


def test_audit_021_pydantic_empty_warning():
    """
    AUDIT-021: BottleneckClaim must emit UserWarning (non-blocking) when both
    attempted_circumvention and claimed_resolution are empty/None.
    """
    from echelon.schema.bottleneck_claim import BottleneckClaim

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        claim = BottleneckClaim(
            claim_text="Bandwidth limited by Q-factor in demonstrated designs",
            claim_type="limitation",
            severity="failure",
            binds_metric=True,
            binds_mechanism=True,
            binds_condition=True,
            binds_threshold=True,
            evidence_id="paper_003_p1_ghi",
            evidence_span="Bandwidth limited by Q-factor in demonstrated designs.",
            evidence_page=1,
            evidence_section="abstract",
            attempted_circumvention=None,   # both empty → warning
            claimed_resolution=None,
        )

    # Must emit at least one UserWarning containing AUDIT-021
    audit_021_warnings = [
        x for x in w
        if issubclass(x.category, UserWarning)
        and "AUDIT-021" in str(x.message)
    ]
    assert len(audit_021_warnings) > 0, (
        "[AUDIT-021] Expected UserWarning when both anti-incremental fields are empty"
    )

    # Must NOT raise — non-blocking
    assert claim is not None, "Claim construction must succeed (warning is non-blocking)"


def test_audit_021_no_warning_when_fields_populated():
    """
    AUDIT-021: No UserWarning when at least one of the anti-incremental fields
    is non-empty.
    """
    from uuid import uuid4
    from echelon.schema.bottleneck_claim import BottleneckClaim, EvidenceLink

    span = "The paper attempts to bypass limits using coupled resonator array."
    ev = EvidenceLink(
        evidence_id=uuid4(),
        evidence_span=span,
        evidence_page=2,
        content_hash=hashlib.sha256(span.encode()).hexdigest(),
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        BottleneckClaim(
            claim_text="Silicon waveguide loss constrains integration density",
            claim_type="limitation",
            severity="constraint",
            binds_metric=True,
            binds_mechanism=True,
            binds_condition=True,
            binds_threshold=False,
            evidence_id="paper_004_p2_jkl",
            evidence_span="Silicon waveguide loss constrains photonic integration density.",
            evidence_page=2,
            evidence_section="discussion",
            attempted_circumvention=[ev],  # non-empty → no warning
            claimed_resolution=None,
        )

    audit_021_warnings = [
        x for x in w
        if issubclass(x.category, UserWarning)
        and "AUDIT-021" in str(x.message)
    ]
    assert len(audit_021_warnings) == 0, (
        "[AUDIT-021] Should NOT emit warning when attempted_circumvention is non-empty"
    )


def test_audit_021_parse_claim_response_defaults_to_empty_lists():
    """
    AUDIT-021: parse_claim_extraction_response must default attempted_circumvention
    and claimed_resolution to [] when LLM omits them.
    """
    from echelon.bottleneck.extract_claim import parse_claim_extraction_response

    # LLM output omitting both AUDIT-018 fields
    llm_output = json.dumps([
        {
            "claim_text": "Propagation loss limits waveguide integration density",
            "claim_type": "limitation",
            "severity": "constraint",
            "binds_metric": True,
            "binds_mechanism": True,
            "binds_condition": True,
            "binds_threshold": False,
            "binds_optimization_objective": False,
            "metric_value": None,
            "metric_unit": None,
            "evidence_id": "paper_005_p1_mno",
            "evidence_span": "Propagation loss limits waveguide integration density.",
            "evidence_page": 1,
            "evidence_section": "abstract",
            # NOTE: attempted_circumvention and claimed_resolution intentionally omitted
        }
    ])

    valid, rejected = parse_claim_extraction_response(llm_output, "paper_005")
    assert len(valid) == 1
    assert len(rejected) == 0
    # Defaults must be injected
    assert valid[0]["attempted_circumvention"] == [], \
        "[AUDIT-021] attempted_circumvention should default to []"
    assert valid[0]["claimed_resolution"] == [], \
        "[AUDIT-021] claimed_resolution should default to []"


# ============================================================================
# AUDIT-044: SPECTER2 context window + bge-m3 fallback
# ============================================================================

def test_audit_044_embed_claim_with_context_includes_neighbors():
    """
    AUDIT-044: embed_claim_with_context must return a string containing the
    claim sentence PLUS ±1 surrounding sentences from the abstract.
    """
    from echelon.bottleneck.prior_art_search import embed_claim_with_context

    abstract = (
        "Metasurfaces enable precise wavefront control at subwavelength scales. "
        "However, bandwidth is fundamentally limited by the resonance Q-factor. "
        "This constraint remains an open challenge in current flat-optics designs."
    )
    claim = "However, bandwidth is fundamentally limited by the resonance Q-factor."

    result = embed_claim_with_context(claim, abstract, window=1)

    # Must return a string
    assert isinstance(result, str)

    # Must contain the preceding context (Metasurfaces...)
    assert "Metasurfaces" in result, (
        "[AUDIT-044] embed_claim_with_context must include preceding sentence"
    )

    # Must contain the following context (This constraint...)
    assert "This constraint" in result or "challenge" in result, (
        "[AUDIT-044] embed_claim_with_context must include following sentence"
    )

    # Must contain the claim itself
    assert "Q-factor" in result, (
        "[AUDIT-044] embed_claim_with_context must contain the claim sentence"
    )


def test_audit_044_embed_claim_fallback_when_abstract_empty():
    """
    AUDIT-044: embed_claim_with_context falls back to the claim itself when
    the abstract is empty.
    """
    from echelon.bottleneck.prior_art_search import embed_claim_with_context

    claim = "Crosstalk limits photonic integration density."
    result = embed_claim_with_context(claim, "", window=1)
    assert result == claim, (
        "[AUDIT-044] Should return claim unchanged when abstract is empty"
    )

    result2 = embed_claim_with_context(claim, None, window=1)
    assert result2 == claim


def test_audit_044_embed_claim_window_0_returns_claim():
    """
    AUDIT-044: window=0 should return only the matching claim sentence.
    """
    from echelon.bottleneck.prior_art_search import embed_claim_with_context

    abstract = (
        "First sentence with context. "
        "Bandwidth limited by Q-factor. "
        "Third sentence after."
    )
    claim = "Bandwidth limited by Q-factor."
    result = embed_claim_with_context(claim, abstract, window=0)
    assert isinstance(result, str)
    # With window=0, should only return the matched sentence
    assert "First sentence" not in result
    assert "Third sentence" not in result


def test_audit_044_bge_m3_fallback_function_exists():
    """
    AUDIT-044: embed_text_with_bge_m3 function must exist and accept text.
    When no model libraries are installed, it should return None (not raise).
    """
    from echelon.bottleneck.prior_art_search import embed_text_with_bge_m3

    # Call with no pre-loaded model; will attempt imports and gracefully fail
    result = embed_text_with_bge_m3("Test embedding text for bge-m3 fallback")
    # Must not raise; may return None if libraries not installed
    assert result is None or isinstance(result, list), (
        "[AUDIT-044] embed_text_with_bge_m3 must return list[float] or None"
    )


def test_audit_044_bge_m3_with_mock_model():
    """
    AUDIT-044: embed_text_with_bge_m3 works with a pre-loaded mock model.
    """
    from echelon.bottleneck.prior_art_search import embed_text_with_bge_m3

    class MockBGEModel:
        """Mock bge-m3 model with encode() API."""
        def encode(self, texts, max_length=512):
            # Return a simple mock embedding
            return [[0.1, 0.2, 0.3, 0.4] * 192]  # 768D mock

    mock_model = MockBGEModel()
    result = embed_text_with_bge_m3("test text", bge_model=mock_model)
    assert result is not None, "[AUDIT-044] Should return embedding from mock model"
    assert isinstance(result, list), "[AUDIT-044] Result must be a list"
    assert len(result) == 768


# ============================================================================
# AUDIT-057: evidence_span ≥3 sentences + pronoun resolution stub
# ============================================================================

def test_audit_057_extend_evidence_with_context():
    """
    AUDIT-057: extend_evidence_with_context must expand a single claim sentence
    to include ±1 surrounding sentences (≥3 sentences total when available).
    """
    from echelon.pdf.sentence_split import extend_evidence_with_context

    abstract = (
        "Photonic integration has advanced rapidly over the past decade. "
        "Bandwidth is fundamentally limited by the Q-factor resonance tradeoff. "
        "This constraint prevents scaling beyond 50 channels in practice."
    )
    claim = "Bandwidth is fundamentally limited by the Q-factor resonance tradeoff."

    result = extend_evidence_with_context(claim, abstract, window=1)

    assert isinstance(result, str)
    # Should contain preceding context
    assert "Photonic" in result, (
        "[AUDIT-057] extend_evidence_with_context missing preceding sentence"
    )
    # Should contain following context
    assert "constraint" in result or "channels" in result, (
        "[AUDIT-057] extend_evidence_with_context missing following sentence"
    )
    # Should contain the claim
    assert "Q-factor" in result


def test_audit_057_extend_evidence_fallback():
    """
    AUDIT-057: extend_evidence_with_context returns the claim unchanged when
    the abstract is empty or None.
    """
    from echelon.pdf.sentence_split import extend_evidence_with_context

    claim = "Bandwidth is limited by the Q-factor."
    assert extend_evidence_with_context(claim, "") == claim
    assert extend_evidence_with_context(claim, None) == claim


def test_audit_057_resolve_pronouns_stub():
    """
    AUDIT-057: resolve_pronouns stub must exist, accept text, and return a string.
    The stub is a no-op for Pilot; it must NOT raise.
    """
    from echelon.pdf.sentence_split import resolve_pronouns

    text_with_pronouns = (
        "The Q-factor limits bandwidth. It also constrains the operating range. "
        "They have been studied extensively."
    )
    result = resolve_pronouns(text_with_pronouns)
    assert isinstance(result, str), "[AUDIT-057] resolve_pronouns must return str"
    # Stub may return unchanged text — that's acceptable for Pilot
    assert len(result) > 0


def test_audit_057_extend_and_resolve():
    """
    AUDIT-057: extend_and_resolve convenience function applies both operations.
    """
    from echelon.pdf.sentence_split import extend_and_resolve

    abstract = (
        "Silicon waveguides exhibit propagation loss. "
        "This constrains integration density. "
        "Future designs must address it."
    )
    result = extend_and_resolve(
        "This constrains integration density.",
        abstract,
        window=1,
    )
    assert isinstance(result, str)
    # Must include at least the claim sentence
    assert "constrains" in result or "integration" in result


def test_audit_057_window_produces_minimum_3_sentences():
    """
    AUDIT-057: With window=1 on a 5-sentence abstract, the result must span
    at least the claim sentence plus its immediate neighbours.
    """
    from echelon.pdf.sentence_split import extend_evidence_with_context

    abstract = (
        "Introduction sentence one. "
        "Background sentence two. "
        "Bandwidth limited by Q-factor resonance constraint. "
        "Discussion sentence four. "
        "Conclusion sentence five."
    )
    claim = "Bandwidth limited by Q-factor resonance constraint."
    result = extend_evidence_with_context(claim, abstract, window=1)

    # Should include sentence 2 (before), 3 (claim), and 4 (after)
    assert "Background" in result or "two" in result, \
        "[AUDIT-057] Should include sentence before claim"
    assert "Discussion" in result or "four" in result, \
        "[AUDIT-057] Should include sentence after claim"
    assert "Q-factor" in result


# ============================================================================
# AUDIT-058: SELF_PRAISE_PATTERNS — check before NEGATION, no false positives
# ============================================================================

def test_audit_058_self_praise_patterns_exist():
    """
    AUDIT-058: SELF_PRAISE_PATTERNS must be defined with ≥9 patterns.
    """
    from echelon.pdf.extract_evidence import SELF_PRAISE_PATTERNS

    assert isinstance(SELF_PRAISE_PATTERNS, list), \
        "[AUDIT-058] SELF_PRAISE_PATTERNS must be a list"
    assert len(SELF_PRAISE_PATTERNS) >= 9, (
        f"[AUDIT-058] Expected ≥9 SELF_PRAISE_PATTERNS, got {len(SELF_PRAISE_PATTERNS)}"
    )


def test_audit_058_outperforms_sota_is_self_praise():
    """
    AUDIT-058: A sentence containing 'outperforms SOTA by 5%' must be flagged
    as self-praise and NOT treated as a bottleneck evidence cue.
    """
    from echelon.pdf.extract_evidence import is_self_praise

    # The key AUDIT-058 test case: this MUST be caught
    assert is_self_praise("Our model outperforms SOTA by 5% on all benchmarks"), (
        "[AUDIT-058] 'outperforms SOTA by 5%' must be detected as self-praise"
    )


def test_audit_058_self_praise_detection():
    """
    AUDIT-058: Various self-praise patterns must be correctly detected.
    """
    from echelon.pdf.extract_evidence import is_self_praise

    self_praise_examples = [
        "Our method outperforms all prior methods by 8%.",
        "The system achieves state-of-the-art performance.",
        "It works perfectly without tuning in all conditions.",
        "The model never degrades under high temperature.",
        "Our approach is not limited by traditional bounds.",
        "This technique completely eliminates crosstalk noise.",
        "The design surpasses all existing metasurface baselines.",
        "Performance is achieved without any compromise in quality.",
        "Our framework significantly outperforms the baseline model.",
    ]

    for text in self_praise_examples:
        assert is_self_praise(text), (
            f"[AUDIT-058] Expected is_self_praise=True for: {text!r}"
        )


def test_audit_058_genuine_bottleneck_not_self_praise():
    """
    AUDIT-058: Genuine bottleneck descriptions must NOT be flagged as self-praise.
    """
    from echelon.pdf.extract_evidence import is_self_praise

    genuine_bottlenecks = [
        "Bandwidth is fundamentally limited by the resonance Q-factor.",
        "Crosstalk constrains channel density below 50 channels per mm squared.",
        "Propagation loss remains a key barrier to integration.",
        "The system fails to maintain coherence at temperatures above 4K.",
        "Silicon waveguide loss is not yet reduced below 1 dB/cm.",
        "However, the efficiency remains limited by material absorption.",
        "Fabrication constraints prevent nanoscale features below 10 nm.",
        "The method is difficult to scale beyond laboratory conditions.",
    ]

    for text in genuine_bottlenecks:
        assert not is_self_praise(text), (
            f"[AUDIT-058] Genuine bottleneck falsely flagged as self-praise: {text!r}"
        )


def test_audit_058_filter_self_praise_from_evidence():
    """
    AUDIT-058: filter_self_praise_from_evidence correctly partitions spans.
    """
    from echelon.pdf.extract_evidence import filter_self_praise_from_evidence

    candidate_spans = [
        "Bandwidth is limited by the Q-factor resonance tradeoff.",        # genuine
        "Our method outperforms SOTA by 5% on all benchmarks.",            # self-praise
        "Crosstalk remains below -20 dB only within a 50 nm window.",     # genuine
        "The system completely eliminates all noise sources.",              # self-praise
        "Integration density is constrained by waveguide spacing.",        # genuine
    ]

    kept, discarded = filter_self_praise_from_evidence(candidate_spans)

    assert len(kept) == 3, f"[AUDIT-058] Expected 3 kept spans, got {len(kept)}"
    assert len(discarded) == 2, f"[AUDIT-058] Expected 2 discarded spans, got {len(discarded)}"

    # Verify the right spans are kept/discarded
    assert any("Q-factor" in s for s in kept)
    assert any("SOTA" in s for s in discarded)
    assert any("eliminates" in s for s in discarded)


# ============================================================================
# AUDIT-085: TOP2000_REFINE_PROMPT + build_topic_aware_prompt
# ============================================================================

def test_audit_085_prompt_template_has_placeholders():
    """
    AUDIT-085: TOP2000_REFINE_PROMPT must contain {primary_topic_name} and
    {neighbor_topic_names_top5} placeholders.
    """
    from echelon.seeds.score_keystone import TOP2000_REFINE_PROMPT

    assert "{primary_topic_name}" in TOP2000_REFINE_PROMPT, (
        "[AUDIT-085] TOP2000_REFINE_PROMPT missing {primary_topic_name}"
    )
    assert "{neighbor_topic_names_top5}" in TOP2000_REFINE_PROMPT, (
        "[AUDIT-085] TOP2000_REFINE_PROMPT missing {neighbor_topic_names_top5}"
    )
    assert "{title}" in TOP2000_REFINE_PROMPT, \
        "[AUDIT-085] TOP2000_REFINE_PROMPT missing {title}"
    assert "{abstract_full}" in TOP2000_REFINE_PROMPT, \
        "[AUDIT-085] TOP2000_REFINE_PROMPT missing {abstract_full}"


def test_audit_085_build_topic_aware_prompt_injects_context():
    """
    AUDIT-085: build_topic_aware_prompt must inject primary_topic_name and
    the top-5 KNN neighbour topic names into the prompt.
    """
    from echelon.seeds.score_keystone import build_topic_aware_prompt

    paper = {
        "title": "Nonlinear metasurface for ultrafast pulse shaping",
        "abstract": "We demonstrate a nonlinear metasurface that achieves ultrafast pulse control.",
        "primary_topic_name": "Nonlinear Photonics",
    }
    knn_topics = [
        "Ultrafast Optics",
        "Silicon Photonics",
        "Quantum Optics",
        "Electromagnetic Metamaterials",
        "Laser Physics",
    ]

    prompt = build_topic_aware_prompt(paper, knn_topics)

    assert isinstance(prompt, str), "[AUDIT-085] build_topic_aware_prompt must return str"

    # Primary topic name must appear
    assert "Nonlinear Photonics" in prompt, (
        "[AUDIT-085] primary_topic_name not injected into prompt"
    )

    # All 5 neighbour topics must appear
    for topic in knn_topics:
        assert topic in prompt, (
            f"[AUDIT-085] KNN topic '{topic}' not injected into prompt"
        )

    # Title and abstract must appear
    assert "Nonlinear metasurface" in prompt, "[AUDIT-085] title missing from prompt"
    assert "We demonstrate" in prompt, "[AUDIT-085] abstract missing from prompt"

    # No unfilled template placeholders (the JSON reply block uses {{ }} and is fine)
    # Check that none of the original {key} placeholders remain unfilled
    unfilled = re.findall(r"\{(?!\s*\n)([a-z_]+)\}", prompt)
    assert not unfilled, (
        f"[AUDIT-085] Prompt has unfilled template placeholders: {unfilled}"
    )


def test_audit_085_build_topic_aware_prompt_top5_truncation():
    """
    AUDIT-085: build_topic_aware_prompt must use at most 5 KNN topics even if
    more are provided.
    """
    from echelon.seeds.score_keystone import build_topic_aware_prompt

    paper = {
        "title": "Silicon photonic chip",
        "abstract": "A silicon photonic chip with low propagation loss.",
        "primary_topic_name": "Silicon Photonics",
    }
    knn_topics = [f"Topic_{i}" for i in range(10)]  # 10 topics provided

    prompt = build_topic_aware_prompt(paper, knn_topics)

    # Only Topic_0 through Topic_4 should appear, not Topic_5+
    for i in range(5):
        assert f"Topic_{i}" in prompt, f"[AUDIT-085] Topic_{i} should be in prompt"
    for i in range(5, 10):
        assert f"Topic_{i}" not in prompt, (
            f"[AUDIT-085] Topic_{i} should NOT be in prompt (only top-5 allowed)"
        )


def test_audit_085_build_topic_aware_prompt_empty_knn():
    """
    AUDIT-085: build_topic_aware_prompt handles empty knn_topics gracefully.
    """
    from echelon.seeds.score_keystone import build_topic_aware_prompt

    paper = {
        "title": "Quantum dot laser",
        "abstract": "A quantum dot laser with improved efficiency.",
        "primary_topic_name": "Quantum Optics",
    }

    prompt = build_topic_aware_prompt(paper, knn_topics=[])
    assert isinstance(prompt, str)
    unfilled = re.findall(r"\{(?!\s*\n)([a-z_]+)\}", prompt)
    assert not unfilled, f"[AUDIT-085] Unfilled placeholders with empty knn_topics: {unfilled}"
    assert "no neighbours" in prompt.lower() or "available" in prompt.lower(), (
        "[AUDIT-085] Should indicate no neighbours when knn_topics is empty"
    )


def test_audit_085_prompt_fallback_topic_name():
    """
    AUDIT-085: build_topic_aware_prompt falls back to alternative topic name fields
    if primary_topic_name is absent.
    """
    from echelon.seeds.score_keystone import build_topic_aware_prompt

    # Paper without primary_topic_name but with primary_topic_display_name
    paper = {
        "title": "Photonic crystal waveguide",
        "abstract": "Photonic crystal waveguide with bandgap engineering.",
        "primary_topic_display_name": "Photonic Crystals",
    }
    knn_topics = ["Photonics", "Nanophotonics"]

    prompt = build_topic_aware_prompt(paper, knn_topics)
    assert "Photonic Crystals" in prompt, (
        "[AUDIT-085] Should fall back to primary_topic_display_name"
    )


def test_audit_085_parse_refine_prompt_response():
    """
    AUDIT-085: parse_refine_prompt_response must extract the four scoring fields.
    """
    from echelon.seeds.score_keystone import parse_refine_prompt_response

    good_response = json.dumps({
        "cross_domain_significance": 0.75,
        "novelty_within_topic": 0.60,
        "breakthrough_language_score": 0.45,
        "mechanism_novelty_score": 0.80,
        "reasoning": "Bridges Nonlinear Photonics and Ultrafast Optics via new mechanism.",
    })

    result = parse_refine_prompt_response(good_response)
    assert result is not None, "[AUDIT-085] parse_refine_prompt_response failed on valid input"
    assert result["cross_domain_significance"] == 0.75
    assert result["novelty_within_topic"] == 0.60
    assert result["breakthrough_language_score"] == 0.45
    assert result["mechanism_novelty_score"] == 0.80

    # Invalid response
    assert parse_refine_prompt_response("not json at all") is None
    assert parse_refine_prompt_response(json.dumps({"partial": 0.5})) is None


# ============================================================================
# Integration: AUDIT-044 × AUDIT-057 (same sentence_split module)
# ============================================================================

def test_audit_044_057_shared_sentence_splitting():
    """
    AUDIT-044 & AUDIT-057 share the same sentence splitting infrastructure.
    embed_claim_with_context (prior_art_search) and extend_evidence_with_context
    (sentence_split) must produce consistent results on the same text.
    """
    from echelon.bottleneck.prior_art_search import embed_claim_with_context
    from echelon.pdf.sentence_split import extend_evidence_with_context

    abstract = (
        "We study photonic crosstalk in silicon waveguides. "
        "Crosstalk limits integration density below 50 channels per mm squared. "
        "Several mitigation strategies have been proposed but remain insufficient."
    )
    claim = "Crosstalk limits integration density below 50 channels per mm squared."

    result_044 = embed_claim_with_context(claim, abstract, window=1)
    result_057 = extend_evidence_with_context(claim, abstract, window=1)

    # Both must produce multi-sentence strings containing context
    for result, tag in [(result_044, "AUDIT-044"), (result_057, "AUDIT-057")]:
        assert "photonic" in result.lower() or "silicon" in result.lower(), (
            f"[{tag}] Missing preceding context sentence"
        )
        assert "mitigation" in result or "insufficient" in result, (
            f"[{tag}] Missing following context sentence"
        )
        assert "Crosstalk limits" in result or "crosstalk" in result.lower()


# ============================================================================
# Entry point (direct run)
# ============================================================================

if __name__ == "__main__":
    test_audit_018_schema_fields()
    test_audit_018_claim_with_circumvention()
    test_audit_018_claimed_resolution_negative_signal()
    test_audit_021_prompt_has_6_properties()
    test_audit_021_pydantic_empty_warning()
    test_audit_021_no_warning_when_fields_populated()
    test_audit_021_parse_claim_response_defaults_to_empty_lists()
    test_audit_044_embed_claim_with_context_includes_neighbors()
    test_audit_044_embed_claim_fallback_when_abstract_empty()
    test_audit_044_embed_claim_window_0_returns_claim()
    test_audit_044_bge_m3_fallback_function_exists()
    test_audit_044_bge_m3_with_mock_model()
    test_audit_057_extend_evidence_with_context()
    test_audit_057_extend_evidence_fallback()
    test_audit_057_resolve_pronouns_stub()
    test_audit_057_extend_and_resolve()
    test_audit_057_window_produces_minimum_3_sentences()
    test_audit_058_self_praise_patterns_exist()
    test_audit_058_outperforms_sota_is_self_praise()
    test_audit_058_self_praise_detection()
    test_audit_058_genuine_bottleneck_not_self_praise()
    test_audit_058_filter_self_praise_from_evidence()
    test_audit_085_prompt_template_has_placeholders()
    test_audit_085_build_topic_aware_prompt_injects_context()
    test_audit_085_build_topic_aware_prompt_top5_truncation()
    test_audit_085_build_topic_aware_prompt_empty_knn()
    test_audit_085_prompt_fallback_topic_name()
    test_audit_085_parse_refine_prompt_response()
    test_audit_044_057_shared_sentence_splitting()
    print("\n✅ 所有 6 条 P1 Schema/Prompt 测试通过!")
