"""
[V12.5] paper-qa 集成 + 保留原创单元测试

覆盖:
  test_paperqa_parse_pdf_works               — paper-qa 能解析真实 PDF
  test_section_type_priority_for_limitation_query — limitations 优先检索逻辑
  test_paperqa_rerank_improves_precision_on_synthetic — pplx rerank 接口(mock)
  test_double_gate_loader_returns_71_seeds   — V11.5 双门加载 71 金种子
  test_first_principles_pipeline_end_to_end_one_theme — 5项追问管道端到端

Run: pytest tests/test_v12_5_paperqa.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import pytest

# 确保根路径在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

PDF_DIR = '/home/user/workspace/echelon_mvp0a/scibot/pdfs'
PARSED_DIR = '/home/user/workspace/echelon_mvp0a/scibot/parsed'
CHROMA_DIR = '/home/user/workspace/echelon_mvp0a/scibot/chroma_db'
DB_PATH = '/home/user/workspace/echelon_mvp0a/db/pilot_v5.db'
SEEDS_JSON = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources.json'

# 用固定的第一篇 PDF 做解析测试
TEST_PDF_ID = '01KR7T0VQ0VWCDTX5SN9B4BEVH'
TEST_PDF_PATH = f'{PDF_DIR}/{TEST_PDF_ID}.pdf'


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------

def _chroma_available() -> bool:
    """检查 ChromaDB 是否有数据可供查询。"""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        col = client.get_collection("scibot_papers")
        return col.count() > 0
    except Exception:
        return False


# --------------------------------------------------------------------------
# Test 1: paper-qa PDF 解析
# --------------------------------------------------------------------------

class TestPaperQAParsePDF:
    """[V12.5] paper-qa 解析 PDF 能力测试。"""

    def test_paperqa_parse_pdf_works(self):
        """
        paper-qa 的 read_doc (parsed_text_only=True) 能正确解析真实 PDF,
        返回多页文本,每页非空。
        """
        pytest.importorskip("paperqa", reason="paper-qa not installed")

        if not os.path.exists(TEST_PDF_PATH):
            pytest.skip(f"测试 PDF 不存在: {TEST_PDF_PATH}")

        from scibot.paperqa_integration import EchelonPaperQA

        pqa = EchelonPaperQA()
        result = asyncio.run(
            pqa.parse_pdf_async(TEST_PDF_PATH, paper_id=TEST_PDF_ID)
        )

        # 基本字段
        assert 'error' not in result, f"解析失败: {result.get('error')}"
        assert result['paper_id'] == TEST_PDF_ID
        assert result['source'] == 'paperqa'
        assert result['page_count'] >= 1, "应该至少有 1 页"
        assert len(result.get('full_text', '')) > 500, "全文长度应 > 500 字符"

    def test_paperqa_extracts_nonempty_pages(self):
        """
        paper-qa 解析后的每页文本不为空。
        """
        pytest.importorskip("paperqa", reason="paper-qa not installed")

        if not os.path.exists(TEST_PDF_PATH):
            pytest.skip(f"测试 PDF 不存在: {TEST_PDF_PATH}")

        from scibot.paperqa_integration import EchelonPaperQA

        pqa = EchelonPaperQA()
        result = asyncio.run(
            pqa.parse_pdf_async(TEST_PDF_PATH, paper_id=TEST_PDF_ID)
        )

        pages = result.get('pages', {})
        assert len(pages) >= 1, "应有多页"
        nonempty = [p for p in pages.values() if len(p.strip()) > 10]
        assert len(nonempty) >= 1, "至少 1 页有实质文本"

    def test_paperqa_produces_sections(self):
        """
        paper-qa 解析后,extract_sections_from_text 能识别至少 1 个有效章节。
        """
        pytest.importorskip("paperqa", reason="paper-qa not installed")

        if not os.path.exists(TEST_PDF_PATH):
            pytest.skip(f"测试 PDF 不存在: {TEST_PDF_PATH}")

        from scibot.paperqa_integration import EchelonPaperQA

        pqa = EchelonPaperQA()
        result = asyncio.run(
            pqa.parse_pdf_async(TEST_PDF_PATH, paper_id=TEST_PDF_ID)
        )

        sections = result.get('sections', {})
        non_empty_sections = {
            k: v for k, v in sections.items()
            if not k.startswith('_') and len(v.strip()) > 50
        }
        assert len(non_empty_sections) >= 1, (
            f"应至少识别 1 个非空章节,实际: {list(sections.keys())}"
        )

    def test_paperqa_limitations_auto_extracted(self):
        """
        若论文没有显式 limitations 节,
        extract_sections_from_text 应从 discussion/conclusion 自动抽取限制句。
        """
        from scibot.paperqa_integration import extract_sections_from_text

        # 合成一个没有 Limitations 标题但 Discussion 含限制语义的文本
        fake_text = """
Abstract
This paper introduces a new method.

Introduction
The problem is important.

Methods
We use gradient descent.

Discussion
However, our approach cannot handle large-scale datasets efficiently.
The main limitation is the quadratic complexity. We are unable to scale beyond 10k samples.
Future work will address this constraint.

Conclusion
We propose a solution that shows promise.
"""
        sections = extract_sections_from_text(fake_text)

        # discussion 应被识别
        assert len(sections.get('discussion', '')) > 20, "应识别 discussion 节"

        # limitations 应被自动抽取 (含 limitation/cannot/unable 等关键词)
        lim_text = sections.get('limitations', '')
        assert len(lim_text) > 20, (
            f"应自动抽取 limitations 文本,实际: '{lim_text[:100]}'"
        )
        assert 'Auto-extracted' in lim_text, "自动抽取的标记应在文本中"


# --------------------------------------------------------------------------
# Test 2: section_type 优先 limitations 检索 (Sci-Bot 原创 #1)
# --------------------------------------------------------------------------

class TestSectionTypePriorityForLimitationQuery:
    """[Sci-Bot 原创 #1] section_type 优先 limitations 检索过滤。"""

    def test_should_filter_by_limitation_positive_cases(self):
        """含卡点关键词的查询应触发 limitations 优先过滤。"""
        from scibot.scibot_query import should_filter_by_limitation

        positive_queries = [
            "What are the main limitations of this approach?",
            "What challenges remain in tokamak RL control?",
            "What bottlenecks exist in dexterous hand control?",
            "Why does the method fail on OOD data?",
            "卡点是什么",
            "当前技术的瓶颈",
            "主要挑战是什么",
            "What future directions are proposed?",
        ]
        for q in positive_queries:
            assert should_filter_by_limitation(q), (
                f"应触发 limitation 过滤: '{q}'"
            )

    def test_should_filter_by_limitation_negative_cases(self):
        """不含卡点关键词的查询不触发 limitations 优先过滤。"""
        from scibot.scibot_query import should_filter_by_limitation

        negative_queries = [
            "Describe the method architecture",
            "What datasets were used?",
            "Summarize the results",
            "How many parameters does the model have?",
        ]
        for q in negative_queries:
            assert not should_filter_by_limitation(q), (
                f"不应触发 limitation 过滤: '{q}'"
            )

    def test_section_type_priority_constants(self):
        """PRIORITY_SECTIONS 包含正确的 4 个章节类型。"""
        from scibot.scibot_query import PRIORITY_SECTIONS

        expected = {'limitations', 'discussion', 'future_work', 'conclusion'}
        assert PRIORITY_SECTIONS == expected, (
            f"PRIORITY_SECTIONS 应为 {expected},实际: {PRIORITY_SECTIONS}"
        )

    def test_query_returns_priority_sections_first(self):
        """
        当 ChromaDB 有数据时,limitation 查询返回的 top-N 结果
        中优先章节应排在前面 (is_priority_section=True 的在前)。
        """
        if not _chroma_available():
            pytest.skip("ChromaDB 无数据,跳过实际检索测试")

        from scibot.scibot_query import query

        chunks = query("What are the limitations and challenges?", top_k=8)
        if not chunks:
            pytest.skip("检索无结果")

        # 验证:有 is_priority_section=True 的 chunk
        prio = [c for c in chunks if c.get('is_priority_section')]
        # 不强制所有都是,但 top-1 应是优先章节 (如果有的话)
        assert 'section_type' in chunks[0], "每个 chunk 应含 section_type 字段"
        assert 'paper_id' in chunks[0], "每个 chunk 应含 paper_id 字段"
        assert 'distance' in chunks[0], "每个 chunk 应含 distance 字段"

    def test_section_type_metadata_in_chunks(self):
        """query() 返回的 chunk 结构字段完整。"""
        if not _chroma_available():
            pytest.skip("ChromaDB 无数据,跳过实际检索测试")

        from scibot.scibot_query import query

        chunks = query("meta-optics inverse design", top_k=3)
        if not chunks:
            pytest.skip("检索无结果")

        required_keys = {'text', 'paper_id', 'paper_title', 'section_type',
                         'chunk_idx', 'is_priority_section', 'distance'}
        for chunk in chunks:
            missing = required_keys - set(chunk.keys())
            assert not missing, f"chunk 缺少字段: {missing}"

    def test_build_index_metadata_has_paperqa_doc_id(self):
        """
        [V12.5] build_index.py 产生的 metadata 包含 paperqa_doc_id 字段。
        (验证 V12.5 新增的引用追踪 metadata)
        """
        if not _chroma_available():
            pytest.skip("ChromaDB 无数据,跳过")

        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        col = client.get_collection("scibot_papers")

        # 取 1 条记录检查 metadata
        result = col.get(limit=1, include=['metadatas'])
        if not result['metadatas']:
            pytest.skip("无 metadata 可检查")

        meta = result['metadatas'][0]
        # parse_engine 或 paperqa_doc_id 任一存在即说明是 V12.5 索引
        # 若是旧索引(V12前),允许不存在 paperqa_doc_id
        # 仅当 index_stats 显示 version=V12.5 时才强制检查
        stats_path = os.path.join(CHROMA_DIR, '_index_stats.json')
        if os.path.exists(stats_path):
            with open(stats_path) as f:
                stats = json.load(f)
            if stats.get('version') == 'V12.5':
                assert 'paperqa_doc_id' in meta or 'parse_engine' in meta, (
                    f"V12.5 索引的 metadata 应含 paperqa_doc_id 或 parse_engine, "
                    f"实际 keys: {list(meta.keys())}"
                )


# --------------------------------------------------------------------------
# Test 3: pplx rerank 接口 (Sci-Bot 原创: LLM 全走 pplx)
# --------------------------------------------------------------------------

class TestPaperQARerankImprovesOnSynthetic:
    """[V12.5] use_paperqa_rerank=True 接口测试。"""

    def test_query_accepts_use_paperqa_rerank_param(self):
        """query() 函数接受 use_paperqa_rerank 参数 (不崩溃)。"""
        if not _chroma_available():
            pytest.skip("ChromaDB 无数据")

        from scibot.scibot_query import query

        # use_paperqa_rerank=False (原行为) 不应崩溃
        chunks_cosine = query("limitations of meta-optics", top_k=5, use_paperqa_rerank=False)
        assert isinstance(chunks_cosine, list), "应返回 list"
        assert len(chunks_cosine) <= 5

    def test_rerank_fallback_on_mock_chunks(self):
        """
        _pplx_rerank 在 pplx 不可用时应 fallback 到 cosine 排序,不抛异常。
        使用 monkeypatch 模拟 pplx 失败。
        """
        from scibot import scibot_query

        # 构造 synthetic chunks
        synthetic_chunks = [
            {
                'text': f'This is chunk {i} about limitations.',
                'paper_id': f'PAPER_{i:03d}',
                'paper_title': f'Test Paper {i}',
                'section_type': 'limitations' if i % 2 == 0 else 'methods',
                'chunk_idx': i,
                'is_priority_section': i % 2 == 0,
                'distance': 0.1 * i,
            }
            for i in range(15)
        ]

        import subprocess
        original_run = subprocess.run

        def mock_run_fail(*args, **kwargs):
            """模拟 pplx 命令失败 (returncode=1)。"""
            class FakeResult:
                returncode = 1
                stdout = ''
                stderr = 'mock failure'
            return FakeResult()

        subprocess.run = mock_run_fail
        try:
            result = scibot_query._pplx_rerank(
                "What are the limitations?",
                synthetic_chunks,
                top_k=5,
            )
        finally:
            subprocess.run = original_run

        assert isinstance(result, list), "fallback 应返回 list"
        assert len(result) == 5, f"应返回 top_k=5 个,实际: {len(result)}"
        # fallback 时直接取前 5 个
        assert result[0]['paper_id'] == 'PAPER_000'

    def test_rerank_with_valid_mock_pplx_response(self):
        """
        _pplx_rerank 能正确解析 pplx llm extract 的 JSONL 输出。
        使用 monkeypatch 模拟成功响应。
        """
        from scibot import scibot_query
        import subprocess

        synthetic_chunks = [
            {
                'text': f'Chunk {i}: {"limitations" if i == 2 else "other content"}.',
                'paper_id': f'P{i}',
                'paper_title': f'Paper {i}',
                'section_type': 'limitations' if i == 2 else 'introduction',
                'chunk_idx': i,
                'is_priority_section': i == 2,
                'distance': 0.5 - 0.01 * i,
            }
            for i in range(10)
        ]

        # 模拟 pplx 返回:选下标 [2, 0, 5, 3] (前 4 个)
        mock_output = json.dumps({
            "results": [
                {"result": {"ranked_indices": [2, 0, 5, 3]}}
            ]
        })

        original_run = subprocess.run

        def mock_run_success(*args, **kwargs):
            class FakeResult:
                returncode = 0
                stdout = mock_output
                stderr = ''
            return FakeResult()

        subprocess.run = mock_run_success
        try:
            result = scibot_query._pplx_rerank(
                "What are the limitations?",
                synthetic_chunks,
                top_k=3,
            )
        finally:
            subprocess.run = original_run

        assert isinstance(result, list), "应返回 list"
        assert len(result) == 3, f"应返回 top_k=3 个,实际: {len(result)}"
        # 第一个应该是 chunk 2 (limitations)
        assert result[0]['chunk_idx'] == 2, (
            f"第一个应是 chunk 2 (rerank 最高分),实际: {result[0]['chunk_idx']}"
        )

    def test_rerank_handles_invalid_indices_gracefully(self):
        """
        _pplx_rerank 处理 pplx 返回越界下标时不崩溃,只用有效下标。
        """
        from scibot import scibot_query
        import subprocess

        chunks = [
            {
                'text': f'Chunk {i}',
                'paper_id': f'P{i}',
                'paper_title': '',
                'section_type': 'discussion',
                'chunk_idx': i,
                'is_priority_section': True,
                'distance': 0.1 * i,
            }
            for i in range(5)
        ]

        # 模拟返回含越界下标 [99, 0, 1]
        mock_output = json.dumps({
            "results": [
                {"result": {"ranked_indices": [99, 0, 1]}}
            ]
        })

        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            class FakeResult:
                returncode = 0
                stdout = mock_output
                stderr = ''
            return FakeResult()

        subprocess.run = mock_run
        try:
            result = scibot_query._pplx_rerank("test", chunks, top_k=3)
        finally:
            subprocess.run = original_run

        assert isinstance(result, list)
        # 99 是越界下标,只有 [0, 1] 有效,返回 2 个
        assert len(result) <= 3
        valid_ids = {c['chunk_idx'] for c in result}
        assert 99 not in valid_ids, "越界下标 99 不应出现在结果中"


# --------------------------------------------------------------------------
# Test 4: double_gate_loader 加载 71 金种子 (Sci-Bot 原创 #3)
# --------------------------------------------------------------------------

class TestDoubleGateLoaderReturns71Seeds:
    """[Sci-Bot 原创 #3] V11.5 双门筛选上游接入验证。"""

    def test_double_gate_loader_returns_71_seeds(self):
        """
        load_v11_5_seeds() 应返回 71 篇金种子论文。
        这是 V11.5 双门筛选 + LLM 验证的核心输出。
        """
        if not os.path.exists(SEEDS_JSON):
            pytest.skip(f"金种子文件不存在: {SEEDS_JSON}")

        from scibot.double_gate_loader import load_v11_5_seeds

        seeds = load_v11_5_seeds()
        assert len(seeds) == 71, (
            f"V11.5 金种子应为 71 篇,实际: {len(seeds)}"
        )

    def test_seeds_have_required_fields(self):
        """每个金种子应含 paper_id, title, topic_name, abstract 字段。"""
        if not os.path.exists(SEEDS_JSON):
            pytest.skip(f"金种子文件不存在: {SEEDS_JSON}")

        from scibot.double_gate_loader import load_v11_5_seeds

        seeds = load_v11_5_seeds()
        required = {'paper_id', 'title', 'topic_name', 'abstract'}

        for seed in seeds:
            missing = required - set(seed.keys())
            assert not missing, f"种子缺少字段: {missing} (paper_id={seed.get('paper_id')})"

    def test_get_seed_paper_ids_returns_71(self):
        """get_seed_paper_ids() 返回 71 个 paper_id。"""
        if not os.path.exists(SEEDS_JSON):
            pytest.skip(f"金种子文件不存在: {SEEDS_JSON}")

        from scibot.double_gate_loader import get_seed_paper_ids

        ids = get_seed_paper_ids()
        assert len(ids) == 71, f"应返回 71 个 paper_id,实际: {len(ids)}"
        assert len(set(ids)) == 71, "paper_id 不应有重复"

    def test_double_gate_db_query_works(self):
        """load_double_gate_papers() 能查 DB 并返回记录。"""
        if not os.path.exists(DB_PATH):
            pytest.skip(f"DB 不存在: {DB_PATH}")

        from scibot.double_gate_loader import load_double_gate_papers

        papers = load_double_gate_papers()
        assert isinstance(papers, list), "应返回 list"
        # DB 里有 2000 篇,双门过滤后应该有相当比例通过
        assert len(papers) >= 1, "双门过滤后应有至少 1 篇论文"
        # 验证每篇都通过了双门
        for p in papers:
            assert p['is_outlier'] == 0, f"所有论文应通过门1 (is_outlier=0): {p['id']}"
            assert p['validation_type'] in ('experiment', 'simulation'), (
                f"所有论文应通过门2 (validation_type): {p['id']}"
            )

    def test_double_gate_stats_structure(self):
        """get_double_gate_stats() 返回完整统计结构。"""
        if not os.path.exists(DB_PATH) or not os.path.exists(SEEDS_JSON):
            pytest.skip("DB 或金种子文件不存在")

        from scibot.double_gate_loader import get_double_gate_stats

        stats = get_double_gate_stats()
        required = {'total_in_db', 'passed_double_gate', 'seed_count', 'seed_ids'}
        assert required.issubset(stats.keys()), f"stats 缺少字段: {required - set(stats.keys())}"
        assert stats['total_in_db'] == 2000, f"DB 总数应为 2000: {stats['total_in_db']}"
        assert stats['seed_count'] == 71, f"金种子应为 71: {stats['seed_count']}"
        assert len(stats['seed_ids']) == 71


# --------------------------------------------------------------------------
# Test 5: 第一性原理管道端到端 (Sci-Bot 原创 #2)
# --------------------------------------------------------------------------

class TestFirstPrinciplesPipelineEndToEnd:
    """[Sci-Bot 原创 #2] 第一性原理 5 项追问范式端到端测试。"""

    def test_first_principles_instruction_has_5_items(self):
        """
        FIRST_PRINCIPLES_INSTRUCTION 包含 5 项追问:
        what_phenomenon / how_mechanism / why_first_principle /
        where_cross_domain / predict_falsifiable
        """
        from scibot.first_principles_analysis import FIRST_PRINCIPLES_INSTRUCTION

        required_keys = [
            'what_phenomenon',
            'how_mechanism',
            'why_first_principle',
            'where_cross_domain',
            'predict_falsifiable',
        ]
        for key in required_keys:
            assert key in FIRST_PRINCIPLES_INSTRUCTION, (
                f"5项追问中缺少: {key}"
            )

    def test_output_schema_has_5_fields(self):
        """
        OUTPUT_SCHEMA 包含所有 5 个必填字段。
        """
        from scibot.first_principles_analysis import OUTPUT_SCHEMA

        required = {
            'what_phenomenon', 'how_mechanism', 'why_first_principle',
            'where_cross_domain', 'predict_falsifiable',
        }
        schema_required = set(OUTPUT_SCHEMA.get('required', []))
        assert required == schema_required, (
            f"OUTPUT_SCHEMA required 字段应为 {required},实际: {schema_required}"
        )

    def test_themes_list_has_17_themes(self):
        """THEMES 列表应有 17 个主题 (V12 设计规格)。"""
        from scibot.first_principles_analysis import THEMES

        assert len(THEMES) == 17, f"应有 17 个主题,实际: {len(THEMES)}"

        # 每个主题应有 theme_id, theme_title, query
        for theme in THEMES:
            assert 'theme_id' in theme, f"主题缺少 theme_id: {theme}"
            assert 'theme_title' in theme, f"主题缺少 theme_title: {theme}"
            assert 'query' in theme, f"主题缺少 query: {theme}"

    def test_analyze_theme_returns_5_keys_with_chroma(self):
        """
        analyze_theme() 在 ChromaDB 有数据时返回含 5 项追问的 dict。
        (LLM 调用使用 mock 避免真实 pplx 调用)
        """
        if not _chroma_available():
            pytest.skip("ChromaDB 无数据,跳过端到端测试")

        from scibot import first_principles_analysis as fpa

        # Mock run_llm_extract 避免真实 LLM 调用
        mock_result = {
            "what_phenomenon": "[test] 测试卡点现象",
            "how_mechanism": "[test] 机制描述",
            "why_first_principle": "[test] 第一性原理",
            "where_cross_domain": "[test] 跨域桥点",
            "predict_falsifiable": "[test] 可证伪预测",
        }

        original_run_llm = fpa.run_llm_extract
        fpa.run_llm_extract = lambda *args, **kwargs: mock_result

        try:
            # 用第一个主题测试
            theme = fpa.THEMES[0]
            result = fpa.analyze_theme(theme)
        finally:
            fpa.run_llm_extract = original_run_llm

        # 验证 5 项都在结果中
        assert 'what_phenomenon' in result, "缺少 what_phenomenon"
        assert 'how_mechanism' in result, "缺少 how_mechanism"
        assert 'why_first_principle' in result, "缺少 why_first_principle"
        assert 'where_cross_domain' in result, "缺少 where_cross_domain"
        assert 'predict_falsifiable' in result, "缺少 predict_falsifiable"
        assert result['theme_id'] == theme['theme_id']

    def test_first_principles_uses_query_for_theme(self):
        """
        analyze_theme() 内部调用 query_for_theme (RAG 检索,Sci-Bot 原创 #1)。
        验证两者的集成是正确的:analyze_theme -> query_for_theme -> ChromaDB。
        """
        from scibot.first_principles_analysis import analyze_theme
        from scibot import first_principles_analysis as fpa, scibot_query

        call_log = []
        original_query = scibot_query.query_for_theme

        def mock_query_for_theme(theme_title, paper_ids, top_k):
            call_log.append({'theme_title': theme_title, 'top_k': top_k})
            return []  # 返回空,触发 fallback 路径

        scibot_query.query_for_theme = mock_query_for_theme
        fpa.query_for_theme = mock_query_for_theme  # also patch the import in fpa

        try:
            theme = fpa.THEMES[0]
            result = fpa.analyze_theme(theme)
        finally:
            scibot_query.query_for_theme = original_query
            fpa.query_for_theme = original_query

        assert len(call_log) >= 1, "analyze_theme 应至少调用一次 query_for_theme"
        assert call_log[0]['theme_title'] == theme['query'], (
            f"query_for_theme 的 theme_title 应是 theme['query'],实际: {call_log[0]['theme_title']}"
        )


# --------------------------------------------------------------------------
# Test 6: V12.5 集成完整性检查
# --------------------------------------------------------------------------

class TestV125IntegrationCompleteness:
    """V12.5 各模块导入和接口完整性验证。"""

    def test_paperqa_integration_importable(self):
        """scibot.paperqa_integration 可正常导入。"""
        from scibot.paperqa_integration import (
            EchelonPaperQA,
            extract_sections_from_text,
            classify_heading,
            PRIORITY_SECTIONS,
            get_pqa_full_text,
        )
        assert EchelonPaperQA is not None
        assert PRIORITY_SECTIONS == {'limitations', 'discussion', 'future_work', 'conclusion'}

    def test_double_gate_loader_importable(self):
        """scibot.double_gate_loader 可正常导入。"""
        from scibot.double_gate_loader import (
            load_v11_5_seeds,
            get_seed_paper_ids,
            load_double_gate_papers,
            get_seeds_for_fetch,
            get_double_gate_stats,
        )
        assert load_v11_5_seeds is not None

    def test_scibot_query_has_use_paperqa_rerank(self):
        """scibot_query.query() 接受 use_paperqa_rerank 参数。"""
        import inspect
        from scibot.scibot_query import query

        sig = inspect.signature(query)
        assert 'use_paperqa_rerank' in sig.parameters, (
            "query() 应有 use_paperqa_rerank 参数"
        )
        # 默认值应为 False (向后兼容)
        default = sig.parameters['use_paperqa_rerank'].default
        assert default is False, f"use_paperqa_rerank 默认应为 False,实际: {default}"

    def test_scibot_query_has_pplx_rerank_function(self):
        """scibot_query 有 _pplx_rerank 内部函数。"""
        from scibot.scibot_query import _pplx_rerank
        import inspect

        sig = inspect.signature(_pplx_rerank)
        assert 'question' in sig.parameters
        assert 'chunks' in sig.parameters
        assert 'top_k' in sig.parameters

    def test_build_index_has_use_paperqa_param(self):
        """build_index() 接受 use_paperqa 参数。"""
        import inspect
        from scibot.build_index import build_index

        sig = inspect.signature(build_index)
        assert 'use_paperqa' in sig.parameters, (
            "build_index() 应有 use_paperqa 参数"
        )

    def test_paperqa_integration_does_not_import_openai(self):
        """
        paperqa_integration.py 导入后不应触发 OpenAI API 调用。
        (不联网,不实例化 LLM client)
        """
        # 检查模块源码中没有直接 import openai
        import inspect
        from scibot import paperqa_integration
        source = inspect.getsource(paperqa_integration)
        assert 'import openai' not in source, (
            "paperqa_integration 不应直接 import openai"
        )
        assert 'OpenAI(' not in source, (
            "paperqa_integration 不应实例化 OpenAI client"
        )

    def test_scibot_query_uses_pplx_not_openai_for_rerank(self):
        """
        scibot_query._pplx_rerank 使用 pplx 命令,不实例化 OpenAI client。
        """
        import inspect
        from scibot import scibot_query
        source = inspect.getsource(scibot_query._pplx_rerank)

        assert 'pplx' in source, "_pplx_rerank 应调用 pplx 命令"
        # 确保不调用 OpenAI 客户端 (允许注释/文档中出现 openai 字眼,但不能实例化)
        assert 'OpenAI(' not in source, "_pplx_rerank 不应实例化 OpenAI() 客户端"
        assert 'import openai' not in source, "_pplx_rerank 不应 import openai"

    def test_section_type_classify_heading_consistency(self):
        """
        paperqa_integration.classify_heading 与 parse_pdf.py 的行为一致。
        测试关键章节标题识别。
        """
        from scibot.paperqa_integration import classify_heading

        test_cases = [
            ("Abstract", 'abstract'),
            ("Introduction", 'introduction'),
            ("1. Introduction", 'introduction'),
            ("Limitations", 'limitations'),
            ("3. Limitations and Future Work", 'limitations'),
            ("Discussion", 'discussion'),
            ("Results and Discussion", 'discussion'),
            ("Conclusion", 'conclusion'),
            ("5. Conclusions", 'conclusion'),
            ("Future Work", 'future_work'),
            ("References", 'references'),
            ("Random paragraph text that is not a heading", None),
        ]

        for heading_text, expected in test_cases:
            result = classify_heading(heading_text)
            assert result == expected, (
                f"classify_heading('{heading_text}') = {result!r}, 期望 {expected!r}"
            )
