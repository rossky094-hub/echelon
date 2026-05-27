#!/usr/bin/env python3
"""
test_v12_5_extensions.py - Unit tests for Sci-Bot V12.5 新增 4 项独有能力

Tests:
    - contradiction_detector: 跨论文矛盾检测
    - citation_chain: 多跳引用追踪
    - principle_to_papers: 元规律→论文反查
    - incremental_analysis: 新论文增量分析

Run:
    pytest tests/test_v12_5_extensions.py -v
    pytest tests/test_v12_5_extensions.py -v -k "test_contradiction"
"""

import json
import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

PARSED_DIR = Path('/home/user/workspace/echelon_mvp0a/scibot/parsed')
SCIBOT_DIR = Path('/home/user/workspace/echelon_mvp0a/scibot')
META_PRINCIPLES_FILE = SCIBOT_DIR / 'meta_principles.json'

# 已知存在的 paper_id（来自 V12 数据库）
KNOWN_PAPER_ID = "01KR7T0VQ0VWCDTX5SN9B4BEVH"   # 超构光学
KNOWN_PAPER_ID_2 = "01KR7T0X48ESGCZC6KF1M5RW90"  # tokamak RL

SAMPLE_CHUNKS = [
    {
        "text": "Our method achieves 95% accuracy on the standard benchmark.",
        "paper_id": "01KR7T0X3W40FACCMYC42QXFHV",
        "paper_title": "Learning Locomotion for Quadruped Robots",
        "section_type": "limitations",
        "chunk_idx": 0,
        "is_priority_section": True,
        "distance": 0.3,
    },
    {
        "text": "The proposed approach only achieves 77% accuracy on the same benchmark due to domain gap issues.",
        "paper_id": "01KR7T0WDG5XAJAHWRQC7WQGVG",
        "paper_title": "Continuous control actions learning",
        "section_type": "limitations",
        "chunk_idx": 1,
        "is_priority_section": True,
        "distance": 0.4,
    },
    {
        "text": "We demonstrate that sparse rewards are the main bottleneck, not exploration strategy.",
        "paper_id": "01KR7T0X4QBX13RAK16ACGEXJZ",
        "paper_title": "Decentralized multi-agent RL",
        "section_type": "discussion",
        "chunk_idx": 0,
        "is_priority_section": True,
        "distance": 0.5,
    },
    {
        "text": "Contrary to previous claims, exploration strategy—not sparse rewards—is the main limitation.",
        "paper_id": "01KR7T0XDEPQN648T38DAFC32M",
        "paper_title": "Intelligent career planning via RL",
        "section_type": "limitations",
        "chunk_idx": 0,
        "is_priority_section": True,
        "distance": 0.55,
    },
]

SAMPLE_LLM_CONTRADICTION_RESPONSE = {
    "contradictions": [
        {
            "type": "numeric",
            "severity": "high",
            "claim_a": {
                "paper_id": "01KR7T0X3W40FACCMYC42QXFHV",
                "text": "achieves 95% accuracy on the standard benchmark"
            },
            "claim_b": {
                "paper_id": "01KR7T0WDG5XAJAHWRQC7WQGVG",
                "text": "only achieves 77% accuracy on the same benchmark"
            },
            "explanation": "两篇论文在同一基准上报告了截然不同的精度数值（95% vs 77%），差异达18个百分点，这直接影响对该任务难度和方法有效性的判断。"
        },
        {
            "type": "mechanism",
            "severity": "mid",
            "claim_a": {
                "paper_id": "01KR7T0X4QBX13RAK16ACGEXJZ",
                "text": "sparse rewards are the main bottleneck, not exploration strategy"
            },
            "claim_b": {
                "paper_id": "01KR7T0XDEPQN648T38DAFC32M",
                "text": "exploration strategy—not sparse rewards—is the main limitation"
            },
            "explanation": "两篇论文对强化学习主要瓶颈的归因完全相反，一个认为稀疏奖励是根源，另一个认为探索策略是根源，这是典型的机制矛盾。"
        }
    ],
    "summary": "在该主题下检测到2条矛盾：1条数值矛盾（精度数据差异显著）和1条机制矛盾（对强化学习主要瓶颈的归因相反）。",
    "total_chunks_analyzed": 4
}


# ─────────────────────────────────────────────────────────────────────────────
# Test: contradiction_detector
# ─────────────────────────────────────────────────────────────────────────────

class TestContradictionDetector:
    """跨论文矛盾检测测试。"""

    def test_import(self):
        """模块可以正常导入。"""
        from scibot.contradiction_detector import detect_contradictions, detect_contradictions_for_theme
        assert callable(detect_contradictions)
        assert callable(detect_contradictions_for_theme)

    def test_theme_id_validation(self):
        """无效 theme_id 应该抛出 ValueError。"""
        from scibot.contradiction_detector import detect_contradictions_for_theme
        with pytest.raises(ValueError, match="Unknown theme_id"):
            detect_contradictions_for_theme("T99")

    def test_valid_theme_ids(self):
        """所有 T01-T17 都应该是合法 theme_id。"""
        from scibot.contradiction_detector import THEME_QUERIES
        assert "T01" in THEME_QUERIES
        assert "T17" in THEME_QUERIES
        assert len(THEME_QUERIES) == 17

    def test_theme_titles_coverage(self):
        """所有 THEME_TITLES 覆盖 T01-T17。"""
        from scibot.contradiction_detector import THEME_TITLES
        for i in range(1, 18):
            assert f"T{i:02d}" in THEME_TITLES

    @patch('scibot.contradiction_detector.run_llm_extract')
    def test_detect_contradictions_with_mock_llm(self, mock_llm):
        """模拟 LLM 返回，验证矛盾解析逻辑。"""
        mock_llm.return_value = SAMPLE_LLM_CONTRADICTION_RESPONSE

        from scibot.contradiction_detector import _sync_detect
        result = _sync_detect(SAMPLE_CHUNKS)

        assert isinstance(result, list)
        assert len(result) == 2

        # 第一条矛盾是数值类型
        assert result[0]['type'] == 'numeric'
        assert result[0]['severity'] == 'high'
        assert 'paper_id' in result[0]['claim_a']
        assert 'paper_id' in result[0]['claim_b']
        assert 'explanation' in result[0]

        # 第二条矛盾是机制类型
        assert result[1]['type'] == 'mechanism'
        assert result[1]['severity'] == 'mid'

    @patch('scibot.contradiction_detector.run_llm_extract')
    def test_detect_contradictions_llm_failure(self, mock_llm):
        """LLM 失败时返回空列表。"""
        mock_llm.return_value = None

        from scibot.contradiction_detector import _sync_detect
        result = _sync_detect(SAMPLE_CHUNKS)
        assert result == []

    def test_empty_chunks_returns_empty(self):
        """空 chunks 输入应该直接返回空列表（不调用 LLM）。"""
        from scibot.contradiction_detector import _sync_detect
        result = _sync_detect([])
        assert result == []

    @patch('scibot.contradiction_detector.run_llm_extract')
    def test_contradiction_schema_fields(self, mock_llm):
        """矛盾输出需包含必要字段。"""
        mock_llm.return_value = SAMPLE_LLM_CONTRADICTION_RESPONSE
        from scibot.contradiction_detector import _sync_detect
        result = _sync_detect(SAMPLE_CHUNKS)
        for contradiction in result:
            assert 'type' in contradiction
            assert contradiction['type'] in ('numeric', 'mechanism', 'boundary')
            assert 'severity' in contradiction
            assert contradiction['severity'] in ('low', 'mid', 'high')
            assert 'claim_a' in contradiction
            assert 'claim_b' in contradiction
            assert 'paper_id' in contradiction['claim_a']
            assert 'text' in contradiction['claim_a']
            assert 'explanation' in contradiction

    @patch('scibot.contradiction_detector.query_for_theme')
    @patch('scibot.contradiction_detector.run_llm_extract')
    def test_detect_for_theme_returns_full_result(self, mock_llm, mock_query):
        """detect_contradictions_for_theme 返回完整结构。"""
        mock_query.return_value = SAMPLE_CHUNKS
        mock_llm.return_value = SAMPLE_LLM_CONTRADICTION_RESPONSE

        from scibot.contradiction_detector import detect_contradictions_for_theme
        result = detect_contradictions_for_theme("T12", top_k=8)

        assert result['theme_id'] == 'T12'
        assert 'theme_title' in result
        assert 'contradictions' in result
        assert 'summary' in result
        assert 'chunks_analyzed' in result
        assert 'papers_involved' in result


# ─────────────────────────────────────────────────────────────────────────────
# Test: citation_chain
# ─────────────────────────────────────────────────────────────────────────────

class TestCitationChain:
    """多跳引用追踪测试。"""

    def test_import(self):
        """模块可以正常导入。"""
        from scibot.citation_chain import trace_citation_chain, build_citation_tree
        assert callable(trace_citation_chain)
        assert callable(build_citation_tree)

    def test_load_all_papers(self):
        """应该能加载所有已解析论文。"""
        from scibot.citation_chain import _load_all_papers
        papers = _load_all_papers()
        assert len(papers) >= 20  # V12 有 25 篇
        assert KNOWN_PAPER_ID in papers
        paper = papers[KNOWN_PAPER_ID]
        assert 'title' in paper
        assert 'paper_id' in paper

    def test_unknown_paper_id_returns_error(self):
        """不在语料库中的 paper_id 应返回 error 字段。"""
        from scibot.citation_chain import trace_citation_chain
        result = trace_citation_chain("NONEXISTENT_PAPER_ID_XYZ")
        assert 'error' in result

    def test_known_paper_returns_tree(self):
        """已知 paper_id 应该返回引用树结构。"""
        from scibot.citation_chain import trace_citation_chain
        result = trace_citation_chain(KNOWN_PAPER_ID, depth=1)

        assert 'error' not in result
        assert result['root_paper_id'] == KNOWN_PAPER_ID
        assert result['in_corpus'] is True
        assert 'citation_tree' in result
        assert 'common_ancestors' in result
        assert isinstance(result['common_ancestors'], list)

    def test_citation_tree_structure(self):
        """引用树节点结构验证。"""
        from scibot.citation_chain import trace_citation_chain
        result = trace_citation_chain(KNOWN_PAPER_ID, depth=1)
        tree = result['citation_tree']

        assert 'paper_id' in tree
        assert 'title' in tree
        assert 'in_corpus' in tree
        assert 'depth' in tree
        assert 'references' in tree
        assert isinstance(tree['references'], list)
        assert tree['depth'] == 0  # 根节点深度为 0

    def test_extract_references_from_text(self):
        """参考文献提取函数。"""
        from scibot.citation_chain import _extract_references_from_text, _extract_ref_titles

        fake_paper = {
            "raw_text": """...methods...
References
[1] Smith, J. et al. Deep Learning for Robot Manipulation. NeurIPS, 2023.
[2] Wang, L. and Chen, Q. Tactile Sensors for Dexterous Hands. ICRA, 2022.
[3] Liu, X. et al. "Reinforcement Learning with Sparse Rewards". ICLR, 2024.
""",
            "sections": {}
        }

        entries = _extract_references_from_text(fake_paper)
        assert len(entries) >= 1

        titles = _extract_ref_titles(entries)
        assert isinstance(titles, list)

    def test_find_in_corpus_match(self):
        """语料库中应该能找到已知论文（近似标题匹配）。"""
        from scibot.citation_chain import _find_in_corpus, _load_all_papers

        all_papers = _load_all_papers()
        # 查找超构光学论文（标题关键词）
        match = _find_in_corpus(
            "genetic algorithm meta-atom design metasurface optics",
            all_papers
        )
        # 可能找到或找不到（取决于 Jaccard 阈值），但不应报错
        if match:
            assert 'paper_id' in match
            assert 'match_score' in match

    def test_find_in_corpus_no_match(self):
        """完全不相关的标题应该返回 None。"""
        from scibot.citation_chain import _find_in_corpus, _load_all_papers
        all_papers = _load_all_papers()
        result = _find_in_corpus("zzz unrelated gibberish xyz", all_papers)
        assert result is None

    def test_common_ancestors_empty_when_no_refs(self):
        """无引用时共同祖先应为空列表。"""
        from scibot.citation_chain import find_common_ancestors

        tree = {
            "paper_id": "P1",
            "title": "Paper 1",
            "in_corpus": True,
            "depth": 0,
            "references": [],
            "ref_titles_extracted": [],
        }
        ancestors = find_common_ancestors(tree)
        assert ancestors == []


# ─────────────────────────────────────────────────────────────────────────────
# Test: principle_to_papers
# ─────────────────────────────────────────────────────────────────────────────

class TestPrincipleToPapers:
    """元规律→论文反查测试。"""

    def test_import(self):
        """模块可以正常导入。"""
        from scibot.principle_to_papers import query_principle_in_papers_sync
        assert callable(query_principle_in_papers_sync)

    def test_invalid_principle_id(self):
        """无效元规律 ID 应该返回 error 字段。"""
        from scibot.principle_to_papers import query_principle_in_papers_sync
        result = query_principle_in_papers_sync("MP99")
        assert 'error' in result

    def test_valid_principle_ids(self):
        """MP_ID_MAP 应该覆盖 MP1-MP4。"""
        from scibot.principle_to_papers import MP_ID_MAP
        assert "MP1" in MP_ID_MAP
        assert "MP2" in MP_ID_MAP
        assert "MP3" in MP_ID_MAP
        assert "MP4" in MP_ID_MAP
        assert len(MP_ID_MAP) == 4

    def test_load_meta_principles(self):
        """元规律 JSON 应该能正确加载。"""
        from scibot.principle_to_papers import _load_meta_principles
        mps = _load_meta_principles()
        assert len(mps) == 4
        # 每个元规律应有关键字段
        for mp in mps:
            assert 'principle' in mp
            assert 'covered_themes' in mp
            assert 'explanation' in mp
            assert len(mp['covered_themes']) > 0

    def test_meta_principles_cover_all_themes(self):
        """4 个元规律应该覆盖所有 17 个主题。"""
        from scibot.principle_to_papers import _load_meta_principles
        mps = _load_meta_principles()
        all_covered = set()
        for mp in mps:
            all_covered.update(mp.get('covered_themes', []))
        # 应覆盖所有 17 主题
        assert len(all_covered) >= 17

    @patch('scibot.principle_to_papers.query_for_theme')
    @patch('scibot.principle_to_papers._run_llm_extract')
    def test_query_principle_returns_structure(self, mock_llm, mock_query):
        """query_principle_in_papers_sync 返回完整结构。"""
        mock_query.return_value = SAMPLE_CHUNKS
        mock_llm.return_value = {
            "papers_ranked": [
                {
                    "paper_id": "01KR7T0X3W40FACCMYC42QXFHV",
                    "paper_title": "Learning Locomotion",
                    "severity_score": 0.87,
                    "evidence": "The curse of dimensionality severely limits...",
                    "how_principle_manifests": "高维动作空间导致非凸地形搜索失效..."
                }
            ],
            "principle_analysis": "维度灾难在多个主题中普遍体现..."
        }

        from scibot.principle_to_papers import query_principle_in_papers_sync
        result = query_principle_in_papers_sync("MP1", top_n=3)

        assert result['principle_id'] == 'MP1'
        assert 'principle' in result
        assert 'covered_themes' in result
        assert 'papers_ranked_by_severity' in result
        assert 'principle_analysis' in result

    @patch('scibot.principle_to_papers.query_for_theme')
    @patch('scibot.principle_to_papers._run_llm_extract')
    def test_papers_sorted_by_severity(self, mock_llm, mock_query):
        """论文应该按严重度降序排列。"""
        mock_query.return_value = SAMPLE_CHUNKS
        mock_llm.return_value = {
            "papers_ranked": [
                {"paper_id": "P1", "paper_title": "Paper 1", "severity_score": 0.6,
                 "evidence": "...", "how_principle_manifests": "..."},
                {"paper_id": "P2", "paper_title": "Paper 2", "severity_score": 0.9,
                 "evidence": "...", "how_principle_manifests": "..."},
                {"paper_id": "P3", "paper_title": "Paper 3", "severity_score": 0.75,
                 "evidence": "...", "how_principle_manifests": "..."},
            ],
            "principle_analysis": "分析文本"
        }

        from scibot.principle_to_papers import query_principle_in_papers_sync
        result = query_principle_in_papers_sync("MP2", top_n=5)

        papers = result['papers_ranked_by_severity']
        assert len(papers) == 3
        # 应该按严重度降序
        severities = [p['severity'] for p in papers]
        assert severities == sorted(severities, reverse=True)

    @patch('scibot.principle_to_papers.query_for_theme')
    @patch('scibot.principle_to_papers._run_llm_extract')
    def test_llm_failure_fallback(self, mock_llm, mock_query):
        """LLM 失败时应该 fallback 到 first_principles_results 数据。"""
        mock_query.return_value = SAMPLE_CHUNKS
        mock_llm.return_value = None

        from scibot.principle_to_papers import query_principle_in_papers_sync
        result = query_principle_in_papers_sync("MP1", top_n=3)

        # 不应该报错，而是使用 fallback
        assert 'error' not in result
        assert 'principle_id' in result
        assert result['principle_id'] == 'MP1'


# ─────────────────────────────────────────────────────────────────────────────
# Test: incremental_analysis
# ─────────────────────────────────────────────────────────────────────────────

class TestIncrementalAnalysis:
    """新论文增量分析测试。"""

    def test_import(self):
        """模块可以正常导入。"""
        from scibot.incremental_analysis import analyze_new_paper_sync, analyze_new_paper
        assert callable(analyze_new_paper_sync)
        assert callable(analyze_new_paper)

    def test_nonexistent_pdf_returns_error(self):
        """不存在的 PDF 路径应该返回 error。"""
        from scibot.incremental_analysis import analyze_new_paper_sync
        result = analyze_new_paper_sync("/tmp/nonexistent_paper_xyz.pdf")
        assert 'error' in result

    def test_semantic_match_themes(self):
        """语义主题匹配函数测试。"""
        from scibot.incremental_analysis import _semantic_match_themes

        # 包含强 RL 关键词的文本
        rl_text = "reinforcement learning sparse reward exploration policy gradient convergence"
        themes = _semantic_match_themes(rl_text)

        assert len(themes) == 3  # 返回 top-3
        assert all('theme_id' in t for t in themes)
        assert all('score' in t for t in themes)
        assert all('matched_keywords' in t for t in themes)

        # 第一个应该是最相关的主题（分数最高）
        scores = [t['score'] for t in themes]
        assert scores == sorted(scores, reverse=True)

    def test_semantic_match_metasurface(self):
        """超构光学相关文本应该匹配到 T01 或 T02。"""
        from scibot.incremental_analysis import _semantic_match_themes

        meta_text = "metasurface differentiable optimization inverse design meta-optics broadband"
        themes = _semantic_match_themes(meta_text)

        top_theme_ids = [t['theme_id'] for t in themes]
        assert any(tid in ('T01', 'T02') for tid in top_theme_ids)

    def test_semantic_match_principles(self):
        """元规律匹配函数测试。"""
        from scibot.incremental_analysis import _semantic_match_principles

        # 高维优化相关
        hd_text = "high dimensional optimization non-convex convergence curse dimensionality"
        mps = _semantic_match_principles(hd_text)

        assert len(mps) == 4  # 返回所有 4 个 MP
        assert all('mp_id' in m for m in mps)
        assert all('score' in m for m in mps)

        # MP1（维度灾难）应该排名靠前
        scores = [m['score'] for m in mps]
        assert scores == sorted(scores, reverse=True)

    def test_themes_coverage(self):
        """THEMES 列表应该覆盖 T01-T17。"""
        from scibot.incremental_analysis import THEMES

        theme_ids = {t['theme_id'] for t in THEMES}
        assert len(theme_ids) == 17
        for i in range(1, 18):
            assert f"T{i:02d}" in theme_ids

    def test_meta_principles_coverage(self):
        """META_PRINCIPLES 列表应该覆盖 MP1-MP4。"""
        from scibot.incremental_analysis import META_PRINCIPLES

        mp_ids = {m['id'] for m in META_PRINCIPLES}
        assert len(mp_ids) == 4
        assert {'MP1', 'MP2', 'MP3', 'MP4'} == mp_ids

    @patch('scibot.incremental_analysis._download_arxiv_pdf')
    @patch('scibot.incremental_analysis._parse_pdf_simple')
    @patch('scibot.incremental_analysis._run_llm_extract')
    def test_analyze_arxiv_url_flow(self, mock_llm, mock_parse, mock_download):
        """arXiv URL 分析流程（全 mock）。"""
        mock_download.return_value = "/tmp/test_paper.pdf"
        mock_parse.return_value = {
            "raw_text": "Deep learning for robot manipulation...",
            "sections": {
                "abstract": "We propose a novel approach for robot manipulation...",
                "limitations": "Our method fails in high-dimensional spaces...",
                "methods": "We use transformer architecture...",
            },
            "page_count": 10,
        }
        mock_llm.return_value = {
            "paper_summary": "本文提出了一种新型机器人操作方法...",
            "top_theme_id": "T04",
            "top_theme_title": "具身智能中的物理一致性拓扑建模",
            "theme_alignment_score": 0.78,
            "theme_alignment_reason": "论文涉及机器人操作的物理约束建模...",
            "top_mp_id": "MP2",
            "top_mp_name": "流形假设失真与表达能力上限瓶颈",
            "mp_severity": 0.72,
            "mp_evidence": "Our method fails in high-dimensional spaces...",
            "what_phenomenon": "论文卡点...",
            "how_mechanism": "失败机制...",
            "why_first_principle": "流形假设...",
            "where_cross_domain": "跨域对偶...",
            "predict_falsifiable": "预测...",
            "knowledge_relation": "reinforces",
            "knowledge_relation_detail": "强化了 T04 主题的现有结论..."
        }

        from scibot.incremental_analysis import analyze_new_paper_sync
        result = analyze_new_paper_sync("https://arxiv.org/abs/2401.12345")

        assert 'error' not in result or 'five_questions' in result
        assert result.get('top_theme', {}).get('theme_id') == 'T04'
        assert result.get('top_mp', {}).get('mp_id') == 'MP2'
        assert result.get('knowledge_relation') == 'reinforces'
        fq = result.get('five_questions', {})
        assert 'what_phenomenon' in fq
        assert 'how_mechanism' in fq
        assert 'why_first_principle' in fq
        assert 'where_cross_domain' in fq
        assert 'predict_falsifiable' in fq

    def test_parse_pdf_from_existing_file(self):
        """从真实存在的 PDF 文件解析。"""
        from scibot.incremental_analysis import _parse_pdf_simple

        # 使用 V12 已有的 PDF 文件
        pdf_path = f"/home/user/workspace/echelon_mvp0a/scibot/pdfs/{KNOWN_PAPER_ID}.pdf"
        if not os.path.exists(pdf_path):
            pytest.skip("已知 PDF 文件不存在")

        parsed = _parse_pdf_simple(pdf_path)
        assert 'raw_text' in parsed
        assert 'sections' in parsed
        assert len(parsed['raw_text']) > 100

    def test_arxiv_id_extraction(self):
        """arXiv URL 中的 ID 提取逻辑。"""
        import re
        test_urls = [
            ("https://arxiv.org/abs/2401.12345", "2401.12345"),
            ("https://arxiv.org/pdf/2401.12345v2", "2401.12345v2"),
            ("https://arxiv.org/abs/2312.00001", "2312.00001"),
        ]
        for url, expected_id in test_urls:
            match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
            assert match is not None, f"Failed to extract ID from {url}"
            assert match.group(1) == expected_id

    def test_knowledge_relation_async(self):
        """async 接口应该能被调用（即使是 sync 包装）。"""
        from scibot.incremental_analysis import analyze_new_paper

        # 只验证 analyze_new_paper 是 async 函数
        import asyncio
        assert asyncio.iscoroutinefunction(analyze_new_paper)


# ─────────────────────────────────────────────────────────────────────────────
# Integration: cross-module data consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestDataConsistency:
    """跨模块数据一致性验证。"""

    def test_meta_principles_file_exists(self):
        """meta_principles.json 必须存在。"""
        mp_file = SCIBOT_DIR / 'meta_principles.json'
        assert mp_file.exists(), "meta_principles.json 缺失"

    def test_first_principles_results_file_exists(self):
        """first_principles_results.json 必须存在。"""
        fp_file = SCIBOT_DIR / 'first_principles_results.json'
        assert fp_file.exists(), "first_principles_results.json 缺失"

    def test_parsed_papers_count(self):
        """解析论文数量应该 >= 20。"""
        parsed_files = [f for f in PARSED_DIR.glob('*.json') if not f.name.startswith('_')]
        assert len(parsed_files) >= 20, f"Only {len(parsed_files)} parsed papers found"

    def test_theme_ids_consistent_across_modules(self):
        """各模块中的 theme_id 定义应一致。"""
        from scibot.contradiction_detector import THEME_QUERIES as cd_themes
        from scibot.principle_to_papers import THEME_QUERIES as p2p_themes
        from scibot.incremental_analysis import THEMES as ia_themes

        # contradiction_detector 和 principle_to_papers 的主题 ID 应该一致
        assert set(cd_themes.keys()) == set(p2p_themes.keys())

        # incremental_analysis 的主题 ID 也应该一致
        ia_theme_ids = {t['theme_id'] for t in ia_themes}
        assert ia_theme_ids == set(cd_themes.keys())

    def test_meta_principles_data_integrity(self):
        """meta_principles.json 数据完整性验证。"""
        mp_file = SCIBOT_DIR / 'meta_principles.json'
        with open(mp_file) as f:
            data = json.load(f)

        mps = data.get('meta_principles', [])
        assert len(mps) == 4, f"Expected 4 meta principles, got {len(mps)}"

        all_theme_ids = set()
        for mp in mps:
            assert 'principle' in mp
            assert 'covered_themes' in mp
            assert 'explanation' in mp
            assert isinstance(mp['covered_themes'], list)
            assert len(mp['covered_themes']) > 0
            all_theme_ids.update(mp['covered_themes'])

        # 确认所有 17 主题都被覆盖
        assert len(all_theme_ids) >= 17

    def test_first_principles_results_structure(self):
        """first_principles_results.json 结构验证。"""
        fp_file = SCIBOT_DIR / 'first_principles_results.json'
        with open(fp_file) as f:
            results = json.load(f)

        assert isinstance(results, list)
        assert len(results) >= 17, f"Expected 17 results, got {len(results)}"

        required_fields = ['theme_id', 'theme_title', 'what_phenomenon', 
                          'how_mechanism', 'why_first_principle']
        for result in results:
            for field in required_fields:
                assert field in result, f"Missing field {field} in {result.get('theme_id')}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
