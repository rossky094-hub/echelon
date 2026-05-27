"""
V11.3 Hotfix Unit Tests — 6 items (R1, R2, R3, R4, R5, R7)

Each test corresponds exactly to the hotfix specification:
  R1: test_keystone_score_no_collapse          — σ ≥ 0.10 on 1000 synthetic papers
  R2: test_abstract_split_evidence_count_gt_zero — evidence ≥ 3 per bottleneck
  R3: test_cross_topic_label_uses_slash         — 5:5 mixed cluster gets "/" label
  R4: test_bridge_keywords_creates_edge         — bridge keyword → forced edge
  R5: test_cs_paper_passes_depth_gate           — VLM paper (87.3% COCO) passes
  R7: test_cocite_min_weight_2                  — co_citation only built at weight ≥ 2

Run: pytest tests/test_v11_3_hotfix.py -v
"""
from __future__ import annotations

import math
import os
import random
import sys

import pytest

# Ensure echelon package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# R1: test_keystone_score_no_collapse
# 1000 synthetic papers, σ ≥ 0.10 (healthy threshold)
# ============================================================================

def test_keystone_score_no_collapse():
    """
    R1 (V11.3): KeystoneScore 对数空间几何平均 + 0.05 平滑.

    用 1000 个假论文验证:
    - 标准差 σ ≥ 0.10 (健康区分度, 原 V11.2 σ < 0.05)
    - Top-10 与 Bottom-50 的 score 差 ≥ 0.2
    - 无 NaN / 无复数 / 无越界值
    """
    from echelon.seeds.score_keystone import compute_keystone_score, safe_clip

    rng = random.Random(42)
    scores = []

    for _ in range(1000):
        # Diverse inputs: some low, some high, some negative (edge cases)
        c_rec = rng.uniform(-0.3, 1.0)
        c_venue = rng.uniform(0.0, 1.0)
        c_td = rng.uniform(0.0, 1.0)
        c_rb = rng.uniform(0.0, 1.0)
        c_rev = rng.uniform(0.0, 1.0)
        c_bib = rng.uniform(0.0, 1.0)
        c_cocite = rng.uniform(0.0, 1.0) if rng.random() > 0.3 else None
        c_bc = rng.uniform(0.0, 1.0)
        c_cd = rng.uniform(0.0, 1.0) if rng.random() > 0.3 else None
        c_sem = rng.uniform(0.0, 1.0)
        c_bl = rng.uniform(0.0, 1.0)
        c_mn = rng.uniform(0.0, 1.0)
        sc = rng.uniform(0.0, 1.0)

        s = compute_keystone_score(
            c_recency=c_rec,
            c_venue=c_venue,
            c_team_disrupt=c_td,
            c_recent_burst=c_rb,
            c_review_filter=c_rev,
            c_bib_breadth=c_bib,
            c_cocite_breadth=c_cocite,
            c_bridging_centrality=c_bc,
            c_cd_subdomain=c_cd,
            c_semantic_outlier=c_sem,
            c_breakthrough_lang=c_bl,
            c_mechanism_novelty=c_mn,
            supporting_count=sc,
        )

        # No complex / NaN / out-of-range
        assert not isinstance(s, complex), f"KeystoneScore is complex: {s}"
        assert isinstance(s, float), f"KeystoneScore is not float: {type(s)}"
        assert not math.isnan(s), f"KeystoneScore is NaN"
        assert 0.0 <= s <= 1.0, f"KeystoneScore out of [0,1]: {s}"

        scores.append(s)

    # Compute standard deviation
    mean_s = sum(scores) / len(scores)
    variance = sum((x - mean_s) ** 2 for x in scores) / len(scores)
    sigma = math.sqrt(variance)

    assert sigma >= 0.10, (
        f"R1 FAILED: KeystoneScore σ = {sigma:.4f} < 0.10 (评分坍缩未解决). "
        f"mean={mean_s:.4f}, min={min(scores):.4f}, max={max(scores):.4f}"
    )

    # Top-10 vs Bottom-50 gap
    sorted_scores = sorted(scores)
    top10_mean = sum(sorted_scores[-10:]) / 10
    bottom50_mean = sum(sorted_scores[:50]) / 50
    gap = top10_mean - bottom50_mean
    assert gap >= 0.2, (
        f"R1 FAILED: Top10 vs Bottom50 gap = {gap:.4f} < 0.20. "
        f"top10_mean={top10_mean:.4f}, bottom50_mean={bottom50_mean:.4f}"
    )

    print(
        f"✅ R1 通过: σ={sigma:.4f} ≥ 0.10, "
        f"Top10-Bottom50 gap={gap:.4f} ≥ 0.20, "
        f"mean={mean_s:.4f}"
    )


# ============================================================================
# R2: test_abstract_split_evidence_count_gt_zero
# 每个卡点至少 3 条 evidence atom
# ============================================================================

def test_abstract_split_evidence_count_gt_zero():
    """
    R2 (V11.3): abstract 分句 + EvidenceAtom 绑定.

    验证:
    - 每篇论文 abstract 能切出 ≥ 1 个 EvidenceAtom
    - cluster_papers (5 篇) 能提供 ≥ 3 条 evidence atoms
    - 关键词匹配 ("however", "limitation", "challenge") 的句子优先排列
    """
    from echelon.pdf.sentence_split import (
        split_abstract_to_sentences,
        extract_abstract_evidence_atoms,
        bind_evidence_to_bottleneck_claim,
    )
    from echelon.pdf.extract_evidence import extract_evidence_from_abstract

    # --- Test 1: pysbd sentence splitting ---
    abstract_with_bottleneck = (
        "Metasurfaces offer unprecedented control over electromagnetic waves. "
        "However, the bandwidth of existing designs remains fundamentally limited "
        "by the resonance quality factor. "
        "This challenge prevents broadband operation in practical applications. "
        "We propose a multi-resonance approach to address this limitation. "
        "Experimental results show 3x bandwidth improvement at 1550 nm."
    )

    sentences = split_abstract_to_sentences(abstract_with_bottleneck)
    assert len(sentences) >= 3, (
        f"R2 FAILED: pysbd 只切出 {len(sentences)} 句, 应 >= 3"
    )

    # --- Test 2: EvidenceAtom creation from abstract ---
    atoms = extract_evidence_from_abstract(
        paper_id="test_paper_001",
        abstract=abstract_with_bottleneck,
    )
    assert len(atoms) >= 1, (
        f"R2 FAILED: extract_evidence_from_abstract 返回 0 个 atoms"
    )

    # Verify page_no = 1 (not 0, which violates ge=1 schema)
    for atom in atoms:
        assert atom.page_no >= 1, (
            f"R2 FAILED: EvidenceAtom.page_no={atom.page_no} < 1 (违反 ge=1 约束)"
        )
        assert atom.section_type == "abstract", (
            f"R2 FAILED: section_type={atom.section_type!r} 应为 'abstract'"
        )
        assert len(atom.span_text) >= 10, (
            f"R2 FAILED: span_text 太短 ({len(atom.span_text)} < 10 chars)"
        )

    # --- Test 3: Keyword-matched sentences come first ---
    raw_atoms = extract_abstract_evidence_atoms(
        paper_id="test_paper_001",
        abstract=abstract_with_bottleneck,
    )
    # At least one of the first atoms should contain bottleneck keywords
    first_texts = " ".join(a["span_text"].lower() for a in raw_atoms[:3])
    has_bottleneck_kw = any(
        kw in first_texts
        for kw in ["however", "limitation", "limited", "challenge", "prevent"]
    )
    assert has_bottleneck_kw, (
        f"R2 FAILED: 优先排序失败 — 前3条 atoms 无关键词. "
        f"texts={first_texts[:200]!r}"
    )

    # --- Test 4: cluster bind_evidence (5 papers → ≥ 3 atoms) ---
    cluster_papers = []
    for i in range(5):
        cluster_papers.append({
            "paper_id": f"cluster_paper_{i:03d}",
            "abstract": (
                f"Paper {i}: This study explores metasurface limitations. "
                f"However, the bandwidth challenge remains unsolved. "
                f"We achieve {85 + i}% accuracy on ImageNet despite these constraints."
            ),
        })

    cluster_atoms = bind_evidence_to_bottleneck_claim(
        cluster_papers=cluster_papers,
        min_evidence=3,
    )
    assert len(cluster_atoms) >= 3, (
        f"R2 FAILED: cluster 只产生 {len(cluster_atoms)} 条 evidence, 应 >= 3"
    )

    print(
        f"✅ R2 通过: pysbd 切出 {len(sentences)} 句, "
        f"EvidenceAtom {len(atoms)} 个 (page_no>=1), "
        f"cluster evidence {len(cluster_atoms)} 条 ≥ 3"
    )


# ============================================================================
# R3: test_cross_topic_label_uses_slash
# 5:5 混合 cluster → label 含 "/"
# ============================================================================

def test_cross_topic_label_uses_slash():
    """
    R3 (V11.3): 跨 topic cluster label 用 "/" 连接.

    验证:
    - 5:5 混合 cluster (top_topic_ratio=0.5 < 0.6) → label 含 "/"
    - 纯 cluster (ratio=1.0 ≥ 0.6) → label 不含 "/", 只含 "中"
    - is_cross_topic_cluster() 函数正确判断
    """
    from echelon.bottleneck.label_generator import (
        compute_top_topic_ratio,
        build_topic_prefix,
        is_cross_topic_cluster,
    )

    # Build a 5:5 mixed cluster
    mixed_members = []
    for i in range(5):
        mixed_members.append({
            "paper_id": f"optics_paper_{i:03d}",
            "primary_topic_id": "T10245",
            "primary_topic_display_name": "Metasurface Design",
            "topic_name": "Metasurface Design",
        })
    for i in range(5):
        mixed_members.append({
            "paper_id": f"ml_paper_{i:03d}",
            "primary_topic_id": "T11714",
            "primary_topic_display_name": "Multimodal ML",
            "topic_name": "Multimodal ML",
        })

    # --- top_topic_ratio for 5:5 cluster ---
    ratio, sorted_topics = compute_top_topic_ratio(mixed_members)
    assert abs(ratio - 0.5) < 0.01, (
        f"R3 FAILED: top_topic_ratio={ratio:.3f} 应为 0.5 (5:5 混合)"
    )
    assert len(sorted_topics) == 2, (
        f"R3 FAILED: sorted_topics={sorted_topics} 应为 2 个"
    )

    # --- is_cross_topic_cluster() ---
    assert is_cross_topic_cluster(mixed_members, cross_topic_threshold=0.6), (
        f"R3 FAILED: 5:5 cluster 应判定为 cross-topic (ratio=0.5 < 0.6)"
    )

    # --- build_topic_prefix: should contain "/" ---
    prefix = build_topic_prefix(mixed_members)
    assert "/" in prefix, (
        f"R3 FAILED: cross-topic prefix 不含 '/': {prefix!r}"
    )
    assert "跨界" in prefix, (
        f"R3 FAILED: cross-topic prefix 不含 '跨界': {prefix!r}"
    )

    # --- Pure (9:1) cluster → no "/" ---
    pure_members = []
    for i in range(9):
        pure_members.append({
            "paper_id": f"optics_{i:03d}",
            "primary_topic_id": "T10245",
            "primary_topic_display_name": "Metasurface Design",
        })
    pure_members.append({
        "paper_id": "other_001",
        "primary_topic_id": "T11714",
        "primary_topic_display_name": "Multimodal ML",
    })

    pure_ratio, _ = compute_top_topic_ratio(pure_members)
    assert pure_ratio >= 0.6, (
        f"R3 FAILED: 9:1 cluster top_topic_ratio={pure_ratio:.3f} 应 ≥ 0.6"
    )

    assert not is_cross_topic_cluster(pure_members, cross_topic_threshold=0.6), (
        f"R3 FAILED: 9:1 cluster 不应判定为 cross-topic"
    )

    pure_prefix = build_topic_prefix(pure_members)
    assert "/" not in pure_prefix, (
        f"R3 FAILED: 单 topic cluster prefix 不应含 '/': {pure_prefix!r}"
    )
    assert "中" in pure_prefix, (
        f"R3 FAILED: 单 topic cluster prefix 应含 '中': {pure_prefix!r}"
    )

    print(
        f"✅ R3 通过: 5:5 混合 prefix={prefix!r} (含 '/'), "
        f"9:1 纯 prefix={pure_prefix!r} (无 '/')"
    )


# ============================================================================
# R4: test_bridge_keywords_creates_edge
# 含桥词论文 → 强制建 semantic_bridge 边
# ============================================================================

def test_bridge_keywords_creates_edge():
    """
    R4 (V11.3): 桥词列表 + semantic_bridge 强制建边.

    验证:
    - BRIDGE_KEYWORDS 包含 38 条词
    - contains_bridge_keyword() 正确匹配
    - build_bridge_keyword_edges() 对含桥词论文建立跨 topic 边
    - 不含桥词的论文不建强制边
    """
    from echelon.graph.bridge_keywords import (
        BRIDGE_KEYWORDS,
        contains_bridge_keyword,
        find_bridge_keywords,
        build_bridge_keyword_edges,
    )

    # --- 38 keywords present ---
    assert len(BRIDGE_KEYWORDS) == 38, (
        f"R4 FAILED: 桥词列表应有 38 条, 实际 {len(BRIDGE_KEYWORDS)} 条"
    )

    # --- Keyword matching ---
    bridge_abstract = (
        "We design a diffractive deep neural network that performs image recognition "
        "using optical diffraction. The system operates at 1550 nm wavelength."
    )
    assert contains_bridge_keyword(bridge_abstract), (
        f"R4 FAILED: 含 'diffractive deep neural network' 的 abstract 未被识别"
    )

    found = find_bridge_keywords(bridge_abstract)
    assert len(found) >= 1, f"R4 FAILED: find_bridge_keywords 返回 0 个匹配"
    assert "diffractive deep neural network" in found, (
        f"R4 FAILED: 'diffractive deep neural network' 未在 found={found} 中"
    )

    # --- No false positive for non-bridge abstract ---
    non_bridge = (
        "We propose a transformer-based vision model that achieves 87.3% on ImageNet. "
        "The model uses attention mechanisms for feature extraction."
    )
    assert not contains_bridge_keyword(non_bridge), (
        f"R4 FAILED: 非桥词 abstract 误报 bridge: abstract={non_bridge[:80]!r}"
    )

    # --- build_bridge_keyword_edges ---
    papers = [
        {
            "paper_id": "optics_bridge_001",
            "primary_topic_id": "T10245",  # Optics topic
            "abstract": (
                "We demonstrate optical computing using photonic neural network "
                "architectures. The all-optical neural network achieves 95% accuracy."
            ),
        },
        {
            "paper_id": "ml_paper_001",
            "primary_topic_id": "T11714",  # ML topic
            "abstract": (
                "A transformer model for visual question answering achieves SOTA on VQA."
            ),
        },
        {
            "paper_id": "ml_paper_002",
            "primary_topic_id": "T11714",  # ML topic
            "abstract": (
                "Large language models with vision encoders outperform baseline on COCO."
            ),
        },
        {
            "paper_id": "optics_pure_001",
            "primary_topic_id": "T10245",  # Optics topic (no bridge keyword)
            "abstract": (
                "We characterize metasurface resonances at terahertz frequencies. "
                "The transmission coefficient is -15 dB at 1 THz."
            ),
        },
    ]

    edges = build_bridge_keyword_edges(papers)

    # optics_bridge_001 has bridge keywords → should have edges to ML topic papers
    bridge_paper_edges = [
        e for e in edges
        if "optics_bridge_001" in (e[0], e[1])
    ]
    assert len(bridge_paper_edges) >= 1, (
        f"R4 FAILED: 桥词论文 'optics_bridge_001' 未建立任何跨 topic 边. "
        f"edges={edges}"
    )

    # All edges should be cross-topic (T10245 ↔ T11714)
    for e in edges:
        pid_a, pid_b = e[0], e[1]
        topic_a = next(p["primary_topic_id"] for p in papers if p["paper_id"] == pid_a)
        topic_b = next(p["primary_topic_id"] for p in papers if p["paper_id"] == pid_b)
        assert topic_a != topic_b, (
            f"R4 FAILED: 边 ({pid_a}, {pid_b}) 是同 topic 边 (topic_a={topic_a})"
        )

    # Edge weight should be 0.5
    for e in edges:
        assert abs(e[2] - 0.5) < 1e-9, (
            f"R4 FAILED: bridge 边权重={e[2]:.3f} 应为 0.5"
        )

    # optics_pure_001 (no bridge keyword) should not be the source of bridge edges
    pure_source_edges = [
        e for e in edges
        if e[0] == "optics_pure_001" or e[1] == "optics_pure_001"
    ]
    assert len(pure_source_edges) == 0, (
        f"R4 FAILED: 无桥词论文 'optics_pure_001' 错误地出现在强制边中: {pure_source_edges}"
    )

    print(
        f"✅ R4 通过: 38 条桥词, 桥词论文建 {len(bridge_paper_edges)} 条跨 topic 边, "
        f"weight=0.5, 纯光学论文无强制边"
    )


# ============================================================================
# R5: test_cs_paper_passes_depth_gate
# VLM 论文 (87.3% COCO) 通过物理深度门
# ============================================================================

def test_cs_paper_passes_depth_gate():
    """
    R5 (V11.3): 物理深度门 OR 化 — VLM/CS 论文应能通过.

    验证:
    - 纯 CS/VLM 论文 (含 SOTA% + COCO dataset) → passed=True (Path 2)
    - 纯物理论文 (含 nm/dB 数值) → passed=True (Path 1)
    - 对比实验论文 (含 outperform/baseline + 数字) → passed=True (Path 3)
    - 空 abstract → passed=False
    """
    from echelon.seeds.physical_depth import (
        check_physical_depth,
        has_physical_depth,
        PhysicalDepthResult,
    )

    # --- Path 2: VLM CS paper ---
    vlm_abstract = (
        "We present a vision-language model that achieves 87.3% accuracy on COCO. "
        "Our ablation study shows each component contributes: removing the cross-attention "
        "layer drops accuracy by 3.2%. On VQA benchmark we achieve 74.1%, and on "
        "ImageNet top-1 accuracy reaches 91.5%."
    )

    result_vlm = check_physical_depth(vlm_abstract)
    assert result_vlm.passed, (
        f"R5 FAILED: VLM 论文未通过深度门. "
        f"path1={result_vlm.path1_count}, path2={result_vlm.path2_count}, "
        f"path3={result_vlm.path3_count}"
    )
    assert result_vlm.path2_passed, (
        f"R5 FAILED: VLM 论文 Path2 (CS 量化) 未通过. path2_count={result_vlm.path2_count}"
    )

    # The spec's exact test: "achieves 87.3% on COCO" in abstract
    minimal_vlm = (
        "Our model achieves 87.3% on COCO, with 82.1% on VQA and "
        "ablation study confirming each module's importance."
    )
    assert has_physical_depth(minimal_vlm), (
        f"R5 FAILED: 含 '87.3% on COCO' 的论文未通过深度门"
    )

    # --- Path 1: Optics paper ---
    optics_abstract = (
        "We design a metasurface operating at 1550 nm wavelength. "
        "The insertion loss is 3.5 dB and bandwidth is 100 nm. "
        "Resonance frequency is 193 THz with Q-factor 1000."
    )
    result_optics = check_physical_depth(optics_abstract)
    assert result_optics.passed, (
        f"R5 FAILED: 光学论文未通过深度门. path1={result_optics.path1_count}"
    )
    assert result_optics.path1_passed, (
        f"R5 FAILED: 光学论文 Path1 (物理常量) 未通过"
    )

    # --- Path 3: Comparison paper ---
    comparison_abstract = (
        "We compare our method against 3 baselines. "
        "Our approach outperforms the state-of-the-art by 5.2% on Task A. "
        "Versus the baseline, we achieve 12.8 points gain with 94.3% accuracy."
    )
    result_cmp = check_physical_depth(comparison_abstract)
    assert result_cmp.passed, (
        f"R5 FAILED: 对比实验论文未通过深度门. path3={result_cmp.path3_count}"
    )

    # --- Empty abstract → failed ---
    assert not has_physical_depth(""), (
        "R5 FAILED: 空 abstract 不应通过深度门"
    )
    assert not has_physical_depth(None), (
        "R5 FAILED: None abstract 不应通过深度门"
    )

    # --- Pure description paper (no quantitative) → failed ---
    qualitative_abstract = (
        "We discuss the conceptual framework for understanding quantum phenomena. "
        "The theoretical approach relies on symmetry arguments and conservation laws. "
        "Future work will explore experimental validation."
    )
    result_qual = check_physical_depth(qualitative_abstract)
    # This should fail (no numeric values, no datasets, no comparisons with numbers)
    assert not result_qual.passed, (
        f"R5 WARNING: 定性论文意外通过了深度门 "
        f"(path1={result_qual.path1_count}, path2={result_qual.path2_count}, "
        f"path3={result_qual.path3_count}). 可接受的边界情况."
    )

    print(
        f"✅ R5 通过: VLM path2_count={result_vlm.path2_count}, "
        f"光学 path1_count={result_optics.path1_count}, "
        f"对比 path3_count={result_cmp.path3_count}"
    )


# ============================================================================
# R7: test_cocite_min_weight_2
# co_citation 只在共被引 >= 2 时建边
# ============================================================================

def test_cocite_min_weight_2():
    """
    R7 (V11.3): co_citation 阈值 >= 2.

    验证:
    - 两篇论文被同一外部文献引用 (weight=1) → 不建边
    - 两篇论文被 2 个外部文献引用 (weight=2) → 建边
    - 两篇论文被 3 个外部文献引用 (weight=3) → 建边
    - MIN_COCITE_WEIGHT 常量等于 2
    """
    from echelon.graph.cocite import (
        build_cocitation_edges,
        MIN_COCITE_WEIGHT,
        cocite_stats,
    )

    # --- Check constant ---
    assert MIN_COCITE_WEIGHT == 2, (
        f"R7 FAILED: MIN_COCITE_WEIGHT={MIN_COCITE_WEIGHT} 应为 2"
    )

    # --- Setup: 3 papers, external refs A/B/C ---
    # Paper 1 and Paper 2 both cite external_ref_A (co-citation weight=1)
    # Paper 1 and Paper 3 both cite external_ref_A and external_ref_B (weight=2)
    # Paper 2 and Paper 3 both cite external_ref_C only (weight=1)

    papers = [
        {
            "paper_id": "P1",
            "referenced_work_ids": ["ext_A", "ext_B", "ext_X"],
        },
        {
            "paper_id": "P2",
            "referenced_work_ids": ["ext_A", "ext_C", "ext_Y"],
        },
        {
            "paper_id": "P3",
            "referenced_work_ids": ["ext_A", "ext_B", "ext_C"],
        },
    ]

    # P1-P2 share ext_A → weight=1 (BELOW threshold)
    # P1-P3 share ext_A, ext_B → weight=2 (AT threshold, should build edge)
    # P2-P3 share ext_A, ext_C → weight=2 (AT threshold, should build edge)

    edges = build_cocitation_edges(papers, min_weight=2)

    edge_pairs = {(e[0], e[1]) for e in edges}
    edge_weights = {(e[0], e[1]): e[2] for e in edges}

    # P1-P3: weight=2 → should be present
    assert ("P1", "P3") in edge_pairs or ("P3", "P1") in edge_pairs, (
        f"R7 FAILED: P1-P3 (weight=2) 未建边. edges={edges}"
    )

    # P2-P3: weight=2 → should be present
    assert ("P2", "P3") in edge_pairs or ("P3", "P2") in edge_pairs, (
        f"R7 FAILED: P2-P3 (weight=2) 未建边. edges={edges}"
    )

    # P1-P2: weight=1 → should NOT be present
    assert ("P1", "P2") not in edge_pairs and ("P2", "P1") not in edge_pairs, (
        f"R7 FAILED: P1-P2 (weight=1) 被错误建边. edges={edges}"
    )

    # All returned edges must have weight >= 2
    for e in edges:
        assert e[2] >= 2, (
            f"R7 FAILED: edge {e[0]}-{e[1]} weight={e[2]} < 2"
        )

    # --- Extra: weight=1 explicitly excluded ---
    single_cocite_papers = [
        {"paper_id": "PA", "referenced_work_ids": ["ext_SINGLE"]},
        {"paper_id": "PB", "referenced_work_ids": ["ext_SINGLE"]},
    ]
    single_edges = build_cocitation_edges(single_cocite_papers, min_weight=2)
    assert len(single_edges) == 0, (
        f"R7 FAILED: weight=1 的对应该返回 0 条边, 实际 {len(single_edges)}"
    )

    # --- Stats ---
    stats = cocite_stats(edges)
    assert stats["min_weight"] >= 2, (
        f"R7 FAILED: stats min_weight={stats['min_weight']} < 2"
    )

    print(
        f"✅ R7 通过: {len(edges)} 条 co_citation 边 (min_weight=2), "
        f"P1-P2 weight=1 被过滤, "
        f"P1-P3/P2-P3 weight=2 保留"
    )


# ============================================================================
# Entry point for direct execution
# ============================================================================

if __name__ == "__main__":
    test_keystone_score_no_collapse()
    test_abstract_split_evidence_count_gt_zero()
    test_cross_topic_label_uses_slash()
    test_bridge_keywords_creates_edge()
    test_cs_paper_passes_depth_gate()
    test_cocite_min_weight_2()
    print("\n🎉 V11.3 全部 6 项 hotfix 测试通过!")
